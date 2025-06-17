"""
Google Cloud Function that triggers on GCS uploads to automatically process documents
and initiate incremental training when thresholds are met.

Deploy with:
gcloud functions deploy document-ai-auto-trainer \
    --runtime python39 \
    --trigger-resource YOUR_BUCKET_NAME \
    --trigger-event google.storage.object.finalize \
    --entry-point process_document_upload \
    --set-env-vars GCP_PROJECT_ID=YOUR_PROJECT,DOCUMENT_AI_PROCESSOR_ID=YOUR_PROCESSOR_ID
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from google.cloud import documentai_v1 as documentai
from google.cloud import firestore
from google.cloud import workflows_v1
from google.cloud.workflows import executions_v1
from google.cloud import storage
from google.api_core.client_options import ClientOptions

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
PROCESSOR_ID = os.environ.get('DOCUMENT_AI_PROCESSOR_ID')
LOCATION = os.environ.get('DOCUMENT_AI_LOCATION', 'us')
WORKFLOW_NAME = os.environ.get('WORKFLOW_NAME', 'document-ai-training-workflow')
FIRESTORE_COLLECTION = 'processed_documents'
TRAINING_COLLECTION = 'training_batches'
CONFIG_COLLECTION = 'training_configs'

# Initialize clients
db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
workflow_client = workflows_v1.WorkflowsClient()
workflow_execution_client = executions_v1.ExecutionsClient()

# Document AI client
opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)


def process_document_upload(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Cloud Function triggered by GCS object creation.
    Processes the document and checks if training should be triggered.
    """
    try:
        # Extract event details
        bucket_name = event['bucket']
        file_name = event['name']
        content_type = event.get('contentType', '')
        
        logger.info(f"Processing new file: gs://{bucket_name}/{file_name}")
        
        # Filter only PDF files in the documents folder
        if not file_name.startswith('documents/') or not content_type == 'application/pdf':
            logger.info(f"Skipping non-document file: {file_name}")
            return {'status': 'skipped', 'reason': 'Not a document PDF'}
        
        # Check if document already processed
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(file_name)
        existing_doc = doc_ref.get()
        
        if existing_doc.exists and existing_doc.to_dict().get('status') == 'completed':
            logger.info(f"Document already processed: {file_name}")
            return {'status': 'skipped', 'reason': 'Already processed'}
        
        # Create document record
        document_id = file_name.replace('/', '_').replace('.pdf', '')
        gcs_uri = f"gs://{bucket_name}/{file_name}"
        
        doc_data = {
            'document_id': document_id,
            'gcs_uri': gcs_uri,
            'bucket': bucket_name,
            'file_name': file_name,
            'processor_id': PROCESSOR_ID,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc),
            'used_for_training': False
        }
        
        # Check if processor has a trained version
        processor_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        has_trained_version = check_processor_versions(processor_path)
        
        if has_trained_version:
            # Process document immediately
            result = process_with_document_ai(gcs_uri, processor_path)
            
            doc_data.update({
                'status': 'completed',
                'document_type': result.get('document_type', 'OTHER'),
                'confidence_score': result.get('confidence', 0.0),
                'processed_at': datetime.now(timezone.utc),
                'extracted_data': result.get('extracted_data', {})
            })
        else:
            # Store for initial training
            logger.info("No trained version available - storing for initial training")
            doc_data['status'] = 'pending_initial_training'
        
        # Save document record
        doc_ref.set(doc_data)
        
        # Check if we should trigger training
        should_train, training_type = check_training_conditions()
        
        if should_train:
            logger.info(f"Triggering {training_type} training")
            trigger_training_workflow(training_type)
            return {
                'status': 'success',
                'document_id': document_id,
                'training_triggered': True,
                'training_type': training_type
            }
        
        return {
            'status': 'success',
            'document_id': document_id,
            'training_triggered': False
        }
        
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        return {
            'status': 'error',
            'error': str(e)
        }


def check_processor_versions(processor_path: str) -> bool:
    """Check if processor has any trained versions."""
    try:
        request = documentai.ListProcessorVersionsRequest(parent=processor_path)
        versions = docai_client.list_processor_versions(request=request)
        
        for version in versions:
            if version.state == documentai.ProcessorVersion.State.DEPLOYED:
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking processor versions: {str(e)}")
        return False


