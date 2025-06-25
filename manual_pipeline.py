#!/usr/bin/env python3
"""
EXACT WORKING PIPELINE - Based on our previous successful session
Processes documents from GCS documents/ folder and actually imports/trains
"""

import json
import requests
import time
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import storage

# Configuration - EXACT same as working session
PROJECT_ID = "tetrix-462721"
OCR_PROCESSOR_ID = "2369784b09e9d56a"  # OCR processor for text extraction
CLASSIFIER_PROCESSOR_ID = "ddc065df69bfa3b5"  # Classifier processor for import and training
LOCATION = "us"
BUCKET_NAME = "document-ai-test-veronica"

def get_access_token():
    """Get Google Cloud access token"""
    credentials, _ = default()
    credentials.refresh(Request())
    return credentials.token

def process_document_with_ai(file_path):
    """Process a document with OCR processor - EXACT working version"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{OCR_PROCESSOR_ID}:process"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    data = {
        "gcsDocument": {
            "gcsUri": f"gs://{BUCKET_NAME}/{file_path}",
            "mimeType": "application/pdf"
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error processing document {file_path}: {response.text}")
        return None

def create_labeled_document(processed_doc, document_type, original_uri):
    """Create a labeled document with proper entities - EXACT working version"""
    if not processed_doc or "document" not in processed_doc:
        return None
    
    doc = processed_doc["document"]
    
    # Create the labeled document structure - EXACT format that worked
    labeled_doc = {
        "mimeType": "application/pdf",
        "text": doc.get("text", ""),
        "pages": doc.get("pages", []),
        "uri": original_uri,
        "entities": [
            {
                "type": document_type,
                "mentionText": document_type,
                "confidence": 1.0,
                "textAnchor": {
                    "textSegments": [
                        {
                            "startIndex": 0,
                            "endIndex": len(document_type)
                        }
                    ]
                }
            }
        ]
    }
    
    return labeled_doc

def upload_labeled_document(labeled_doc, output_path):
    """Upload labeled document to GCS - EXACT working version"""
    access_token = get_access_token()
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKET_NAME}/o"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    params = {
        "uploadType": "media",
        "name": output_path
    }
    
    response = requests.post(
        url,
        headers=headers,
        params=params,
        data=json.dumps(labeled_doc)
    )
    
    if response.status_code == 200:
        return True
    else:
        print(f"Error uploading {output_path}: {response.text}")
        return False

def import_documents_to_processor():
    """Import labeled documents to classifier processor - EXACT working version"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1beta3/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{CLASSIFIER_PROCESSOR_ID}/dataset:importDocuments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID
    }
    
    # Use EXACT same folder structure that worked before
    data = {
        "batchDocumentsImportConfigs": [
            {
                "batchInputConfig": {
                    "gcsPrefix": {
                        "gcsUriPrefix": f"gs://{BUCKET_NAME}/working_labeled_documents/"
                    }
                },
                "autoSplitConfig": {
                    "trainingSplitRatio": 0.8
                }
            }
        ]
    }
    
    print(f"🔄 Calling import API with data: {json.dumps(data, indent=2)}")
    response = requests.post(url, headers=headers, json=data)
    
    print(f"📊 Import response status: {response.status_code}")
    print(f"📊 Import response: {response.text}")
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Error importing documents: {response.text}")
        return None

