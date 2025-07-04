"""
Google Cloud Function that triggers on GCS uploads to automatically process documents
and initiate incremental training when thresholds are met.
"""

import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from google.cloud import documentai_v1 as documentai
from google.cloud import firestore
from google.cloud import storage
from google.api_core.client_options import ClientOptions
from google.cloud.workflows import executions_v1
from google.cloud.workflows.executions_v1 import Execution
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
PROCESSOR_ID = os.environ.get('DOCUMENT_AI_PROCESSOR_ID')
OCR_PROCESSOR_ID = os.environ.get('OCR_PROCESSOR_ID', '2369784b09e9d56a')  # OCR processor for text extraction
LOCATION = os.environ.get('DOCUMENT_AI_LOCATION', 'us')
WORKFLOW_NAME = os.environ.get('WORKFLOW_NAME', 'automation-workflow')
WORKFLOW_LOCATION = 'us-central1'
BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME', 'document-ai-test-veronica')

# Initialize clients
db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
workflow_execution_client = executions_v1.ExecutionsClient()

# Document AI client
opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)

# The following serves as a fallback for auto-labeling. It is not used in the current implementation.
# If the file is not in a subfolder (e.g., just documents/doc1.pdf), the function then tries to infer the label from the filename itself by searching for keywords defined in DOCUMENT_TYPE_KEYWORDS.
# DOCUMENT_TYPE_KEYWORDS = {
#     'capital_call': ['capital call', 'drawdown', 'commitment', 'capital contribution'],
#     'distribution_notice': ['distribution', 'proceeds', 'realized', 'dividend'],
#     'financial_statement': ['balance sheet', 'income statement', 'financial statement', 'profit loss'],
#     'portfolio_summary': ['portfolio', 'holdings', 'investments', 'asset allocation'],
#     'tax': ['tax', 'k-1', 'schedule k', '1099', '1040'],
# }


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

        # Generate unique document ID
        filename_only = os.path.basename(file_name)
        name_without_ext = filename_only.rsplit('.', 1)[0] if '.' in filename_only else filename_only
        file_hash = hashlib.md5(file_name.encode()).hexdigest()[:8]
        safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name_without_ext.replace(' ', '_'))[:40]
        document_id = f"{safe_name}_{file_hash}"
        
        # Check if document already processed
        doc_ref = db.collection('processed_documents').document(document_id)
        existing_doc = doc_ref.get()
        
        if existing_doc.exists and existing_doc.to_dict().get('status') == 'completed':
            logger.info(f"Document already processed: {document_id}")
            return {'status': 'skipped', 'reason': 'Already processed'}
        
        # Create document record
        gcs_uri = f"gs://{bucket_name}/{file_name}"
        
        # Auto-label document based on filename or content
        document_label = auto_label_document(file_name, gcs_uri)
        
        doc_data = {
            'document_id': document_id,
            'gcs_uri': gcs_uri,
            'bucket': bucket_name,
            'file_name': file_name,
            'processor_id': PROCESSOR_ID,
            'status': 'pending',
            'document_label': document_label,  # Important: Store the label for training
            'created_at': datetime.now(timezone.utc),
            'used_for_training': False
        }
        
        # Check if processor has a trained version
        processor_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        has_trained_version = check_processor_versions(processor_path)
        
        if has_trained_version:
            try:
                # Process document immediately
                logger.info("Processing document with trained model")
                result = process_with_document_ai(gcs_uri, processor_path)
                
                # Update document type based on prediction
                predicted_type = result.get('document_type', 'OTHER')
                confidence = result.get('confidence', 0.0)
                
                # If confidence is low, keep the auto-label for retraining
                if confidence < 0.7 and document_label != 'OTHER':
                    logger.info(f"Low confidence prediction ({confidence}), keeping auto-label: {document_label}")
                else:
                    document_label = predicted_type
                
                doc_data.update({
                    'status': 'completed',
                    'document_type': predicted_type,
                    'document_label': document_label,  # This is what will be used for training
                    'confidence_score': confidence,
                    'processed_at': datetime.now(timezone.utc),
                    'extracted_data': result.get('extracted_data', {})
                })
            except Exception as processing_error:
                logger.error(f"Error processing with trained model: {str(processing_error)}")
                # Fall back to storing for training
                logger.info("Falling back to store for training due to processing error")
                doc_data['status'] = 'pending_initial_training'
        else:
            # Store for initial training
            logger.info("No deployed trained version available - storing for initial training")
            doc_data['status'] = 'pending_initial_training'
        
        # Save document record
        doc_ref.set(doc_data)
        logger.info(f"Document saved with label: {document_label}")
        
        # Check if we should trigger training
        should_train, training_type = check_training_conditions()
        
        if should_train:
            logger.info(f"Triggering {training_type} training")
            try:
                trigger_training_workflow(training_type)
                return {
                    'status': 'success',
                    'document_id': document_id,
                    'document_label': document_label,
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
            'document_label': document_label,
            'training_triggered': False
        }
        
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }


