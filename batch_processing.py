import re
from typing import Optional
import json
import functions_framework
import logging
import mimetypes
from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import InternalServerError
from google.api_core.exceptions import RetryError
from google.cloud import documentai  # type: ignore
from google.cloud import storage
from google.cloud import pubsub_v1
from flask import Request

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# TODO(developer): Uncomment these variables before running the sample.
project_id = "tetrix-462721"
location = "us" # Format is "us" or "eu"
processor_id = "ddc065df69bfa3b5" # Create processor before running sample
gcs_output_uri = "gs://document-ai-test-veronica/output/" # Updated bucket
# processor_version_id = "YOUR_PROCESSOR_VERSION_ID" # Optional. Example: pretrained-ocr-v1.0-2020-09-23

# TODO(developer): You must specify either `gcs_input_uri` and `mime_type` or `gcs_input_prefix`
gcs_input_prefix = "gs://document-ai-test-veronica/documents/" # Updated bucket
# field_mask = "text,entities,pages.pageNumber"  # Optional. The fields to return in the Document object.

# Configuration
topic_name = "document-ai-training-trigger"

# Initialize clients
storage_client = storage.Client()
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(project_id, topic_name)

# Supported MIME types for Document AI
SUPPORTED_MIME_TYPES = {
    'application/pdf': 'PDF',
    'image/tiff': 'TIFF',
    'image/gif': 'GIF',
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
    'image/bmp': 'BMP',
    'image/webp': 'WEBP',
    'text/plain': 'TXT',
    'text/html': 'HTML',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'XLSX',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPTX'
}

def get_mime_type(file_name: str) -> str:
    """Get the MIME type for a file based on its extension."""
    mime_type, _ = mimetypes.guess_type(file_name)
    if mime_type and mime_type in SUPPORTED_MIME_TYPES:
        logger.info(f"Detected MIME type {mime_type} for file {file_name}")
        return mime_type
    else:
        logger.warning(f"Unsupported or unknown MIME type for {file_name}, defaulting to PDF")
        return "application/pdf"

def enable_processor_training():
    """Enable automatic training for the processor."""
    try:
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        client = documentai.DocumentProcessorServiceClient(client_options=opts)
        
        processor_path = client.processor_path(project_id, location, processor_id)
        logger.info(f"Processor path: {processor_path}")
        
        # Configure processor for automatic training
        processor = documentai.Processor(
            name=processor_path,
            display_name="Auto-training Processor",
            type_="CUSTOM_CLASSIFIER",
            state="ENABLED",
            process_options=documentai.ProcessOptions(
                ocr_config=documentai.OcrConfig(
                    enable_native_pdf_parsing=True,
                    enable_image_quality_scores=True,
                ),
                auto_training=True,  # Enable automatic training
                auto_training_min_document_count=1,  # Minimum documents before training
                auto_training_confidence_threshold=0,  # Confidence threshold for training
            )
        )
        
        request = documentai.UpdateProcessorRequest(
            processor=processor,
            update_mask={"paths": ["process_options"]}
        )
        
        response = client.update_processor(request)
        logger.info(f"Processor updated successfully: {response}")
        return response
    except Exception as e:
        logger.error(f"Error enabling processor training: {str(e)}")
        raise

@functions_framework.http
def process_new_document(request: Request):
    """HTTP Cloud Function triggered by new document upload."""
    if request.method != 'POST':
        return ('Method not allowed', 405)
    
    try:
        data = request.get_json()
        if not data:
            return ('No data provided', 400)
            
        bucket_name = data.get('bucket')
        file_name = data.get('name')
        
        if not bucket_name or not file_name:
            return ('Missing bucket or file name', 400)
        
        logger.info(f"Processing document: gs://{bucket_name}/{file_name}")
        
        # Get the appropriate MIME type for the file
        input_mime_type = get_mime_type(file_name)
        logger.info(f"Using MIME type: {input_mime_type}")

        logger.info("Calling batch_process_documents now...")
        
        # Process the new document
        gcs_input_uri = f"gs://{bucket_name}/{file_name}"
        batch_process_documents(
            project_id=project_id,
            location=location,
            processor_id=processor_id,
            gcs_output_uri=gcs_output_uri,
            gcs_input_uri=gcs_input_uri,
            input_mime_type=input_mime_type
        )
        
        # Publish message to trigger training check
        message_data = {
            "bucket": bucket_name,
            "file": file_name,
            "processor_id": processor_id,
            "action": "check_training",
            "mime_type": input_mime_type
        }
        logger.info(f"Publishing message to {topic_path}: {message_data}")
        publisher.publish(
            topic_path,
            json.dumps(message_data).encode("utf-8")
        )
        
        return ('Document processed successfully', 200)
        
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        return (f'Error processing document: {str(e)}', 500)