def process_with_document_ai(gcs_uri: str, processor_path: str) -> Dict[str, Any]:
    """Process document with Document AI."""
    try:
        # Get the default processor version
        processor = docai_client.get_processor(name=processor_path)
        processor_name = processor.default_processor_version or processor_path
        
        # Read document from GCS
        bucket_name = gcs_uri.split('/')[2]
        blob_name = '/'.join(gcs_uri.split('/')[3:])
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        content = blob.download_as_bytes()
        
        # Process document
        request = documentai.ProcessRequest(
            name=processor_name,
            raw_document=documentai.RawDocument(
                content=content,
                mime_type="application/pdf"
            ),
            skip_human_review=True
        )
        
        result = docai_client.process_document(request=request)
        
        # Extract classification results
        document_type = 'OTHER'
        confidence = 0.0
        
        if result.document.entities:
            for entity in result.document.entities:
                if entity.type_:
                    document_type = entity.type_.upper().replace(' ', '_')
                    confidence = entity.confidence
                    break
        
        return {
            'document_type': document_type,
            'confidence': confidence,
            'extracted_data': {
                'text_length': len(result.document.text) if result.document.text else 0,
                'page_count': len(result.document.pages) if result.document.pages else 0,
                'entities': [
                    {
                        'type': e.type_,
                        'text': e.mention_text,
                        'confidence': e.confidence
                    }
                    for e in result.document.entities
                ] if result.document.entities else []
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing with Document AI: {str(e)}")
        raise


def check_training_conditions() -> tuple[bool, str]:
    """
    Check if training conditions are met.
    Returns (should_train, training_type)
    """
    try:
        # Get training configuration
        config_ref = db.collection(CONFIG_COLLECTION).document(PROCESSOR_ID)
        config_doc = config_ref.get()
        
        if not config_doc.exists:
            # Create default config
            default_config = {
                'enabled': True,
                'min_documents_for_initial_training': 10,
                'min_documents_for_incremental': 5,
                'min_accuracy_for_deployment': 0.7,
                'check_interval_minutes': 60,
                'created_at': datetime.now(timezone.utc)
            }
            config_ref.set(default_config)
            config = default_config
        else:
            config = config_doc.to_dict()
        
        if not config.get('enabled', True):
            return False, ''
        
        # Check for active training
        active_training = db.collection(TRAINING_COLLECTION).where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', 'in', ['pending', 'training', 'deploying']
        ).limit(1).get()
        
        if active_training:
            logger.info("Active training already in progress")
            return False, ''
        
        # Count documents by status
        pending_initial = db.collection(FIRESTORE_COLLECTION).where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', '==', 'pending_initial_training'
        ).get()
        
        unused_completed = db.collection(FIRESTORE_COLLECTION).where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', '==', 'completed'
        ).where(
            'used_for_training', '==', False
        ).get()
        
        pending_count = len(pending_initial)
        unused_count = len(unused_completed)
        
        logger.info(f"Training check - Pending: {pending_count}, Unused completed: {unused_count}")
        
        # Check for initial training
        if pending_count >= config.get('min_documents_for_initial_training', 10):
            return True, 'initial'
        
        # Check for incremental training
        if unused_count >= config.get('min_documents_for_incremental', 5):
            return True, 'incremental'
        
        return False, ''
        
    except Exception as e:
        logger.error(f"Error checking training conditions: {str(e)}")
        return False, ''


def trigger_training_workflow(training_type: str):
    """Trigger the training workflow."""
    try:
        # Create workflow execution
        parent = workflow_client.workflow_path(PROJECT_ID, LOCATION, WORKFLOW_NAME)
        
        execution = workflows_v1.Execution(
            argument=json.dumps({
                'processor_id': PROCESSOR_ID,
                'training_type': training_type,
                'triggered_at': datetime.now(timezone.utc).isoformat()
            })
        )
        
        response = workflow_execution_client.create_execution(
            parent=parent,
            execution=execution
        )
        
        logger.info(f"Started workflow execution: {response.name}")
        
    except Exception as e:
        logger.error(f"Error triggering workflow: {str(e)}")
        raise


# Additional helper functions for batch processing
def create_batch_training_job(training_docs: list) -> str:
    """
    Create a batch training job using Document AI's batch processing.
    """
    try:
        processor_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        
        # Create processor version for training
        model_display_name = f"auto-train-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # Get document labels from Firestore
        labeled_documents = []
        for doc in training_docs:
            doc_data = doc.to_dict()
            labeled_documents.append({
                'gcs_uri': doc_data['gcs_uri'],
                'document_type': doc_data.get('document_type', 'OTHER')
            })
        
        # Create training request
        processor_version = documentai.ProcessorVersion(
            display_name=model_display_name
        )
        
        # Prepare training documents
        training_gcs_documents = [
            documentai.Document(
                uri=doc['gcs_uri'],
                type_=doc['document_type']
            )
            for doc in labeled_documents
        ]
        
        request = documentai.TrainProcessorVersionRequest(
            parent=processor_path,
            processor_version=processor_version,
            document_schema=create_document_schema(labeled_documents),
            input_data=documentai.TrainProcessorVersionRequest.InputData(
                training_documents=documentai.BatchDocumentsInputConfig(
                    gcs_documents=documentai.GcsDocuments(
                        documents=[
                            documentai.GcsDocument(
                                gcs_uri=doc['gcs_uri'],
                                mime_type="application/pdf"
                            )
                            for doc in labeled_documents
                        ]
                    )
                )
            )
        )
        
        # Start training
        operation = docai_client.train_processor_version(request=request)
        
        logger.info(f"Started training operation: {operation.name}")
        return operation.name
        
    except Exception as e:
        logger.error(f"Error creating batch training job: {str(e)}")
        raise


def create_document_schema(labeled_documents: list) -> documentai.DocumentSchema:
    """Create document schema for training."""
    schema = documentai.DocumentSchema()
    
    # Get unique document types
    doc_types = set(doc['document_type'] for doc in labeled_documents)
    
    for doc_type in doc_types:
        entity_type = documentai.DocumentSchema.EntityType(
            type_=doc_type,
            display_name=doc_type.replace('_', ' ').title()
        )
        schema.entity_types.append(entity_type)
    
    return schema