def auto_label_document(file_name: str, gcs_uri: str) -> str:
    """
    Auto-label document based on subfolder name.
    The subfolder name is used as the document label. If no subfolder, returns 'OTHER'.
    """
    # Extract subfolder name from the file path
    path_parts = file_name.split('/')
    if len(path_parts) > 2:  # Check if file is in a subfolder
        subfolder = path_parts[1]  # Get the subfolder name
        # Use exact folder name, just replace spaces with underscores
        label = subfolder.replace(' ', '_')
        logger.info(f"Auto-labeled document as {label} based on subfolder")
        return label
    
    # # If no subfolder found, try to determine from filename
    # file_name_lower = file_name.lower()
    # for doc_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
    #     if any(keyword in file_name_lower for keyword in keywords):
    #         logger.info(f"Auto-labeled document as {doc_type} based on filename")
    #         return doc_type
    
    # Default to OTHER if no label can be determined
    logger.info("Could not determine document type, labeled as OTHER")
    return 'OTHER'


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
            # For custom classifiers, the entity type is the document class
            for entity in result.document.entities:
                if entity.type_:
                    document_type = entity.type_
                    confidence = entity.confidence
                    break
        
        # Also check for labels in the document
        if hasattr(result.document, 'labels') and result.document.labels:
            for label in result.document.labels:
                if label.confidence > confidence:
                    document_type = label.name
                    confidence = label.confidence
        
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


def check_training_conditions() -> Tuple[bool, str]:
    """
    Check if training conditions are met.
    Returns (should_train, training_type)
    """
    try:
        # Get training configuration
        config_ref = db.collection('training_configs').document(PROCESSOR_ID)
        config_doc = config_ref.get()
        
        if not config_doc.exists:
            # Create default config
            default_config = {
                'enabled': True,
                'min_documents_for_initial_training': 3,
                'min_documents_for_incremental': 2,
                'min_accuracy_for_deployment': 0,
                'check_interval_minutes': 60,
                'created_at': datetime.now(timezone.utc)
            }
            config_ref.set(default_config)
            config = default_config
        else:
            config = config_doc.to_dict()
        
        if not config.get('enabled', True):
            logger.info("Training is disabled in configuration")
            return False, ''
        
        # Check for active training
        active_training = db.collection('training_batches').where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', 'in', ['pending', 'preparing', 'training', 'deploying']
        ).limit(1).get()
        
        if active_training:
            logger.info("Active training already in progress")
            return False, ''
            
        # Temporarily disabled: Check for recent workflow triggers (within last 2 minutes) to prevent quota exhaustion
        # Note: Index creation in progress, will re-enable once index is ready
        # recent_threshold = datetime.now(timezone.utc).timestamp() - 120  # 2 minutes ago
        # try:
        #     recent_workflows = db.collection('workflow_triggers').where(
        #         'processor_id', '==', PROCESSOR_ID
        #     ).where(
        #         'triggered_at', '>', recent_threshold
        #     ).limit(1).get()
        #     
        #     if recent_workflows:
        #         logger.info("Recent workflow execution detected, waiting to prevent quota exhaustion")
        #         return False, ''
        # except Exception as e:
        #     logger.warning(f"Workflow trigger check failed (index building?): {str(e)}")
        
        # Count documents by status with proper labels
        pending_initial_query = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', '==', 'pending_initial_training'
        )
        
        unused_completed_query = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', '==', 'completed'
        ).where(
            'used_for_training', '==', False
        )
        
        pending_initial_docs = list(pending_initial_query.get())
        unused_completed_docs = list(unused_completed_query.get())
        
        # Filter out documents without labels
        pending_initial = [doc for doc in pending_initial_docs if doc.to_dict().get('document_label')]
        unused_completed = [doc for doc in unused_completed_docs if doc.to_dict().get('document_label')]
        
        pending_count = len(pending_initial)
        unused_count = len(unused_completed)
        
        logger.info(f"Training check - Labeled pending initial: {pending_count}, Labeled unused completed: {unused_count}")
        
        # Check label distribution
        if pending_count > 0:
            label_dist = {}
            for doc in pending_initial:
                label = doc.to_dict().get('document_label', 'OTHER')
                label_dist[label] = label_dist.get(label, 0) + 1
            logger.info(f"Initial training label distribution: {label_dist}")
        
        if unused_count > 0:
            label_dist = {}
            for doc in unused_completed:
                label = doc.to_dict().get('document_label', 'OTHER')
                label_dist[label] = label_dist.get(label, 0) + 1
            logger.info(f"Incremental training label distribution: {label_dist}")
        
        # Check for initial training
        min_initial = config.get('min_documents_for_initial_training', 3)
        if pending_count >= min_initial:
            logger.info(f"Initial training threshold met: {pending_count} >= {min_initial}")
            return True, 'initial'
        
        # Check for incremental training
        min_incremental = config.get('min_documents_for_incremental', 2)
        if unused_count >= min_incremental:
            logger.info(f"Incremental training threshold met: {unused_count} >= {min_incremental}")
            return True, 'incremental'
        
        return False, ''
        
    except Exception as e:
        logger.error(f"Error checking training conditions: {str(e)}", exc_info=True)
        return False, ''


