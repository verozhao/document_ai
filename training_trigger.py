import json
import functions_framework
import logging
from google.cloud import documentai
from google.api_core.client_options import ClientOptions
from flask import Request

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
project_id = "tetrix-462721"
location = "us"
processor_id = "ddc065df69bfa3b5"

@functions_framework.http
def check_training_trigger(request: Request):
    """HTTP Cloud Function triggered by Pub/Sub message to check if training should be triggered."""
    if request.method != 'POST':
        return ('Method not allowed', 405)
    
    try:
        data = request.get_json()
        if not data:
            return ('No data provided', 400)
        
        logger.info(f"Received training check request: {data}")
        
        # Initialize Document AI client
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        client = documentai.DocumentProcessorServiceClient(client_options=opts)
        
        # Get processor path
        processor_path = client.processor_path(project_id, location, processor_id)
        logger.info(f"Processor path: {processor_path}")
        
        # Get processor details
        processor = client.get_processor(name=processor_path)
        logger.info(f"Processor details: {processor}")
        
        # Check if training should be triggered
        if processor.process_options.auto_training:
            training_stats = processor.training_stats
            logger.info(f"Training stats: {training_stats}")
            
            # Check if we have enough documents and if confidence is below threshold
            if (training_stats.document_count >= processor.process_options.auto_training_min_document_count and
                training_stats.average_confidence < processor.process_options.auto_training_confidence_threshold):
                
                logger.info("Training conditions met, triggering training...")
                
                # Trigger training
                request = documentai.TrainProcessorVersionRequest(
                    parent=processor_path,
                    processor_version=documentai.ProcessorVersion(
                        display_name=f"Auto-trained version {training_stats.document_count}",
                        state="TRAINING"
                    )
                )
                
                operation = client.train_processor_version(request)
                logger.info(f"Training triggered for processor {processor_id}")
                logger.info(f"Operation: {operation.operation.name}")
                
                # Wait for training to complete
                result = operation.result()
                logger.info(f"Training completed: {result}")
                return (f'Training completed: {result}', 200)
            else:
                message = {
                    "status": "Training not triggered - conditions not met",
                    "document_count": training_stats.document_count,
                    "average_confidence": training_stats.average_confidence,
                    "required_document_count": processor.process_options.auto_training_min_document_count,
                    "confidence_threshold": processor.process_options.auto_training_confidence_threshold
                }
                logger.info(f"Training not triggered: {message}")
                return (json.dumps(message), 200)
        else:
            logger.warning("Automatic training is not enabled for this processor")
            return ('Automatic training is not enabled for this processor', 400)
            
    except Exception as e:
        logger.error(f"Error checking training trigger: {str(e)}")
        return (f'Error checking training trigger: {str(e)}', 500) 