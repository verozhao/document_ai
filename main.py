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
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from google.cloud import documentai_v1 as documentai
from google.cloud import firestore
from google.cloud import storage
from google.api_core.client_options import ClientOptions
from google.cloud.workflows import executions_v1
from google.cloud.workflows.executions_v1 import Execution
import functions_framework
from flask import Request
from batch_processing import process_new_document as process_doc
from training_trigger import check_training_trigger as check_training

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
PROCESSOR_ID = os.environ.get('DOCUMENT_AI_PROCESSOR_ID')
LOCATION = os.environ.get('DOCUMENT_AI_LOCATION', 'us')
WORKFLOW_NAME = os.environ.get('WORKFLOW_NAME', 'workflow-1-veronica')
WORKFLOW_LOCATION = 'us-central1'  # Workflows are in us-central1
FIRESTORE_COLLECTION = 'processed_documents'
TRAINING_COLLECTION = 'training_batches'
CONFIG_COLLECTION = 'training_configs'

# Initialize clients
db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
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

        filename_only = os.path.basename(file_name)
        name_without_ext = filename_only.rsplit('.', 1)[0] if '.' in filename_only else filename_only
        file_hash = hashlib.md5(file_name.encode()).hexdigest()[:8]
        # Replace spaces with underscores and ensure the name is safe
        safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name_without_ext.replace(' ', '_'))[:40]
        document_id = f"{safe_name}_{file_hash}"
        logger.info(f"Generated document ID: {document_id} for file: {file_name}")
        
        # Check if document already processed
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(document_id)
        existing_doc = doc_ref.get()
        
        if existing_doc.exists and existing_doc.to_dict().get('status') == 'completed':
            logger.info(f"Document already processed: {document_id}")
            return {'status': 'skipped', 'reason': 'Already processed'}
        
        # Create document record
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
            logger.info("Processing document with trained model")
            result = process_with_document_ai(gcs_uri, processor_path)
            
            doc_data.update({
                'status': 'completed',
                'document_type': result.get('document_type', 'OTHER'),
                'confidence_score': result.get('confidence', 0.0),
                'processed_at': datetime.now(timezone.utc),
                'extracted_data': result.get('extracted_data', {})
            })
            logger.info(f"Document processed - Type: {result.get('document_type')}, Confidence: {result.get('confidence')}")
        else:
            # Store for initial training
            logger.info("No trained version available - storing for initial training")
            doc_data['status'] = 'pending_initial_training'
        
        # Save document record
        doc_ref.set(doc_data)
        logger.info(f"Document record saved: {document_id}")
        
        # Check if we should trigger training
        should_train, training_type = check_training_conditions()
        
        if should_train:
            logger.info(f"Triggering {training_type} training")
            try:
                trigger_training_workflow(training_type)
                return {
                    'status': 'success',
                    'document_id': document_id,
                    'training_triggered': True,
                    'training_type': training_type
                }
            except Exception as e:
                logger.error(f"Failed to trigger workflow: {str(e)}")
                return {
                    'status': 'partial_success',
                    'document_id': document_id,
                    'training_triggered': False,
                    'error': f"Workflow trigger failed: {str(e)}"
                }
        
        return {
            'status': 'success',
            'document_id': document_id,
            'training_triggered': False
        }
        
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


def check_processor_versions(processor_path: str) -> bool:
    """Check if processor has any trained versions."""
    try:
        request = documentai.ListProcessorVersionsRequest(parent=processor_path)
        versions = docai_client.list_processor_versions(request=request)
        
        has_deployed = False
        for version in versions:
            logger.info(f"Found processor version: {version.display_name} - State: {version.state.name}")
            if version.state == documentai.ProcessorVersion.State.DEPLOYED:
                has_deployed = True
        
        return has_deployed
    except Exception as e:
        logger.error(f"Error checking processor versions: {str(e)}")
        return False