def create_labeled_document_json(doc_data: Dict[str, Any]) -> Optional[Dict]:
    """Create a labeled document in Document AI JSON format"""
    try:
        source_gcs_uri = doc_data.get('gcs_uri')
        doc_label = doc_data.get('document_label')
        
        if not source_gcs_uri or not doc_label:
            return None
            
        # Read document from GCS first to check size/pages
        bucket_name = source_gcs_uri.split('/')[2]
        blob_name = '/'.join(source_gcs_uri.split('/')[3:])
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        # Check file size (OCR processor has limits)
        blob_size = blob.size
        if blob_size and blob_size > 20 * 1024 * 1024:  # 20MB limit
            logger.warning(f"Document too large ({blob_size} bytes), using filename-based labeling only")
            return {
                "mimeType": "application/pdf",
                "text": f"Large document - processed with filename-based labeling: {doc_label}",
                "uri": source_gcs_uri,
                "entities": [
                    {
                        "type": doc_label,
                        "mentionText": doc_label,
                        "confidence": 1.0,
                        "textAnchor": {
                            "textSegments": [
                                {
                                    "startIndex": 0,
                                    "endIndex": len(doc_label)
                                }
                            ]
                        }
                    }
                ]
            }
        
        # Process document with OCR processor for text extraction
        request = documentai.ProcessRequest(
            name=f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{OCR_PROCESSOR_ID}",
            gcs_document=documentai.GcsDocument(
                gcs_uri=source_gcs_uri,
                mime_type="application/pdf"
            )
        )
        
        # Use OCR processor to get document text and structure
        ocr_processor_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{OCR_PROCESSOR_ID}"
        ocr_client = documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
        )
        
        try:
            result = ocr_client.process_document(request=request)
            
            if not result.document:
                logger.warning("OCR processing returned no document, using filename-based labeling only")
                return {
                    "mimeType": "application/pdf",
                    "text": f"OCR failed - processed with filename-based labeling: {doc_label}",
                    "uri": source_gcs_uri,
                    "entities": [
                        {
                            "type": doc_label,
                            "mentionText": doc_label,
                            "confidence": 1.0,
                            "textAnchor": {
                                "textSegments": [
                                    {
                                        "startIndex": 0,
                                        "endIndex": len(doc_label)
                                    }
                                ]
                            }
                        }
                    ]
                }
        except Exception as ocr_error:
            logger.error(f"OCR processing failed: {str(ocr_error)}, using filename-based labeling only")
            return {
                "mimeType": "application/pdf", 
                "text": f"OCR failed - processed with filename-based labeling: {doc_label}",
                "uri": source_gcs_uri,
                "entities": [
                    {
                        "type": doc_label,
                        "mentionText": doc_label,
                        "confidence": 1.0,
                        "textAnchor": {
                            "textSegments": [
                                {
                                    "startIndex": 0,
                                    "endIndex": len(doc_label)
                                }
                            ]
                        }
                    }
                ]
            }
            
        doc = result.document
        
        # Create labeled document with proper entities
        labeled_doc = {
            "mimeType": "application/pdf",
            "text": doc.text if doc.text else "",
            "pages": [
                {
                    "pageNumber": page.page_number,
                    "dimension": {
                        "width": page.dimension.width,
                        "height": page.dimension.height,
                        "unit": page.dimension.unit
                    } if page.dimension else {}
                } for page in doc.pages
            ],
            "uri": source_gcs_uri,
            "entities": [
                {
                    "type": doc_label,
                    "mentionText": doc_label,
                    "confidence": 1.0,
                    "textAnchor": {
                        "textSegments": [
                            {
                                "startIndex": 0,
                                "endIndex": len(doc_label)
                            }
                        ]
                    }
                }
            ]
        }
        
        return labeled_doc
        
    except Exception as e:
        logger.error(f"Error creating labeled document: {str(e)}")
        return None


