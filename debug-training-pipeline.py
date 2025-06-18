#!/usr/bin/env python3
"""
Debug script to check the Document AI training pipeline status
and diagnose common issues.
"""

import os
import sys
from datetime import datetime, timezone
from google.cloud import firestore
from google.cloud import storage
from google.cloud import documentai_v1 as documentai
from google.api_core.client_options import ClientOptions
from google.cloud.workflows import executions_v1
from google.cloud import logging as cloud_logging

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'tetrix-462721')
PROCESSOR_ID = os.environ.get('DOCUMENT_AI_PROCESSOR_ID', 'ddc065df69bfa3b5')
LOCATION = os.environ.get('DOCUMENT_AI_LOCATION', 'us')
BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME', 'document-ai-test-veronica')
WORKFLOW_NAME = 'workflow-1-veronica'
FUNCTION_NAME = 'document-ai-service'

print(f"=== Document AI Training Pipeline Debugger ===")
print(f"Project ID: {PROJECT_ID}")
print(f"Processor ID: {PROCESSOR_ID}")
print(f"Bucket: {BUCKET_NAME}")
print(f"Location: {LOCATION}")
print()

# Initialize clients
db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
logging_client = cloud_logging.Client(project=PROJECT_ID)

# Document AI client
opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)

def check_processor_status():
    """Check Document AI processor status."""
    print("1. Checking Document AI Processor...")
    try:
        processor_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        processor = docai_client.get_processor(name=processor_path)
        print(f"   ✓ Processor found: {processor.display_name}")
        print(f"   - Type: {processor.type_}")
        print(f"   - State: {processor.state.name}")
        
        # Check versions
        versions_request = documentai.ListProcessorVersionsRequest(parent=processor_path)
        versions = list(docai_client.list_processor_versions(request=versions_request))
        print(f"   - Versions: {len(versions)}")
        
        has_deployed = False
        for v in versions:
            if v.state == documentai.ProcessorVersion.State.DEPLOYED:
                print(f"   ✓ Deployed version: {v.display_name}")
                has_deployed = True
                break
        
        if not has_deployed:
            print("   ⚠️  No deployed version found - initial training needed")
        
        return has_deployed
    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False

def check_bucket_structure():
    """Check GCS bucket structure."""
    print("\n2. Checking GCS Bucket...")
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        if not bucket.exists():
            print(f"   ✗ Bucket {BUCKET_NAME} does not exist!")
            return False
        
        print(f"   ✓ Bucket exists: gs://{BUCKET_NAME}")
        
        # Check folders
        folders = ['documents/', 'training/', 'processed/', 'failed/']
        for folder in folders:
            blobs = list(bucket.list_blobs(prefix=folder, max_results=1))
            if blobs:
                print(f"   ✓ Folder exists: {folder}")
            else:
                print(f"   ⚠️  Folder missing: {folder}")
        
        # Count documents
        doc_blobs = list(bucket.list_blobs(prefix='documents/', delimiter='/'))
        pdf_count = sum(1 for blob in doc_blobs if blob.name.endswith('.pdf'))
        print(f"   - PDF documents in documents/: {pdf_count}")
        
        return True
    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False

def check_firestore_data():
    """Check Firestore collections and data."""
    print("\n3. Checking Firestore Data...")
    try:
        # Check training config
        config_ref = db.collection('training_configs').document(PROCESSOR_ID)
        config = config_ref.get()
        
        if config.exists:
            config_data = config.to_dict()
            print(f"   ✓ Training config exists")
            print(f"   - Enabled: {config_data.get('enabled', 'N/A')}")
            print(f"   - Initial training threshold: {config_data.get('min_documents_for_initial_training', 'N/A')}")
            print(f"   - Incremental threshold: {config_data.get('min_documents_for_incremental', 'N/A')}")
        else:
            print(f"   ⚠️  No training config found")
        
        # Count documents by status
        statuses = ['pending', 'pending_initial_training', 'completed', 'failed']
        for status in statuses:
            docs = db.collection('processed_documents').where(
                'processor_id', '==', PROCESSOR_ID
            ).where('status', '==', status).get()
            count = len(docs)
            if count > 0:
                print(f"   - Documents with status '{status}': {count}")
        
        # Check unused documents
        unused_docs = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).where('status', '==', 'completed').where(
            'used_for_training', '==', False
        ).get()
        print(f"   - Unused completed documents: {len(unused_docs)}")
        
        # Check training batches
        batches = db.collection('training_batches').where(
            'processor_id', '==', PROCESSOR_ID
        ).order_by('started_at', direction=firestore.Query.DESCENDING).limit(5).get()
        
        print(f"\n   Recent training batches:")
        if batches:
            for batch in batches:
                batch_data = batch.to_dict()
                print(f"   - {batch_data.get('batch_id', 'N/A')}: {batch_data.get('status', 'N/A')} ({batch_data.get('document_count', 0)} docs)")
        else:
            print("   - No training batches found")
        
        return True
    except Exception as e:
        print(f"   ✗ Error: {str(e)}")
        return False