def process_with_document_ai(gcs_uri: str, processor_path: str) -> Dict[str, Any]:
    """Process document with Document AI."""
    try:
        # Get the default processor version
        processor = docai_client.get_processor(name=processor_path)
        processor_name = processor.default_processor_version or processor_path
        
        logger.info(f"Using processor version: {processor_name}")
        
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
            # Create default config with LOWER thresholds for testing
            default_config = {
                'enabled': True,
                'min_documents_for_initial_training': 3,  # Lowered from 10
                'min_documents_for_incremental': 2,       # Lowered from 5
                'min_accuracy_for_deployment': 0.7,
                'check_interval_minutes': 60,
                'created_at': datetime.now(timezone.utc)
            }
            config_ref.set(default_config)
            config = default_config
            logger.info(f"Created default config with thresholds: initial={default_config['min_documents_for_initial_training']}, incremental={default_config['min_documents_for_incremental']}")
        else:
            config = config_doc.to_dict()
            logger.info(f"Using existing config with thresholds: initial={config.get('min_documents_for_initial_training')}, incremental={config.get('min_documents_for_incremental')}")
        
        if not config.get('enabled', True):
            logger.info("Training is disabled in configuration")
            return False, ''
        
        # Check for active training
        active_training = db.collection(TRAINING_COLLECTION).where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', 'in', ['pending', 'preparing', 'training', 'deploying']
        ).limit(1).get()
        
        if active_training:
            logger.info("Active training already in progress")
            return False, ''
        
        # Count documents by status
        pending_initial = list(db.collection(FIRESTORE_COLLECTION).where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', '==', 'pending_initial_training'
        ).get())
        
        unused_completed = list(db.collection(FIRESTORE_COLLECTION).where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', '==', 'completed'
        ).where(
            'used_for_training', '==', False
        ).get())
        
        pending_count = len(pending_initial)
        unused_count = len(unused_completed)
        
        logger.info(f"Training check - Pending initial: {pending_count}, Unused completed: {unused_count}")
        
        # Log document IDs for debugging
        if pending_count > 0:
            logger.info(f"Pending initial training documents: {[doc.id for doc in pending_initial[:5]]}")
        if unused_count > 0:
            logger.info(f"Unused completed documents: {[doc.id for doc in unused_completed[:5]]}")
        
        # Check for initial training
        min_initial = config.get('min_documents_for_initial_training', 3)
        if pending_count >= min_initial:
            logger.info(f"Initial training threshold met: {pending_count} >= {min_initial}")
            return True, 'initial'
        elif pending_count > 0:
            logger.info(f"Initial training threshold NOT met: {pending_count} < {min_initial}")
        
        # Check for incremental training
        min_incremental = config.get('min_documents_for_incremental', 2)
        if unused_count >= min_incremental:
            logger.info(f"Incremental training threshold met: {unused_count} >= {min_incremental}")
            return True, 'incremental'
        elif unused_count > 0:
            logger.info(f"Incremental training threshold NOT met: {unused_count} < {min_incremental}")
        
        return False, ''
        
    except Exception as e:
        logger.error(f"Error checking training conditions: {str(e)}", exc_info=True)
        return False, ''


def trigger_training_workflow(training_type: str):
    """Trigger the training workflow."""
    try:
        # Construct the parent path correctly
        parent = f"projects/{PROJECT_ID}/locations/{WORKFLOW_LOCATION}/workflows/{WORKFLOW_NAME}"
        
        # Create execution request
        execution = Execution(
            argument=json.dumps({
                'processor_id': PROCESSOR_ID,
                'training_type': training_type,
                'triggered_at': datetime.now(timezone.utc).isoformat()
            })
        )
        
        # Create execution
        request = executions_v1.CreateExecutionRequest(
            parent=parent,
            execution=execution
        )
        
        response = workflow_execution_client.create_execution(request=request)
        
        logger.info(f"Started workflow execution: {response.name}")
        logger.info(f"Workflow state: {response.state.name}")
        
    except Exception as e:
        logger.error(f"Error triggering workflow: {str(e)}", exc_info=True)
        raise

@functions_framework.http
def process_new_document(request: Request):
    """Entry point for document processing function."""
    return process_doc(request)

@functions_framework.http
def check_training_trigger(request: Request):
    """Entry point for training trigger function."""
    return check_training(request)