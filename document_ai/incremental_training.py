"""
Automated Training Manager that integrates with GCS triggers and Cloud Workflows.
This replaces the manual incremental_training.py with a fully automated version.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any
from collections import defaultdict

from google.cloud import documentai_v1 as documentai
from google.cloud import firestore
from google.cloud import storage
from google.cloud import pubsub_v1
from google.api_core.client_options import ClientOptions
from google.api_core import retry

from .models import (
    DocumentAIStatus,
    DocumentType,
    ProcessedDocument,
    IncrementalTrainingBatch,
    AutomatedTrainingConfig,
)

logger = logging.getLogger(__name__)


class AutomatedTrainingManager:
    """
    Fully automated training manager that works with GCS triggers.
    No manual intervention required - everything is event-driven.
    """

    def __init__(
        self,
        project_id: str,
        processor_id: str,
        location: str = "us",
        use_firestore: bool = True
    ):
        """Initialize the automated training manager."""
        self.project_id = project_id
        self.processor_id = processor_id
        self.location = location
        self.use_firestore = use_firestore
        
        # Initialize clients
        self.storage_client = storage.Client(project=project_id)
        self.pubsub_publisher = pubsub_v1.PublisherClient()
        
        if use_firestore:
            self.firestore_client = firestore.Client(project=project_id)
        
        # Document AI client
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        self.docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)
        
        # Processor path
        self.processor_path = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
        
        # Topics for Pub/Sub notifications
        self.training_topic = f"projects/{project_id}/topics/document-ai-training"
        self.notification_topic = f"projects/{project_id}/topics/document-ai-notifications"

    async def setup_automated_pipeline(self, bucket_name: str):
        """
        Set up the complete automated pipeline including:
        - GCS bucket notifications
        - Pub/Sub topics
        - Cloud Scheduler for periodic checks
        """
        try:
            # Create Pub/Sub topics
            await self._create_pubsub_topics()
            
            # Set up GCS notifications
            await self._setup_gcs_notifications(bucket_name)
            
            # Initialize processor if needed
            await self._initialize_processor()
            
            logger.info(f"Automated pipeline setup complete for processor {self.processor_id}")
            
        except Exception as e:
            logger.error(f"Error setting up automated pipeline: {str(e)}")
            raise

    async def _create_pubsub_topics(self):
        """Create Pub/Sub topics for the pipeline."""
        try:
            # Create training topic
            try:
                self.pubsub_publisher.create_topic(request={"name": self.training_topic})
                logger.info(f"Created Pub/Sub topic: {self.training_topic}")
            except Exception as e:
                if "already exists" in str(e):
                    logger.info(f"Topic already exists: {self.training_topic}")
                else:
                    raise
            
            # Create notification topic
            try:
                self.pubsub_publisher.create_topic(request={"name": self.notification_topic})
                logger.info(f"Created Pub/Sub topic: {self.notification_topic}")
            except Exception as e:
                if "already exists" in str(e):
                    logger.info(f"Topic already exists: {self.notification_topic}")
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"Error creating Pub/Sub topics: {str(e)}")
            raise

    async def _setup_gcs_notifications(self, bucket_name: str):
        """Set up GCS bucket notifications to trigger on document uploads."""
        try:
            bucket = self.storage_client.bucket(bucket_name)
            
            # Create notification configuration
            notification = bucket.notification(
                topic_name=self.training_topic,
                event_types=["OBJECT_FINALIZE"],
                custom_attributes={
                    "processor_id": self.processor_id,
                    "document_type": "training_trigger"
                },
                payload_format="JSON_API_V1"
            )
            
            # Check if notification already exists
            existing_notifications = bucket.list_notifications()
            for existing in existing_notifications:
                if existing.topic_name == self.training_topic:
                    logger.info("GCS notification already exists")
                    return
            
            # Create the notification
            notification.create()
            logger.info(f"Created GCS notification for bucket {bucket_name}")
            
        except Exception as e:
            logger.error(f"Error setting up GCS notifications: {str(e)}")
            raise

    async def _initialize_processor(self):
        """Initialize processor with base configuration if needed."""
        try:
            # Check if processor exists and has versions
            processor = self.docai_client.get_processor(name=self.processor_path)
            
            # List processor versions
            versions_request = documentai.ListProcessorVersionsRequest(
                parent=self.processor_path
            )
            versions = self.docai_client.list_processor_versions(request=versions_request)
            
            has_deployed_version = any(
                v.state == documentai.ProcessorVersion.State.DEPLOYED 
                for v in versions
            )
            
            if not has_deployed_version:
                logger.info("No deployed processor version found - processor ready for initial training")
            else:
                logger.info(f"Processor has deployed version: {processor.default_processor_version}")
                
        except Exception as e:
            logger.error(f"Error initializing processor: {str(e)}")
            raise

    @retry.Retry(predicate=retry.if_exception_type(Exception))
    async def process_training_batch(self, batch_id: str, training_documents: List[Dict[str, Any]]):
        """
        Process a batch of documents for training.
        This is called by the Cloud Workflow.
        """
        try:
            logger.info(f"Processing training batch {batch_id} with {len(training_documents)} documents")
            
            # Create document schema
            schema = self._create_document_schema(training_documents)
            
            # Prepare training request
            model_display_name = f"auto-train-{batch_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            
            processor_version = documentai.ProcessorVersion(
                display_name=model_display_name,
                document_schema=schema
            )
            
            # Create training documents config
            gcs_documents = []
            for doc in training_documents:
                gcs_doc = documentai.GcsDocument(
                    gcs_uri=doc['gcs_uri'],
                    mime_type="application/pdf"
                )
                gcs_documents.append(gcs_doc)
            
            input_config = documentai.TrainProcessorVersionRequest.InputData(
                training_documents=documentai.BatchDocumentsInputConfig(
                    gcs_documents=documentai.GcsDocuments(documents=gcs_documents)
                )
            )
            
            # Check for base version
            base_version = await self._get_latest_deployed_version()
            
            # Create training request
            request = documentai.TrainProcessorVersionRequest(
                parent=self.processor_path,
                processor_version=processor_version,
                document_schema=schema,
                input_data=input_config,
                base_processor_version=base_version
            )
            
            # Start training
            operation = await asyncio.to_thread(
                self.docai_client.train_processor_version,
                request=request
            )
            
            logger.info(f"Started training operation: {operation.name}")
            
            # Publish notification
            await self._publish_notification({
                'event': 'training_started',
                'batch_id': batch_id,
                'operation_name': operation.name,
                'document_count': len(training_documents),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
            return operation.name
            
        except Exception as e:
            logger.error(f"Error processing training batch: {str(e)}")
            await self._publish_notification({
                'event': 'training_failed',
                'batch_id': batch_id,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            raise

    def _create_document_schema(self, training_documents: List[Dict[str, Any]]) -> documentai.DocumentSchema:
        """Create document schema for training based on document types."""
        schema = documentai.DocumentSchema()
        
        # Get unique document types
        doc_types = set()
        for doc in training_documents:
            doc_type = doc.get('document_type', 'OTHER')
            doc_types.add(doc_type)
        
        # Create entity types
        for doc_type in doc_types:
            entity_type = documentai.DocumentSchema.EntityType(
                type_=doc_type,
                display_name=doc_type.replace('_', ' ').title(),
                base_types=["document"]
            )
            
            # Add properties based on document type
            if doc_type == "CAPITAL_CALL":
                entity_type.properties.extend([
                    documentai.DocumentSchema.EntityType.Property(
                        name="call_amount",
                        display_name="Call Amount",
                        value_type="money"
                    ),
                    documentai.DocumentSchema.EntityType.Property(
                        name="due_date",
                        display_name="Due Date",
                        value_type="datetime"
                    )
                ])
            elif doc_type == "FINANCIAL_STATEMENT":
                entity_type.properties.extend([
                    documentai.DocumentSchema.EntityType.Property(
                        name="total_assets",
                        display_name="Total Assets",
                        value_type="money"
                    ),
                    documentai.DocumentSchema.EntityType.Property(
                        name="total_liabilities",
                        display_name="Total Liabilities",
                        value_type="money"
                    )
                ])
            
            schema.entity_types.append(entity_type)
        
        return schema

    async def _get_latest_deployed_version(self) -> Optional[str]:
        """Get the latest deployed processor version."""
        try:
            request = documentai.ListProcessorVersionsRequest(
                parent=self.processor_path
            )
            versions = self.docai_client.list_processor_versions(request=request)
            
            for version in versions:
                if version.state == documentai.ProcessorVersion.State.DEPLOYED:
                    return version.name
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest deployed version: {str(e)}")
            return None

    async def _publish_notification(self, message: Dict[str, Any]):
        """Publish notification to Pub/Sub."""
        try:
            # Convert message to JSON
            message_json = json.dumps(message)
            message_bytes = message_json.encode('utf-8')
            
            # Publish message
            future = self.pubsub_publisher.publish(
                self.notification_topic,
                message_bytes,
                processor_id=self.processor_id
            )
            
            # Wait for publish to complete
            message_id = await asyncio.to_thread(future.result)
            logger.info(f"Published notification: {message_id}")
            
        except Exception as e:
            logger.error(f"Error publishing notification: {str(e)}")

    async def monitor_training_operation(self, operation_name: str) -> Dict[str, Any]:
        """Monitor a training operation until completion."""
        max_wait_time = timedelta(hours=3)
        start_time = datetime.now(timezone.utc)
        check_interval = 60  # seconds
        
        while True:
            try:
                # Check operation status
                operation = await asyncio.to_thread(
                    self.docai_client._transport.operations_client.get_operation,
                    name=operation_name
                )
                
                if operation.done:
                    if operation.error:
                        logger.error(f"Training operation failed: {operation.error}")
                        return {
                            'status': 'failed',
                            'error': str(operation.error),
                            'operation_name': operation_name
                        }
                    else:
                        logger.info(f"Training operation completed successfully")
                        # Extract processor version from response
                        processor_version = documentai.ProcessorVersion.pb(
                            documentai.ProcessorVersion()
                        )
                        operation.response.Unpack(processor_version)
                        
                        return {
                            'status': 'completed',
                            'processor_version': processor_version.name,
                            'operation_name': operation_name
                        }
                
                # Check timeout
                elapsed_time = datetime.now(timezone.utc) - start_time
                if elapsed_time > max_wait_time:
                    logger.error(f"Training operation timed out after {max_wait_time}")
                    return {
                        'status': 'timeout',
                        'error': f'Operation timed out after {max_wait_time}',
                        'operation_name': operation_name
                    }
                
                # Wait before next check
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Error monitoring training operation: {str(e)}")
                return {
                    'status': 'error',
                    'error': str(e),
                    'operation_name': operation_name
                }

    async def deploy_processor_version(self, processor_version_name: str) -> bool:
        """Deploy a trained processor version."""
        try:
            # Deploy the processor version
            request = documentai.DeployProcessorVersionRequest(
                name=processor_version_name
            )
            
            operation = await asyncio.to_thread(
                self.docai_client.deploy_processor_version,
                request=request
            )
            
            logger.info(f"Started deployment operation: {operation.name}")
            
            # Wait for deployment to complete (simplified for this example)
            await asyncio.sleep(300)  # 5 minutes
            
            # Set as default version
            processor = await asyncio.to_thread(
                self.docai_client.get_processor,
                name=self.processor_path
            )
            
            processor.default_processor_version = processor_version_name
            
            update_request = documentai.UpdateProcessorRequest(
                processor=processor,
                update_mask={"paths": ["default_processor_version"]}
            )
            
            await asyncio.to_thread(
                self.docai_client.update_processor,
                request=update_request
            )
            
            logger.info(f"Successfully deployed and set default version: {processor_version_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error deploying processor version: {str(e)}")
            return False

    async def get_training_statistics(self) -> Dict[str, Any]:
        """Get training statistics from Firestore."""
        if not self.use_firestore:
            return {}
            
        try:
            # Get training batches
            batches_ref = self.firestore_client.collection('training_batches')
            batches = batches_ref.where('processor_id', '==', self.processor_id).get()
            
            # Calculate statistics
            total_batches = len(batches)
            successful_batches = sum(1 for b in batches if b.to_dict().get('status') == 'deployed')
            total_documents_trained = sum(
                b.to_dict().get('document_count', 0) for b in batches
            )
            
            # Get latest batch
            latest_batch = None
            if batches:
                latest_batch = max(batches, key=lambda b: b.to_dict().get('started_at', datetime.min))
                
            return {
                'total_training_batches': total_batches,
                'successful_deployments': successful_batches,
                'total_documents_trained': total_documents_trained,
                'latest_batch': latest_batch.to_dict() if latest_batch else None,
                'success_rate': (successful_batches / total_batches * 100) if total_batches > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error getting training statistics: {str(e)}")
            return {}