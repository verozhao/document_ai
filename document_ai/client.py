"""
Enhanced Document AI client that integrates with the automated training pipeline.
This replaces the original client.py to work seamlessly with GCS triggers.
"""

import asyncio
import os
import logging
import uuid
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import documentai_v1 as documentai
from google.cloud import storage
from google.cloud import firestore
from google.api_core import retry
from google.api_core.client_options import ClientOptions

from .models import (
    DocumentAIStatus,
    DocumentType,
    ProcessedDocument,
    DocumentUploadResponse,
)

logger = logging.getLogger(__name__)


class EnhancedDocumentAIClient:
    """
    Enhanced client for Document AI with automated training support.
    Designed to work with GCS-triggered automated training pipeline.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: str = "us",
        processor_id: Optional[str] = None,
        gcs_bucket: Optional[str] = None,
        use_firestore: bool = True,
        auto_upload_to_gcs: bool = True,
    ):
        """
        Initialize the enhanced Document AI client.

        Args:
            project_id: GCP project ID
            location: GCP location
            processor_id: Document AI processor ID
            gcs_bucket: GCS bucket for document storage
            use_firestore: Whether to use Firestore for state management
            auto_upload_to_gcs: Automatically upload documents to GCS for training
        """
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        if not self.project_id:
            raise ValueError("GCP_PROJECT_ID environment variable is not set")
            
        self.location = location
        self.processor_id = processor_id or os.getenv("DOCUMENT_AI_PROCESSOR_ID")
        if not self.processor_id:
            raise ValueError("DOCUMENT_AI_PROCESSOR_ID environment variable is not set")
            
        self.gcs_bucket = gcs_bucket or os.getenv("GCS_BUCKET", f"{self.project_id}-document-ai")
        self.use_firestore = use_firestore
        self.auto_upload_to_gcs = auto_upload_to_gcs
        
        # Initialize clients
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        self.client = documentai.DocumentProcessorServiceClient(client_options=opts)
        self.storage_client = storage.Client(project=self.project_id)
        
        if use_firestore:
            self.firestore_client = firestore.Client(project=self.project_id)
        
        # Ensure bucket exists
        self._ensure_bucket_exists()
        
        # Processor path
        self.processor_path = f"projects/{self.project_id}/locations/{self.location}/processors/{self.processor_id}"
        
        # Check processor state
        self._check_processor_state()

    def _ensure_bucket_exists(self):
        """Ensure the GCS bucket exists."""
        try:
            self.bucket = self.storage_client.bucket(self.gcs_bucket)
            if not self.bucket.exists():
                self.bucket = self.storage_client.create_bucket(
                    self.gcs_bucket,
                    location="US"
                )
                logger.info(f"Created GCS bucket: {self.gcs_bucket}")
                
                # Create folder structure
                self._create_bucket_structure()
        except Exception as e:
            logger.error(f"Error with GCS bucket: {str(e)}")
            raise

    def _create_bucket_structure(self):
        """Create the required folder structure in GCS bucket."""
        folders = ['documents/', 'training/', 'processed/', 'failed/']
        for folder in folders:
            blob = self.bucket.blob(f"{folder}README.txt")
            blob.upload_from_string(f"This folder contains {folder.rstrip('/')} files")
        logger.info("Created bucket folder structure")

    def _check_processor_state(self):
        """Check processor state and available versions."""
        try:
            processor = self.client.get_processor(name=self.processor_path)
            self.processor_state = processor.state
            self.processor_type = processor.type_
            
            # Get default version
            self.default_version = processor.default_processor_version
            
            # List versions
            request = documentai.ListProcessorVersionsRequest(parent=self.processor_path)
            versions = list(self.client.list_processor_versions(request=request))
            
            self.has_deployed_version = any(
                v.state == documentai.ProcessorVersion.State.DEPLOYED for v in versions
            )
            
            logger.info(f"Processor state: {self.processor_state.name}")
            logger.info(f"Has deployed version: {self.has_deployed_version}")
            
        except Exception as e:
            logger.error(f"Error checking processor state: {str(e)}")
            self.has_deployed_version = False
            self.default_version = None

    @retry.Retry()
    async def upload_document_for_training(
        self,
        file_path: str,
        document_name: Optional[str] = None,
        expected_type: Optional[DocumentType] = None,
        process_immediately: bool = False,
    ) -> DocumentUploadResponse:
        """
        Upload a document to GCS for automated training pipeline.
        
        This method uploads documents to the GCS bucket where they will be
        automatically picked up by the Cloud Function for processing and training.
        
        Args:
            file_path: Local path to the document
            document_name: Optional custom name for the document
            expected_type: Optional expected document type
            process_immediately: If True, process immediately instead of waiting for GCS trigger
            
        Returns:
            DocumentUploadResponse with upload details
        """
        document_id = str(uuid.uuid4())
        
        try:
            # Determine document name
            if not document_name:
                document_name = Path(file_path).name
            
            # Upload to GCS documents folder
            blob_name = f"documents/{document_id}_{document_name}"
            blob = self.bucket.blob(blob_name)
            
            # Upload with metadata
            metadata = {
                'document_id': document_id,
                'expected_type': expected_type.value if expected_type else 'unknown',
                'upload_timestamp': datetime.now(timezone.utc).isoformat(),
                'processor_id': self.processor_id,
            }
            blob.metadata = metadata
            
            # Upload file
            blob.upload_from_filename(file_path)
            gcs_uri = f"gs://{self.gcs_bucket}/{blob_name}"
            
            logger.info(f"Uploaded document to GCS: {gcs_uri}")
            
            # If process_immediately is True, we can trigger processing
            # Otherwise, let the Cloud Function handle it
            if process_immediately and self.has_deployed_version:
                return await self._process_document_immediately(
                    gcs_uri, document_id, document_name, expected_type
                )
            
            # For automated pipeline, just return upload confirmation
            # The Cloud Function will handle processing and training
            return DocumentUploadResponse(
                document_id=document_id,
                gcp_document_id=document_id,
                document_path=gcs_uri,
                status=DocumentAIStatus.PENDING,
                document_type=expected_type,
                confidence_score=0.0,
                message="Document uploaded to GCS. Automated processing will begin shortly.",
                training_triggered=False,
            )
            
        except Exception as e:
            logger.error(f"Error uploading document: {str(e)}")
            return DocumentUploadResponse(
                document_id=document_id,
                gcp_document_id="",
                document_path="",
                status=DocumentAIStatus.FAILED,
                message=f"Error: {str(e)}",
                training_triggered=False,
            )
    async def upload_and_process_document(
        self,
        document_path: str,
        document_name: str,
        expected_type: Optional[DocumentType] = None,
        mime_type: str = "application/pdf"
    ) -> DocumentUploadResponse:
        """Upload and immediately process a document."""
        return await self.upload_document_for_training(
            file_path=document_path,
            document_name=document_name,
            expected_type=expected_type,
            process_immediately=True
        )

    async def _process_document_immediately(
        self,
        gcs_uri: str,
        document_id: str,
        document_name: str,
        expected_type: Optional[DocumentType],
    ) -> DocumentUploadResponse:
        """Process a document immediately using Document AI."""
        try:
            # Read document from GCS
            bucket_name = gcs_uri.split('/')[2]
            blob_name = '/'.join(gcs_uri.split('/')[3:])
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            content = blob.download_as_bytes()
            
            # Process with Document AI
            request = documentai.ProcessRequest(
                name=self.default_version or self.processor_path,
                raw_document=documentai.RawDocument(
                    content=content,
                    mime_type="application/pdf"
                ),
                skip_human_review=True,
            )
            
            result = await asyncio.to_thread(
                self.client.process_document,
                request=request,
            )
            
            # Extract results
            document_type, confidence = self._classify_document(result.document)
            extracted_data = self._extract_document_data(result.document, document_type)
            
            # Save to Firestore if enabled
            if self.use_firestore:
                doc_ref = self.firestore_client.collection('processed_documents').document(document_id)
                doc_ref.set({
                    'document_id': document_id,
                    'gcs_uri': gcs_uri,
                    'document_name': document_name,
                    'processor_id': self.processor_id,
                    'document_type': document_type.value,
                    'confidence_score': confidence,
                    'status': 'completed',
                    'extracted_data': extracted_data,
                    'processed_at': firestore.SERVER_TIMESTAMP,
                    'used_for_training': False,
                })
            
            return DocumentUploadResponse(
                document_id=document_id,
                gcp_document_id=document_id,
                document_path=gcs_uri,
                status=DocumentAIStatus.COMPLETED,
                document_type=document_type,
                confidence_score=confidence,
                message="Document processed successfully",
                training_triggered=False,
            )
            
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            raise

    def _classify_document(self, document: documentai.Document) -> Tuple[DocumentType, float]:
        """Classify document based on Document AI results."""
        # If document has classification entities
        if hasattr(document, 'entities') and document.entities:
            for entity in document.entities:
                if entity.type_:
                    entity_type = entity.type_.upper().replace(' ', '_')
                    # Try to match to DocumentType enum
                    try:
                        doc_type = DocumentType(entity_type.lower())
                        return doc_type, entity.confidence
                    except ValueError:
                        # Try partial matching
                        for dt in DocumentType:
                            if entity_type.lower() in dt.value or dt.value in entity_type.lower():
                                return dt, entity.confidence
                    
                    # High confidence but unknown type
                    if entity.confidence > 0.7:
                        return DocumentType.OTHER, entity.confidence
        
        # Fallback classification based on text content
        if hasattr(document, 'text') and document.text:
            text_lower = document.text.lower()
            
            classifications = [
                (DocumentType.CAPITAL_CALL, ['capital call', 'drawdown', 'commitment']),
                (DocumentType.DISTRIBUTION_NOTICE, ['distribution', 'proceeds', 'realized']),
                (DocumentType.FINANCIAL_STATEMENT, ['balance sheet', 'income statement', 'financial statement']),
                (DocumentType.PORTFOLIO_SUMMARY, ['portfolio', 'holdings', 'investments']),
                (DocumentType.TAX, ['tax', 'k-1', 'schedule k']),
            ]
            
            for doc_type, keywords in classifications:
                if any(keyword in text_lower for keyword in keywords):
                    return doc_type, 0.5  # Lower confidence for keyword matching
        
        return DocumentType.OTHER, 0.0

    def _extract_document_data(
        self, document: documentai.Document, document_type: DocumentType
    ) -> Dict[str, Any]:
        """Extract relevant data from document."""
        extracted_data = {
            'text_length': len(document.text) if document.text else 0,
            'page_count': len(document.pages) if document.pages else 0,
            'entities': [],
            'key_value_pairs': {},
        }
        
        # Extract entities
        if document.entities:
            for entity in document.entities:
                entity_data = {
                    'type': entity.type_,
                    'text': entity.mention_text,
                    'confidence': entity.confidence,
                }
                
                # Extract normalized values if available
                if entity.normalized_value:
                    if entity.normalized_value.money_value:
                        entity_data['value'] = {
                            'amount': entity.normalized_value.money_value.amount,
                            'currency': entity.normalized_value.money_value.currency_code,
                        }
                    elif entity.normalized_value.date_value:
                        entity_data['value'] = {
                            'date': f"{entity.normalized_value.date_value.year}-{entity.normalized_value.date_value.month:02d}-{entity.normalized_value.date_value.day:02d}"
                        }
                
                extracted_data['entities'].append(entity_data)
        
        # Extract form fields (key-value pairs)
        if document.pages:
            for page in document.pages:
                if page.form_fields:
                    for field in page.form_fields:
                        field_name = self._get_text(field.field_name, document)
                        field_value = self._get_text(field.field_value, document)
                        if field_name:
                            extracted_data['key_value_pairs'][field_name] = field_value
        
        return extracted_data

    def _get_text(self, layout: Any, document: documentai.Document) -> str:
        """Extract text from a layout element."""
        if not layout or not layout.text_anchor:
            return ""
        
        text_segments = []
        for segment in layout.text_anchor.text_segments:
            start_index = segment.start_index or 0
            end_index = segment.end_index or len(document.text)
            text_segments.append(document.text[start_index:end_index])
        
        return " ".join(text_segments).strip()

    async def get_training_status(self) -> Dict[str, Any]:
        """Get current training status from Firestore."""
        if not self.use_firestore:
            return {'error': 'Firestore not enabled'}
        
        try:
            # Get pending documents
            pending_docs = self.firestore_client.collection('processed_documents').where(
                'processor_id', '==', self.processor_id
            ).where(
                'status', 'in', ['pending', 'pending_initial_training']
            ).get()
            
            # Get unused completed documents
            unused_docs = self.firestore_client.collection('processed_documents').where(
                'processor_id', '==', self.processor_id
            ).where(
                'status', '==', 'completed'
            ).where(
                'used_for_training', '==', False
            ).get()
            
            # Get active training
            active_training = self.firestore_client.collection('training_batches').where(
                'processor_id', '==', self.processor_id
            ).where(
                'status', 'in', ['preparing', 'training', 'deploying']
            ).limit(1).get()
            
            # Get config
            config = self.firestore_client.collection('training_configs').document(
                self.processor_id
            ).get()
            
            config_data = config.to_dict() if config.exists else {}
            
            return {
                'has_model': self.has_deployed_version,
                'pending_documents': len(pending_docs),
                'available_for_training': len(unused_docs),
                'active_training': active_training[0].to_dict() if active_training else None,
                'next_training_threshold': config_data.get('min_documents_for_incremental', 5),
                'auto_training_enabled': config_data.get('enabled', True),
            }
            
        except Exception as e:
            logger.error(f"Error getting training status: {str(e)}")
            return {'error': str(e)}

    async def trigger_manual_training(self) -> bool:
        """
        Manually trigger training (for testing or forced retraining).
        Note: The automated system will handle this automatically.
        """
        if not self.use_firestore:
            logger.error("Cannot trigger training without Firestore")
            return False
        
        try:
            # Create a manual training trigger in Firestore
            trigger_ref = self.firestore_client.collection('training_triggers').document()
            trigger_ref.set({
                'processor_id': self.processor_id,
                'trigger_type': 'manual',
                'requested_at': firestore.SERVER_TIMESTAMP,
                'status': 'pending',
            })
            
            logger.info(f"Manual training trigger created: {trigger_ref.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error triggering manual training: {str(e)}")
            return False


# Convenience functions for the automated pipeline
async def upload_documents_batch(
    document_paths: List[str],
    processor_id: Optional[str] = None,
    document_types: Optional[List[DocumentType]] = None,
) -> List[DocumentUploadResponse]:
    """
    Upload multiple documents to the automated training pipeline.
    
    Args:
        document_paths: List of local file paths
        processor_id: Optional processor ID (uses env var if not provided)
        document_types: Optional list of expected types for each document
        
    Returns:
        List of upload responses
    """
    client = EnhancedDocumentAIClient(processor_id=processor_id)
    
    responses = []
    for i, path in enumerate(document_paths):
        expected_type = document_types[i] if document_types and i < len(document_types) else None
        response = await client.upload_document_for_training(
            file_path=path,
            expected_type=expected_type,
        )
        responses.append(response)
        
        # Small delay to avoid overwhelming the system
        await asyncio.sleep(0.5)
    
    return responses


async def check_automated_training_status(processor_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Check the status of the automated training system.
    
    Args:
        processor_id: Optional processor ID (uses env var if not provided)
        
    Returns:
        Dictionary with training status information
    """
    client = EnhancedDocumentAIClient(processor_id=processor_id)
    return await client.get_training_status()