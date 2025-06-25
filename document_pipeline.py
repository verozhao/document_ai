#!/usr/bin/env python3
"""
Document AI Complete Pipeline
Organized end-to-end pipeline: Setup → Initial Training → Subsequent Retraining

Based on analysis of working operations, this combines the proven approaches
that actually generated successful Google Cloud operations.
"""

import json
import requests
import time
import argparse
from pathlib import Path
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import storage

# Configuration with your exact credentials
PROJECT_ID = "tetrix-462721"
OCR_PROCESSOR_ID = "2369784b09e9d56a"      # For text extraction
CLASSIFIER_PROCESSOR_ID = "ddc065df69bfa3b5"  # For training
LOCATION = "us"
BUCKET_NAME = "document-ai-test-veronica"

class DocumentAIPipeline:
    """Complete Document AI Pipeline - Setup to Retraining"""
    
    def __init__(self):
        print("🚀 Document AI Complete Pipeline")
        print("=" * 50)
        print(f"Project: {PROJECT_ID}")
        print(f"OCR Processor: {OCR_PROCESSOR_ID}")
        print(f"Classifier Processor: {CLASSIFIER_PROCESSOR_ID}")
        print(f"Bucket: {BUCKET_NAME}")
        print()

    def get_access_token(self):
        """Get Google Cloud access token"""
        credentials, _ = default()
        credentials.refresh(Request())
        return credentials.token

    # ============================================================================
    # PHASE 1: SETUP AND DOCUMENT PROCESSING
    # ============================================================================

    def upload_documents_to_gcs(self, local_folder):
        """Upload documents from local folder to GCS with proper organization"""
        print("📤 PHASE 1: Uploading documents to GCS...")
        
        local_path = Path(local_folder)
        if not local_path.exists():
            print(f"❌ Local folder does not exist: {local_folder}")
            return False
        
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)
        uploaded_count = 0
        
        for subfolder in local_path.iterdir():
            if subfolder.is_dir():
                doc_type = subfolder.name
                print(f"  📁 Processing {doc_type} folder...")
                
                for pdf_file in subfolder.glob("*.pdf"):
                    gcs_path = f"documents/{doc_type}/{pdf_file.name}"
                    blob = bucket.blob(gcs_path)
                    blob.upload_from_filename(str(pdf_file))
                    print(f"    ✅ Uploaded: {pdf_file.name}")
                    uploaded_count += 1
        
        print(f"📊 Total documents uploaded: {uploaded_count}")
        return uploaded_count > 0

    def process_and_label_documents(self):
        """Process documents with OCR and create labeled JSON files"""
        print("\n🔄 PHASE 2: Processing and labeling documents...")
        
        # Get document types from GCS structure
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)
        
        doc_types = set()
        for blob in bucket.list_blobs(prefix="documents/"):
            if blob.name.endswith(".pdf"):
                parts = blob.name.split("/")
                if len(parts) >= 2:
                    doc_types.add(parts[1])
        
        print(f"📁 Found document types: {list(doc_types)}")
        total_processed = 0
        
        for doc_type in doc_types:
            print(f"\n  📁 Processing {doc_type} documents...")
            pdfs = list(bucket.list_blobs(prefix=f"documents/{doc_type}/"))
            pdfs = [blob for blob in pdfs if blob.name.endswith(".pdf")]
            
            for blob in pdfs:
                file_name = blob.name.split("/")[-1]
                print(f"    Processing: {file_name}")
                
                # Process with OCR
                processed_doc = self._process_with_ocr(blob.name)
                if processed_doc:
                    # Create labeled document
                    labeled_doc = self._create_labeled_document(
                        processed_doc, doc_type, f"gs://{BUCKET_NAME}/{blob.name}"
                    )
                    
                    # Upload labeled document
                    output_name = file_name.replace(".pdf", ".json")
                    output_path = f"final_labeled_documents/{doc_type}/{output_name}"
                    
                    if self._upload_json_to_gcs(labeled_doc, output_path):
                        print(f"      ✅ Labeled: {output_name}")
                        total_processed += 1
                    else:
                        print(f"      ❌ Failed to upload labeled document")
                else:
                    print(f"      ❌ Failed to process with OCR")
        
        print(f"\n📊 Total documents processed and labeled: {total_processed}")
        return total_processed > 0

    def _process_with_ocr(self, gcs_path):
        """Process document with OCR processor"""
        access_token = self.get_access_token()
        url = f"https://us-documentai.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{OCR_PROCESSOR_ID}:process"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        data = {
            "gcsDocument": {
                "gcsUri": f"gs://{BUCKET_NAME}/{gcs_path}",
                "mimeType": "application/pdf"
            }
        }
        
        response = requests.post(url, headers=headers, json=data)
        return response.json() if response.status_code == 200 else None

    def _create_labeled_document(self, processed_doc, document_type, original_uri):
        """Create labeled document with proper entities - EXACT working format"""
        if not processed_doc or "document" not in processed_doc:
            return None
        
        doc = processed_doc["document"]
        
        return {
            "mimeType": "application/pdf",
            "text": doc.get("text", ""),
            "pages": doc.get("pages", []),
            "uri": original_uri,
            "entities": [{
                "type": document_type,
                "mentionText": document_type,
                "confidence": 1.0,
                "textAnchor": {
                    "textSegments": [{
                        "startIndex": 0,
                        "endIndex": len(document_type)
                    }]
                }
            }]
        }

    def _upload_json_to_gcs(self, json_data, gcs_path):
        """Upload JSON data to GCS"""
        try:
            client = storage.Client(project=PROJECT_ID)
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob(gcs_path)
            blob.upload_from_string(json.dumps(json_data), content_type="application/json")
            return True
        except Exception as e:
            print(f"Error uploading JSON: {e}")
            return False

    # ============================================================================
    # PHASE 2: INITIAL TRAINING
    # ============================================================================

    def import_and_train(self, monitor_completion=True):
        """Import labeled documents and start training - EXACT working version"""
        print("\n📥 PHASE 3: Importing labeled documents...")
        
        # Import using the EXACT working method
        import_result = self._import_working_documents()
        if not import_result or "name" not in import_result:
            print("❌ Import failed")
            return False
        
        import_operation = import_result["name"]
        print(f"✅ Import operation started: {import_operation}")
        
        if monitor_completion:
            print("⏳ Monitoring import completion...")
            if not self._monitor_operation(import_operation, "import"):
                print("❌ Import failed to complete")
                return False
            print("✅ Import completed successfully!")
        
        # Start training
        print("\n🎯 PHASE 4: Starting training...")
        training_result = self._start_training()
        if not training_result or "name" not in training_result:
            print("❌ Training failed to start")
            return False
        
        training_operation = training_result["name"]
        print(f"✅ Training operation started: {training_operation}")
        
        print(f"\n🎉 PIPELINE COMPLETED SUCCESSFULLY!")
        print(f"📥 Import operation: {import_operation}")
        print(f"🎯 Training operation: {training_operation}")
        print(f"🔗 Monitor training: https://console.cloud.google.com/ai/document-ai/processors/details/{CLASSIFIER_PROCESSOR_ID}?project={PROJECT_ID}")
        print(f"⏰ Training will complete in 30-60 minutes")
        
        return True

    def _import_working_documents(self):
        """Import documents using the EXACT working method"""
        access_token = self.get_access_token()
        url = f"https://us-documentai.googleapis.com/v1beta3/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{CLASSIFIER_PROCESSOR_ID}/dataset:importDocuments"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": PROJECT_ID
        }
        
        data = {
            "batchDocumentsImportConfigs": [{
                "batchInputConfig": {
                    "gcsPrefix": {
                        "gcsUriPrefix": f"gs://{BUCKET_NAME}/final_labeled_documents/"
                    }
                },
                "autoSplitConfig": {
                    "trainingSplitRatio": 0.8
                }
            }]
        }
        
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Import error: {response.text}")
            return None

    def _start_training(self):
        """Start training using the EXACT working method"""
        access_token = self.get_access_token()
        url = f"https://us-documentai.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{CLASSIFIER_PROCESSOR_ID}/processorVersions:train"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": PROJECT_ID
        }
        
        data = {
            "processorVersion": {
                "displayName": f"pipeline-training-{int(time.time())}"
            }
        }
        
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Training error: {response.text}")
            return None

    def _monitor_operation(self, operation_name, operation_type="operation"):
        """Monitor operation until completion"""
        access_token = self.get_access_token()
        url = f"https://us-documentai.googleapis.com/v1beta3/{operation_name}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Goog-User-Project": PROJECT_ID
        }
        
        max_checks = 20 if operation_type == "import" else 60
        for check in range(max_checks):
            try:
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    operation = response.json()
                    
                    if operation.get("done", False):
                        if "error" in operation:
                            print(f"❌ {operation_type.title()} failed: {operation['error']}")
                            return False
                        else:
                            return True
                    else:
                        print(f"📊 {operation_type.title()} in progress... (check {check+1}/{max_checks})")
                        time.sleep(30)
                else:
                    print(f"Error checking {operation_type}: {response.status_code}")
                    time.sleep(30)
            except Exception as e:
                print(f"Exception monitoring {operation_type}: {e}")
                time.sleep(30)
        
        print(f"⏰ {operation_type.title()} monitoring timed out")
        return False

    # ============================================================================
    # PHASE 3: SUBSEQUENT RETRAINING
    # ============================================================================

    def retrain_with_new_documents(self, local_folder=None):
        """Add new documents and retrain the processor"""
        print("\n🔄 RETRAINING: Adding new documents and retraining...")
        
        if local_folder:
            # Upload new documents
            if not self.upload_documents_to_gcs(local_folder):
                print("❌ No new documents uploaded")
                return False
            
            # Process new documents
            if not self.process_and_label_documents():
                print("❌ No new documents processed")
                return False
        
        # Import all documents (existing + new) and retrain
        return self.import_and_train(monitor_completion=True)

    # ============================================================================
    # MAIN PIPELINE ORCHESTRATION
    # ============================================================================

    def run_complete_pipeline(self, local_folder, retrain_mode=False):
        """Run the complete pipeline from setup to training"""
        try:
            if retrain_mode:
                return self.retrain_with_new_documents(local_folder)
            else:
                # Initial training pipeline
                if not self.upload_documents_to_gcs(local_folder):
                    return False
                
                if not self.process_and_label_documents():
                    return False
                
                return self.import_and_train(monitor_completion=True)
        
        except Exception as e:
            print(f"❌ Pipeline failed: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(description="Document AI Complete Pipeline")
    parser.add_argument("--local-folder", required=True, 
                       help="Local folder with documents organized in subfolders")
    parser.add_argument("--retrain", action="store_true",
                       help="Retraining mode - add new documents to existing training")
    
    args = parser.parse_args()
    
    # Validate local folder
    local_path = Path(args.local_folder)
    if not local_path.exists():
        print(f"❌ Local folder does not exist: {args.local_folder}")
        return False
    
    # Run pipeline
    pipeline = DocumentAIPipeline()
    success = pipeline.run_complete_pipeline(args.local_folder, args.retrain)
    
    if success:
        print("\n🏆 SUCCESS: Pipeline executed successfully!")
        print("🔗 Check processor: https://console.cloud.google.com/ai/document-ai/processors/details/ddc065df69bfa3b5?project=tetrix-462721")
    else:
        print("\n❌ FAILED: Pipeline execution failed.")
    
    return success

if __name__ == "__main__":
    main()