def organize_training_documents(training_type: str) -> str:
    """
    Create properly labeled JSON documents for training.
    Returns the GCS prefix for training documents.
    """
    try:
        training_prefix = f"labeled_documents"
        
        # Query Firestore for training documents
        query = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).where(
            'status', '==', 'pending_initial_training' if training_type == 'initial' else 'completed'
        ).where(
            'used_for_training', '==', False
        ).where(
            'document_label', '>', ''
        ).limit(50)  # Limit to prevent timeout
        
        docs = list(query.get())
        logger.info(f"Found {len(docs)} documents to create labeled training data")
        
        bucket = storage_client.bucket(BUCKET_NAME)
        processed_count = 0
        
        for doc in docs:
            doc_data = doc.to_dict()
            doc_label = doc_data.get('document_label')
            
            if not doc_label:
                continue
                
            # Create labeled JSON document
            labeled_doc = create_labeled_document_json(doc_data)
            if labeled_doc:
                # Create JSON file path
                doc_id = doc.id
                json_filename = f"{doc_id}.json"
                json_path = f"{training_prefix}/{doc_label}/{json_filename}"
                
                # Upload labeled JSON document
                blob = bucket.blob(json_path)
                blob.upload_from_string(
                    json.dumps(labeled_doc),
                    content_type='application/json'
                )
                
                logger.info(f"Created labeled document: {json_path}")
                processed_count += 1
                
                # Limit processing to prevent timeout
                if processed_count >= 20:
                    logger.info(f"Processed {processed_count} documents, stopping to prevent timeout")
                    break
        
        training_gcs_prefix = f"gs://{BUCKET_NAME}/{training_prefix}/"
        logger.info(f"Created {processed_count} labeled documents in: {training_gcs_prefix}")
        
        return training_gcs_prefix
        
    except Exception as e:
        logger.error(f"Error organizing training documents: {str(e)}", exc_info=True)
        raise


def trigger_training_workflow(training_type: str):
    """Trigger the training workflow."""
    try:
        # Temporarily disabled: Record workflow trigger to prevent concurrent executions
        # Note: Index creation in progress, will re-enable once index is ready
        # trigger_record = {
        #     'processor_id': PROCESSOR_ID,
        #     'training_type': training_type,
        #     'triggered_at': datetime.now(timezone.utc).timestamp(),
        #     'status': 'triggering'
        # }
        # db.collection('workflow_triggers').add(trigger_record)
        
        # First organize documents in GCS
        training_prefix = organize_training_documents(training_type)
        
        parent = f"projects/{PROJECT_ID}/locations/{WORKFLOW_LOCATION}/workflows/{WORKFLOW_NAME}"
        
        # Create execution request
        execution = Execution(
            argument=json.dumps({
                'processor_id': PROCESSOR_ID,
                'training_type': training_type,
                'triggered_at': datetime.now(timezone.utc).isoformat(),
                'bucket_name': BUCKET_NAME,
                'location': LOCATION,
                'training_gcs_prefix': training_prefix
            })
        )
        
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