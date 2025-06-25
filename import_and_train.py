#!/usr/bin/env python3
"""
Import the documents that we know worked and train
"""

import json
import requests
import time
from google.auth import default
from google.auth.transport.requests import Request

# Configuration
PROJECT_ID = "tetrix-462721"
CLASSIFIER_PROCESSOR_ID = "ddc065df69bfa3b5"
LOCATION = "us"
BUCKET_NAME = "document-ai-test-veronica"

def get_access_token():
    credentials, _ = default()
    credentials.refresh(Request())
    return credentials.token

def import_working_documents():
    """Import the documents we know worked from final_labeled_documents"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1beta3/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{CLASSIFIER_PROCESSOR_ID}/dataset:importDocuments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID
    }
    
    data = {
        "batchDocumentsImportConfigs": [
            {
                "batchInputConfig": {
                    "gcsPrefix": {
                        "gcsUriPrefix": f"gs://{BUCKET_NAME}/final_labeled_documents/"
                    }
                },
                "autoSplitConfig": {
                    "trainingSplitRatio": 0.8
                }
            }
        ]
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error importing documents: {response.text}")
        return None

def start_training():
    """Start training the processor"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/processors/{CLASSIFIER_PROCESSOR_ID}/processorVersions:train"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID
    }
    
    data = {
        "processorVersion": {
            "displayName": "working-auto-labeled-training"
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error starting training: {response.text}")
        return None

def monitor_operation(operation_name, operation_type="import"):
    """Monitor an operation until completion"""
    access_token = get_access_token()
    url = f"https://us-documentai.googleapis.com/v1beta3/{operation_name}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Goog-User-Project": PROJECT_ID
    }
    
    print(f"🔄 Monitoring {operation_type} operation...")
    max_checks = 20 if operation_type == "import" else 60  # Training takes longer
    
    for check in range(max_checks):
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                operation = response.json()
                
                if operation.get("done", False):
                    if "error" in operation:
                        print(f"❌ {operation_type.title()} failed!")
                        print(f"Error: {operation['error']}")
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
                print(f"Error checking {operation_type} status: {response.text}")
                time.sleep(30)
                
        except Exception as e:
            print(f"Exception while monitoring {operation_type}: {e}")
            time.sleep(30)
    
    print(f"⏰ Timeout after {max_checks} checks")
    return False

def main():
    print("🚀 IMPORT WORKING DOCUMENTS AND TRAIN")
    print("=" * 40)
    
    # Check how many documents we have
    print("📊 Checking final_labeled_documents...")
    
    # Step 1: Import the working documents
    print(f"\n🔄 Step 1: Importing working labeled documents...")
    import_result = import_working_documents()
    
    if not import_result or "name" not in import_result:
        print("❌ Failed to start import operation")
        return False
    
    import_operation = import_result["name"]
    print(f"✅ Import operation started: {import_operation}")
    
    # Monitor import
    import_success = monitor_operation(import_operation, "import")
    if not import_success:
        print("❌ Import failed or timed out. Check console for details.")
        print(f"Console: https://console.cloud.google.com/ai/document-ai/processors/details/{CLASSIFIER_PROCESSOR_ID}?project={PROJECT_ID}")
        return False
    
    # Step 2: Start training
    print(f"\n🎯 Step 2: Starting training...")
    training_result = start_training()
    
    if not training_result or "name" not in training_result:
        print("❌ Failed to start training operation")
        return False
    
    training_operation = training_result["name"]
    print(f"✅ Training operation started: {training_operation}")
    print(f"⏰ Training will take 30-60 minutes...")
    
    # Give user option to monitor or check later
    print(f"\n🔗 You can monitor training progress in the console:")
    print(f"https://console.cloud.google.com/ai/document-ai/processors/details/{CLASSIFIER_PROCESSOR_ID}?project={PROJECT_ID}")
    print(f"\n📊 Training operation: {training_operation}")
    
    user_input = input("\nDo you want to wait and monitor training? (y/n): ").lower()
    
    if user_input == 'y':
        training_success = monitor_operation(training_operation, "training")
        if training_success:
            print("\n🎉 TRAINING COMPLETED SUCCESSFULLY!")
            print(f"Your processor is now trained and ready to use!")
            return True
        else:
            print("\n⏰ Training monitoring timed out. Check console for final status.")
            return True
    else:
        print("\n✅ Training started successfully!")
        print("Check the console URL above to monitor training progress.")
        return True

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🏆 SUCCESS: Auto-labeling and training process completed!")
    else:
        print("\n❌ Process failed - check the details above")