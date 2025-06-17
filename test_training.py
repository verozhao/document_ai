"""Comprehensive test script for Document AI training pipeline."""

import asyncio
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from google.cloud import storage
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from document_ai import (
    EnhancedDocumentAIClient,
    DocumentType,
    ProcessedDocument,
    AutomatedTrainingConfig,
    IncrementalTrainingBatch,
    DocumentAIStatus,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def upload_to_gcs(local_file_path: str, bucket_name: str) -> str:
    """Upload a file to Google Cloud Storage.
    
    Args:
        local_file_path: Path to the local file
        bucket_name: Name of the GCS bucket
        
    Returns:
        GCS URI of the uploaded file
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    
    # Create a unique blob name to avoid conflicts
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    blob_name = f"documents/{timestamp}_{Path(local_file_path).name}"
    blob = bucket.blob(blob_name)
    
    # Upload the file
    blob.upload_from_filename(local_file_path)
    logger.info(f"Uploaded {Path(local_file_path).name} to gs://{bucket_name}/{blob_name}")
    
    return f"gs://{bucket_name}/{blob_name}"


async def init_db():
    """Initialize MongoDB connection and models."""
    try:
        client = AsyncIOMotorClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)
        
        # Test connection
        await client.admin.command('ping')
        logger.info("MongoDB connection successful")
        
        # Initialize Beanie
        await init_beanie(
            database=client.document_ai,
            document_models=[
                ProcessedDocument,
                IncrementalTrainingBatch,
                AutomatedTrainingConfig
            ]
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return False


async def reset_database():
    """Reset database to clean state for testing."""
    processor_id = os.getenv("DOCUMENT_AI_PROCESSOR_ID")
    
    # Delete all documents for this processor
    result = await ProcessedDocument.find({"processor_id": processor_id}).delete()
    logger.info(f"Deleted {result.deleted_count} processed documents")
    
    # Delete all training batches for this processor
    result = await IncrementalTrainingBatch.find({"processor_id": processor_id}).delete()
    logger.info(f"Deleted {result.deleted_count} training batches")
    
    # Reset or create training config
    config = await AutomatedTrainingConfig.find_one({"processor_id": processor_id})
    if config:
        config.min_documents_for_training = 5  # Set to 5 for testing
        config.enabled = True
        await config.save()
        logger.info("Updated training config")
    else:
        config = AutomatedTrainingConfig(
            processor_id=processor_id,
            enabled=True,
            check_interval_minutes=60,
            min_documents_for_training=5,  # 5 for testing
            min_accuracy_for_deployment=0.7,
            document_types=list(DocumentType),
        )
        await config.save()
        logger.info("Created training config")


async def process_initial_documents(pdf_directory: str, bucket_name: str):
    """Process initial documents for training.
    
    This function will:
    1. Upload PDFs to GCS
    2. Process them with Document AI
    3. Store them as PENDING if no trained model exists
    4. Trigger initial training when threshold is reached
    """
    client = EnhancedDocumentAIClient(
        project_id=os.getenv("GCP_PROJECT_ID"),
        processor_id=os.getenv("DOCUMENT_AI_PROCESSOR_ID"),
        gcs_bucket=bucket_name,
        local_mode=False,
        skip_db=False
    )
    
    # Get all PDF files
    pdf_files = list(Path(pdf_directory).glob("*.pdf"))
    
    if not pdf_files:
        logger.error(f"No PDF files found in {pdf_directory}")
        return
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Found {len(pdf_files)} PDF files to process")
    logger.info(f"{'='*60}\n")
    
    # Process files one by one
    for i, pdf_file in enumerate(pdf_files, 1):
        try:
            logger.info(f"[{i}/{len(pdf_files)}] Processing: {pdf_file.name}")
            
            # Upload to GCS
            gcs_uri = upload_to_gcs(str(pdf_file), bucket_name)
            
            # Process the document
            result = await client.upload_and_process_document(
                document_path=gcs_uri,
                document_name=pdf_file.name,
                mime_type="application/pdf"
            )
            
            logger.info(f"  ✓ Status: {result.status}")
            logger.info(f"  ✓ Document Type: {result.document_type}")
            logger.info(f"  ✓ Confidence: {result.confidence_score}")
            
            if result.training_triggered:
                logger.info("  🚀 TRAINING TRIGGERED!")
                
        except Exception as e:
            logger.error(f"  ✗ Error: {str(e)}")
        
        # Add small delay between documents
        await asyncio.sleep(1)


async def monitor_training():
    """Monitor training progress."""
    processor_id = os.getenv("DOCUMENT_AI_PROCESSOR_ID")
    
    logger.info(f"\n{'='*60}")
    logger.info("MONITORING TRAINING PROGRESS")
    logger.info(f"{'='*60}\n")
    
    while True:
        # Check for active training
        active_training = await IncrementalTrainingBatch.find_one({
            "processor_id": processor_id,
            "status": {"$in": [DocumentAIStatus.PENDING, DocumentAIStatus.TRAINING, DocumentAIStatus.DEPLOYING]}
        })
        
        if active_training:
            logger.info(f"Active Training Batch: {active_training.batch_id}")
            logger.info(f"  Status: {active_training.status}")
            logger.info(f"  Documents: {len(active_training.document_ids)}")
            logger.info(f"  Started: {active_training.started_at}")
            
            if active_training.status in [DocumentAIStatus.DEPLOYED, DocumentAIStatus.TRAINED]:
                logger.info(f"  ✓ Training completed!")
                break
        else:
            # Check pending documents
            pending_count = await ProcessedDocument.find({
                "processor_id": processor_id,
                "status": DocumentAIStatus.PENDING
            }).count()
            
            completed_count = await ProcessedDocument.find({
                "processor_id": processor_id,
                "status": DocumentAIStatus.COMPLETED
            }).count()
            
            logger.info(f"Document Status:")
            logger.info(f"  Pending (for initial training): {pending_count}")
            logger.info(f"  Completed (for retraining): {completed_count}")
            
            if pending_count == 0 and completed_count > 0:
                logger.info("\n✓ Initial training completed! Processor now has a trained model.")
                break
        
        # Wait before next check
        await asyncio.sleep(30)


async def test_incremental_training(pdf_directory: str, bucket_name: str):
    """Test incremental training by adding more documents."""
    client = EnhancedDocumentAIClient(
        project_id=os.getenv("GCP_PROJECT_ID"),
        processor_id=os.getenv("DOCUMENT_AI_PROCESSOR_ID"),
        gcs_bucket=bucket_name,
        local_mode=False,
        skip_db=False
    )
    
    logger.info(f"\n{'='*60}")
    logger.info("TESTING INCREMENTAL TRAINING")
    logger.info("Adding 5 more documents to trigger retraining...")
    logger.info(f"{'='*60}\n")
    
    # Get some PDF files (reuse existing ones for testing)
    pdf_files = list(Path(pdf_directory).glob("*.pdf"))[:5]
    
    for i, pdf_file in enumerate(pdf_files, 1):
        try:
            logger.info(f"[{i}/5] Processing: {pdf_file.name}")
            
            # Upload to GCS with new name
            gcs_uri = upload_to_gcs(str(pdf_file), bucket_name)
            
            # Process the document
            result = await client.upload_and_process_document(
                document_path=gcs_uri,
                document_name=f"retrain_{i}_{pdf_file.name}",
                mime_type="application/pdf"
            )
            
            logger.info(f"  ✓ Status: {result.status}")
            logger.info(f"  ✓ Document Type: {result.document_type}")
            logger.info(f"  ✓ Confidence: {result.confidence_score}")
            
            if result.training_triggered:
                logger.info("  🚀 RETRAINING TRIGGERED!")
                
        except Exception as e:
            logger.error(f"  ✗ Error: {str(e)}")
        
        await asyncio.sleep(1)


async def show_final_status():
    """Show final status of the system."""
    processor_id = os.getenv("DOCUMENT_AI_PROCESSOR_ID")
    
    logger.info(f"\n{'='*60}")
    logger.info("FINAL STATUS")
    logger.info(f"{'='*60}\n")
    
    # Document statistics
    total_docs = await ProcessedDocument.find({"processor_id": processor_id}).count()
    pending_docs = await ProcessedDocument.find({
        "processor_id": processor_id,
        "status": DocumentAIStatus.PENDING
    }).count()
    completed_docs = await ProcessedDocument.find({
        "processor_id": processor_id,
        "status": DocumentAIStatus.COMPLETED
    }).count()
    
    logger.info(f"Document Statistics:")
    logger.info(f"  Total documents: {total_docs}")
    logger.info(f"  Pending: {pending_docs}")
    logger.info(f"  Completed: {completed_docs}")
    
    # Training statistics
    total_trainings = await IncrementalTrainingBatch.find({"processor_id": processor_id}).count()
    deployed_trainings = await IncrementalTrainingBatch.find({
        "processor_id": processor_id,
        "status": DocumentAIStatus.DEPLOYED
    }).count()
    
    logger.info(f"\nTraining Statistics:")
    logger.info(f"  Total training batches: {total_trainings}")
    logger.info(f"  Deployed models: {deployed_trainings}")
    
    # Latest training
    latest_training = await IncrementalTrainingBatch.find({
        "processor_id": processor_id
    }).sort([("started_at", -1)]).first_or_none()
    
    if latest_training:
        logger.info(f"\nLatest Training:")
        logger.info(f"  Batch ID: {latest_training.batch_id}")
        logger.info(f"  Status: {latest_training.status}")
        logger.info(f"  Documents: {len(latest_training.document_ids)}")
        logger.info(f"  Accuracy: {latest_training.accuracy_score}")


async def main():
    """Main test function."""
    # Check environment variables
    required_env_vars = ["GCP_PROJECT_ID", "DOCUMENT_AI_PROCESSOR_ID", "GOOGLE_APPLICATION_CREDENTIALS"]
    for var in required_env_vars:
        if not os.getenv(var):
            logger.error(f"Missing required environment variable: {var}")
            return
    
    # Settings
    pdf_dir = os.getenv("PDF_DIRECTORY", "test_documents")
    bucket_name = os.getenv("GCS_BUCKET_NAME", "document-ai-test-veronica")
    
    # Verify PDF directory exists
    if not os.path.exists(pdf_dir):
        logger.error(f"PDF directory not found: {pdf_dir}")
        return
    
    # Initialize database
    if not await init_db():
        logger.error("Failed to initialize database")
        return
    
    try:
        # Reset database for clean test
        logger.info("Resetting database for clean test...")
        await reset_database()
        
        # Phase 1: Process initial documents for training
        await process_initial_documents(pdf_dir, bucket_name)
        
        # Phase 2: Monitor initial training
        await monitor_training()
        
        # Phase 3: Test incremental training
        # Uncomment the following line to test incremental training
        # await test_incremental_training(pdf_dir, bucket_name)
        
        # Show final status
        await show_final_status()
        
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())