def start_training():
    """Start training the classifier processor - EXACT working version"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{CLASSIFIER_PROCESSOR_ID}/processorVersions:train"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID
    }
    
    data = {
        "processorVersion": {
            "displayName": f"working-training-{int(time.time())}"
        }
    }
    
    print(f"🎯 Calling training API with data: {json.dumps(data, indent=2)}")
    response = requests.post(url, headers=headers, json=data)
    
    print(f"📊 Training response status: {response.status_code}")
    print(f"📊 Training response: {response.text}")
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Error starting training: {response.text}")
        return None

def list_files_in_folder(folder_path):
    """List files in a GCS folder"""
    access_token = get_access_token()
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET_NAME}/o"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"prefix": folder_path}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        items = response.json().get("items", [])
        return [item for item in items if item["name"].endswith(".pdf")]
    else:
        print(f"Error listing files: {response.text}")
        return []

def main():
    """Main pipeline - processes documents/ folder and creates working import"""
    print("🚀 WORKING PIPELINE - Processing documents from documents/ folder")
    print("=" * 60)
    
    # Find document types from documents/ folder structure
    access_token = get_access_token()
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET_NAME}/o"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"prefix": "documents/", "delimiter": "/"}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"❌ Failed to list document folders: {response.text}")
        return False
    
    prefixes = response.json().get("prefixes", [])
    doc_types = [prefix.replace("documents/", "").replace("/", "") for prefix in prefixes]
    doc_types = [folder for folder in doc_types if folder]  # Remove empty strings
    
    print(f"📁 Found document types: {doc_types}")
    
    if not doc_types:
        print("❌ No document types found in documents/ folder")
        return False
    
    total_processed = 0
    
    for doc_type in doc_types:
        print(f"\n📁 Processing {doc_type} documents...")
        folder_path = f"documents/{doc_type}/"
        files = list_files_in_folder(folder_path)
        
        print(f"Found {len(files)} PDF files in {doc_type}")
        
        for file_item in files:
            file_path = file_item["name"]
            file_name = file_path.split("/")[-1]
            print(f"  Processing: {file_name}")
            
            # Process with Document AI
            processed = process_document_with_ai(file_path)
            if processed:
                # Create labeled document
                original_uri = f"gs://{BUCKET_NAME}/{file_path}"
                labeled_doc = create_labeled_document(processed, doc_type, original_uri)
                
                if labeled_doc:
                    # Upload labeled document to working folder
                    output_name = file_name.replace(".pdf", ".json")
                    output_path = f"working_labeled_documents/{doc_type}/{output_name}"
                    
                    if upload_labeled_document(labeled_doc, output_path):
                        print(f"    ✅ Uploaded: {output_path}")
                        total_processed += 1
                    else:
                        print(f"    ❌ Failed to upload: {output_path}")
                else:
                    print(f"    ❌ Failed to create labeled document")
            else:
                print(f"    ❌ Failed to process: {file_name}")
    
    print(f"\n📊 Total documents processed and labeled: {total_processed}")
    
    if total_processed > 0:
        print("\n🔄 Starting import to Document AI processor...")
        import_result = import_documents_to_processor()
        
        if import_result and "name" in import_result:
            operation_name = import_result["name"]
            print(f"✅ Import operation started: {operation_name}")
            
            # Wait a moment for import to initialize
            print("⏳ Waiting for import to initialize...")
            time.sleep(10)
            
            print("\n🎯 Starting training...")
            training_result = start_training()
            
            if training_result and "name" in training_result:
                training_operation = training_result["name"]
                print(f"✅ Training operation started: {training_operation}")
                
                print(f"\n🎉 SUCCESS! Check your Document AI processor in the console:")
                print(f"https://console.cloud.google.com/ai/document-ai/processors/details/{CLASSIFIER_PROCESSOR_ID}?project={PROJECT_ID}")
                print(f"\nLabeled documents location: gs://{BUCKET_NAME}/working_labeled_documents/")
                print(f"Total documents with labels: {total_processed}")
                print(f"Import operation: {operation_name}")
                print(f"Training operation: {training_operation}")
                
                return True
            else:
                print("❌ Failed to start training")
                return False
        else:
            print("❌ Failed to start import operation")
            return False
    else:
        print("❌ No documents were processed successfully")
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🏆 MISSION ACCOMPLISHED: Working pipeline executed successfully!")
    else:
        print("\n❌ Mission failed - check the errors above")