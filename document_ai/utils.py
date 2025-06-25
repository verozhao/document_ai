#!/usr/bin/env python3
"""
Document AI Utilities - Consolidated common functions
Eliminates repeated code across pipeline scripts
"""

import json
import requests
import time
from google.auth import default
from google.auth.transport.requests import Request
from google.cloud import storage

# Configuration
PROJECT_ID = "tetrix-462721"
OCR_PROCESSOR_ID = "2369784b09e9d56a"
CLASSIFIER_PROCESSOR_ID = "ddc065df69bfa3b5"
LOCATION = "us"
BUCKET_NAME = "document-ai-test-veronica"

def get_access_token():
    """Get Google Cloud access token - single implementation"""
    credentials, _ = default()
    credentials.refresh(Request())
    return credentials.token

def process_document_with_ocr(file_path):
    """Process document with OCR processor - unified implementation"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{OCR_PROCESSOR_ID}:process"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Handle both blob names and GCS URIs
    if file_path.startswith("gs://"):
        gcs_uri = file_path
    else:
        gcs_uri = f"gs://{BUCKET_NAME}/{file_path}"
    
    data = {
        "gcsDocument": {
            "gcsUri": gcs_uri,
            "mimeType": "application/pdf"
        },
        "imagelessMode": True
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error processing document {file_path}: {response.text}")
        return None

def create_labeled_document(processed_doc, document_type, original_uri):
    """Create labeled document - unified implementation"""
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

def upload_json_to_gcs(json_data, gcs_path):
    """Upload JSON to GCS - unified implementation"""
    try:
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(json.dumps(json_data), content_type="application/json")
        return True
    except Exception as e:
        print(f"Error uploading JSON to {gcs_path}: {e}")
        return False

def import_documents_to_processor(folder_prefix="final_labeled_documents/"):
    """Import documents to processor - unified implementation"""
    access_token = get_access_token()
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
                    "gcsUriPrefix": f"gs://{BUCKET_NAME}/{folder_prefix}"
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
        print(f"Error importing documents: {response.text}")
        return None

def start_training(display_name=None):
    """Start training - unified implementation"""
    if not display_name:
        display_name = f"unified-training-{int(time.time())}"
    
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{CLASSIFIER_PROCESSOR_ID}/processorVersions:train"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID
    }
    
    data = {
        "processorVersion": {
            "displayName": display_name
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error starting training: {response.text}")
        return None

def monitor_operation(operation_name, operation_type="operation", max_checks=30):
    """Monitor operation - unified implementation"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1beta3/{operation_name}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Goog-User-Project": PROJECT_ID
    }
    
    print(f"🔄 Monitoring {operation_type}...")
    
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
                        print(f"✅ {operation_type.title()} completed successfully!")
                        return True
                else:
                    metadata = operation.get("metadata", {})
                    common_metadata = metadata.get("commonMetadata", {})
                    state = common_metadata.get("state", "RUNNING")
                    print(f"📊 {operation_type.title()} state: {state} (check {check+1}/{max_checks})")
                    time.sleep(30)
            else:
                print(f"Error checking {operation_type}: {response.status_code}")
                time.sleep(30)
        except Exception as e:
            print(f"Exception monitoring {operation_type}: {e}")
            time.sleep(30)
    
    print(f"⏰ {operation_type.title()} monitoring timed out")
    return False