def check_cloud_function_logs():
    """Check recent Cloud Function logs."""
    print("\n4. Checking Cloud Function Logs...")
    try:
        # Get recent logs
        filter_str = f'resource.type="cloud_function" AND resource.labels.function_name="{FUNCTION_NAME}" AND severity>=INFO'
        
        entries = list(logging_client.list_entries(
            filter_=filter_str,
            order_by=cloud_logging.DESCENDING,
            max_results=10
        ))
        
        if entries:
            print(f"   Recent log entries:")
            for entry in entries[:5]:
                timestamp = entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                message = entry.payload.get('message', entry.payload) if isinstance(entry.payload, dict) else str(entry.payload)
                severity = entry.severity
                print(f"   [{timestamp}] {severity}: {message[:100]}...")
        else:
            print("   ⚠️  No recent logs found")
        
        # Check for errors
        error_filter = f'resource.type="cloud_function" AND resource.labels.function_name="{FUNCTION_NAME}" AND severity>=ERROR'
        errors = list(logging_client.list_entries(
            filter_=error_filter,
            order_by=cloud_logging.DESCENDING,
            max_results=5
        ))
        
        if errors:
            print(f"\n   ⚠️  Recent errors:")
            for error in errors[:3]:
                timestamp = error.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                message = error.payload.get('message', error.payload) if isinstance(error.payload, dict) else str(error.payload)
                print(f"   [{timestamp}] {message[:100]}...")
        
        return True
    except Exception as e:
        print(f"   ⚠️  Warning: Could not check logs: {str(e)}")
        return False

def check_workflow_executions():
    """Check recent workflow executions."""
    print("\n5. Checking Workflow Executions...")
    try:
        client = executions_v1.ExecutionsClient()
        parent = f"projects/{PROJECT_ID}/locations/us-central1/workflows/{WORKFLOW_NAME}"
        
        # List recent executions with correct parameters
        request = executions_v1.ListExecutionsRequest(
            parent=parent,
            page_size=5
        )
        executions = list(client.list_executions(request=request))
        
        if executions:
            print(f"   Recent workflow executions:")
            for exec in executions[:5]:
                print(f"   - {exec.name.split('/')[-1]}: {exec.state.name}")
                if exec.error:
                    print(f"     Error: {exec.error.message}")
        else:
            print("   - No workflow executions found")
        
        return True
    except Exception as e:
        print(f"   ⚠️  Warning: Could not check workflow executions: {str(e)}")
        return False

def check_active_training():
    """Check for any active training processes."""
    print("\n6. Checking Active Training Status...")
    try:
        # Check active training in Firestore
        active_training = db.collection('training_batches').where(
            'processor_id', '==', PROCESSOR_ID
        ).where('status', 'in', ['pending', 'in_progress']).get()
        
        if active_training:
            print("   ⚠️  Found active training processes:")
            for training in active_training:
                data = training.to_dict()
                print(f"   - Batch ID: {data.get('batch_id', 'N/A')}")
                print(f"     Status: {data.get('status', 'N/A')}")
                print(f"     Started: {data.get('started_at', 'N/A')}")
                print(f"     Document Count: {data.get('document_count', 0)}")
                
                # Check if training is stuck (older than 1 hour)
                if 'started_at' in data:
                    started = data['started_at']
                    if isinstance(started, str):
                        started = datetime.fromisoformat(started.replace('Z', '+00:00'))
                    if (datetime.now(timezone.utc) - started).total_seconds() > 3600:
                        print("     ⚠️  WARNING: Training appears to be stuck (older than 1 hour)")
        else:
            print("   ✓ No active training processes found")
            
        # Check Document AI processor training status
        processor_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        versions_request = documentai.ListProcessorVersionsRequest(parent=processor_path)
        versions = list(docai_client.list_processor_versions(request=versions_request))
        
        training_versions = [v for v in versions if v.state == documentai.ProcessorVersion.State.TRAINING]
        if training_versions:
            print("\n   ⚠️  Found training versions in Document AI:")
            for v in training_versions:
                print(f"   - Version: {v.name}")
                print(f"     State: {v.state.name}")
                print(f"     Created: {v.create_time}")
        else:
            print("   ✓ No training versions found in Document AI")
            
        return True
    except Exception as e:
        print(f"   ✗ Error checking active training: {str(e)}")
        return False

def suggest_next_steps(has_deployed_version):
    """Suggest next steps based on findings."""
    print("\n=== Recommendations ===")
    
    if not has_deployed_version:
        print("1. Upload at least 3 PDF documents to trigger initial training:")
        print(f"   gsutil cp your-documents/*.pdf gs://{BUCKET_NAME}/documents/")
        print()
        print("2. Monitor the Cloud Function logs:")
        print(f"   gcloud functions logs read {FUNCTION_NAME} --region=us-central1 --follow")
    else:
        print("1. Upload at least 2 PDF documents to trigger incremental training:")
        print(f"   gsutil cp your-documents/*.pdf gs://{BUCKET_NAME}/documents/")
        print()
        print("2. Check if documents are being processed:")
        print("   - Look for 'completed' status documents in Firestore")
        print("   - Check Cloud Function logs for processing activity")
    
    print("\n3. Manual trigger (for testing):")
    print("   You can manually trigger the workflow with:")
    print(f"   gcloud workflows execute {WORKFLOW_NAME} --location=us-central1 \\")
    print(f"     --data='{{\"processor_id\":\"{PROCESSOR_ID}\",\"training_type\":\"initial\"}}'")

def main():
    """Run all checks."""
    has_deployed = check_processor_status()
    check_bucket_structure()
    check_firestore_data()
    check_cloud_function_logs()
    check_workflow_executions()
    check_active_training()
    suggest_next_steps(has_deployed)

if __name__ == "__main__":
    main()