def batch_process_documents(
    project_id: str,
    location: str,
    processor_id: str,
    gcs_output_uri: str,
    processor_version_id: Optional[str] = None,
    gcs_input_uri: Optional[str] = None,
    input_mime_type: Optional[str] = None,
    gcs_input_prefix: Optional[str] = None,
    field_mask: Optional[str] = None,
    timeout: int = 400,
) -> None:
    try:
        # You must set the `api_endpoint` if you use a location other than "us".
        opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        client = documentai.DocumentProcessorServiceClient(client_options=opts)

        if gcs_input_uri:
            # Specify specific GCS URIs to process individual documents
            gcs_document = documentai.GcsDocument(
                gcs_uri=gcs_input_uri, mime_type=input_mime_type
            )
            # Load GCS Input URI into a List of document files
            gcs_documents = documentai.GcsDocuments(documents=[gcs_document])
            input_config = documentai.BatchDocumentsInputConfig(gcs_documents=gcs_documents)
        else:
            # Specify a GCS URI Prefix to process an entire directory
            gcs_prefix = documentai.GcsPrefix(gcs_uri_prefix=gcs_input_prefix)
            input_config = documentai.BatchDocumentsInputConfig(gcs_prefix=gcs_prefix)

        # Cloud Storage URI for the Output Directory
        gcs_output_config = documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=gcs_output_uri, field_mask=field_mask
        )

        # Where to write results
        output_config = documentai.DocumentOutputConfig(gcs_output_config=gcs_output_config)

        if processor_version_id:
            # The full resource name of the processor version
            name = client.processor_version_path(
                project_id, location, processor_id, processor_version_id
            )
        else:
            # The full resource name of the processor
            name = client.processor_path(project_id, location, processor_id)

        logger.info(f"Processing document with processor: {name}")

        request = documentai.BatchProcessRequest(
            name=name,
            input_documents=input_config,
            document_output_config=output_config,
        )

        # BatchProcess returns a Long Running Operation (LRO)
        operation = client.batch_process_documents(request)
        logger.info(f"Started batch processing operation: {operation.operation.name}")

        # Continually polls the operation until it is complete.
        try:
            print(f"Waiting for operation {operation.operation.name} to complete...")
            operation.result(timeout=timeout)
            logger.info("Batch processing completed successfully")
        except (RetryError, InternalServerError) as e:
            logger.error(f"Error during batch processing: {str(e)}")
            raise

        # After the operation is complete,
        # get output document information from operation metadata
        metadata = documentai.BatchProcessMetadata(operation.metadata)
        logger.info(f"Processing metadata: {metadata}")

        if metadata.state != documentai.BatchProcessMetadata.State.SUCCEEDED:
            raise ValueError(f"Batch Process Failed: {metadata.state_message}")

        # Process the results
        storage_client = storage.Client()
        logger.info("Processing output files...")
        
        # One process per Input Document
        for process in list(metadata.individual_process_statuses):
            # output_gcs_destination format: gs://BUCKET/PREFIX/OPERATION_NUMBER/INPUT_FILE_NUMBER/
            matches = re.match(r"gs://(.*?)/(.*)", process.output_gcs_destination)
            if not matches:
                logger.error(f"Could not parse output GCS destination: {process.output_gcs_destination}")
                continue

            output_bucket, output_prefix = matches.groups()
            logger.info(f"Processing output from bucket: {output_bucket}, prefix: {output_prefix}")

            # Get List of Document Objects from the Output Bucket
            output_blobs = storage_client.list_blobs(output_bucket, prefix=output_prefix)

            # Document AI may output multiple JSON files per source file
            for blob in output_blobs:
                if blob.content_type != "application/json":
                    logger.warning(f"Skipping non-supported file: {blob.name} - Mimetype: {blob.content_type}")
                    continue

                # Download JSON File as bytes object and convert to Document Object
                logger.info(f"Processing output file: {blob.name}")
                document = documentai.Document.from_json(
                    blob.download_as_bytes(), ignore_unknown_fields=True
                )

                # Log the document text and any classification results
                logger.info("Document processing results:")
                logger.info(f"Text: {document.text}")
                if hasattr(document, 'entities'):
                    logger.info(f"Entities: {document.entities}")
                if hasattr(document, 'pages'):
                    logger.info(f"Number of pages: {len(document.pages)}")

    except Exception as e:
        logger.error(f"Error in batch_process_documents: {str(e)}")
        raise

if __name__ == "__main__":
    # Enable automatic training when script is run
    enable_processor_training()
    logger.info("Automatic training has been enabled for the processor.")
