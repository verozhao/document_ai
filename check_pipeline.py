#!/usr/bin/env python3
"""
Check the complete Document AI pipeline status and fix issues.
"""

import os
import subprocess
import json
from google.cloud import firestore
from google.cloud import storage
from datetime import datetime, timezone

PROJECT_ID = "tetrix-462721"
BUCKET_NAME = "document-ai-test-veronica"
WORKFLOW_NAME = "workflow-1-veronica"
FUNCTION_NAME = "document-ai-auto-trainer"

# Initialize clients
db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)


def check_eventarc_triggers():
    """Check for Eventarc triggers that might interfere."""
    print("\n=== CHECKING EVENTARC TRIGGERS ===")
    try:
        result = subprocess.run(
            ["gcloud", "eventarc", "triggers", "list", "--location=us-central1", "--format=json"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            triggers = json.loads(result.stdout)
            if triggers:
                print(f"Found {len(triggers)} Eventarc trigger(s):")
                for trigger in triggers:
                    print(f"  - {trigger.get('name')}")
                    print(f"    Destination: {trigger.get('destination', {}).get('workflow')}")
                print("\n⚠️  WARNING: Eventarc triggers may conflict with Cloud Function!")
                print("  Run: gcloud eventarc triggers delete eventarc-trigger-test-veronica --location=us-central1")
            else:
                print("✓ No Eventarc triggers found (good!)")
        else:
            print("✓ No Eventarc triggers found")
    except Exception as e:
        print(f"Error checking triggers: {e}")


def check_cloud_function():
    """Check Cloud Function status."""
    print("\n=== CHECKING CLOUD FUNCTION ===")
    try:
        result = subprocess.run(
            ["gcloud", "functions", "describe", FUNCTION_NAME, "--region=us-east1", "--format=json"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            func = json.loads(result.stdout)
            print(f"✓ Cloud Function exists: {func.get('name')}")
            print(f"  Status: {func.get('status')}")
            print(f"  Trigger: {func.get('eventTrigger', {}).get('eventType')}")
            print(f"  Bucket: {func.get('eventTrigger', {}).get('resource', '').split('/')[-1]}")
            
            # Check environment variables
            env_vars = func.get('environmentVariables', {})
            print(f"\n  Environment variables:")
            for key in ['GCP_PROJECT_ID', 'DOCUMENT_AI_PROCESSOR_ID', 'WORKFLOW_NAME']:
                value = env_vars.get(key, 'NOT SET')
                status = "✓" if value != 'NOT SET' else "✗"
                print(f"    {status} {key}: {value}")
        else:
            print("✗ Cloud Function not found!")
    except Exception as e:
        print(f"Error checking function: {e}")


def check_workflow():
    """Check Workflow status."""
    print("\n=== CHECKING WORKFLOW ===")
    try:
        result = subprocess.run(
            ["gcloud", "workflows", "describe", WORKFLOW_NAME, "--location=us-central1", "--format=json"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            workflow = json.loads(result.stdout)
            print(f"✓ Workflow exists: {workflow.get('name')}")
            print(f"  State: {workflow.get('state')}")
            print(f"  Service Account: {workflow.get('serviceAccount', 'default')}")
        else:
            print("✗ Workflow not found!")
    except Exception as e:
        print(f"Error checking workflow: {e}")


def check_workflow_executions():
    """Check recent workflow executions."""
    print("\n=== CHECKING WORKFLOW EXECUTIONS ===")
    try:
        result = subprocess.run(
            ["gcloud", "workflows", "executions", "list", 
             f"--workflow={WORKFLOW_NAME}", "--location=us-central1", 
             "--limit=5", "--format=json"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            executions = json.loads(result.stdout)
            if executions:
                print(f"Found {len(executions)} recent execution(s):")
                for exec in executions:
                    print(f"  - {exec.get('name', '').split('/')[-1]}")
                    print(f"    State: {exec.get('state')}")
                    print(f"    Start: {exec.get('startTime')}")
                    if exec.get('error'):
                        print(f"    Error: {exec.get('error', {}).get('message')}")
            else:
                print("No workflow executions found")
                print("This means the workflow has never been triggered!")
        else:
            print("Error getting executions")
    except Exception as e:
        print(f"Error checking executions: {e}")


def check_firestore_data():
    """Check Firestore collections."""
    print("\n=== CHECKING FIRESTORE DATA ===")
    
    # Check documents
    docs = list(db.collection('processed_documents').where('processor_id', '==', 'ddc065df69bfa3b5').limit(10).get())
    print(f"Processed documents: {len(docs)}")
    
    if docs:
        # Count by status
        status_counts = {}
        for doc in docs:
            status = doc.to_dict().get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, count in status_counts.items():
            print(f"  {status}: {count}")
    
    # Check training config
    config = db.collection('training_configs').document('ddc065df69bfa3b5').get()
    if config.exists:
        config_data = config.to_dict()
        print(f"\nTraining config:")
        print(f"  Enabled: {config_data.get('enabled', False)}")
        print(f"  Initial threshold: {config_data.get('min_documents_for_initial_training', 10)}")
        print(f"  Incremental threshold: {config_data.get('min_documents_for_incremental', 5)}")
    else:
        print("\n✗ No training config found!")
    
    # Check training batches
    batches = list(db.collection('training_batches').where('processor_id', '==', 'ddc065df69bfa3b5').limit(5).get())
    print(f"\nTraining batches: {len(batches)}")


def check_gcs_files():
    """Check GCS bucket files."""
    print("\n=== CHECKING GCS FILES ===")
    bucket = storage_client.bucket(BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix='documents/', max_results=10))
    
    pdf_count = sum(1 for b in blobs if b.name.endswith('.pdf'))
    print(f"Files in documents/: {len(blobs)} ({pdf_count} PDFs)")
    
    if blobs:
        print("\nRecent files:")
        for blob in sorted(blobs, key=lambda b: b.time_created, reverse=True)[:5]:
            print(f"  - {blob.name} ({blob.time_created})")


def check_function_logs():
    """Show recent Cloud Function logs."""
    print("\n=== RECENT CLOUD FUNCTION LOGS ===")
    try:
        result = subprocess.run(
            ["gcloud", "functions", "logs", "read", FUNCTION_NAME, 
             "--region=us-east1", "--limit=10", "--format=json"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and result.stdout:
            logs = json.loads(result.stdout)
            if logs:
                for log in logs:
                    timestamp = log.get('timestamp', '')
                    text = log.get('text', '').strip()
                    if text:
                        print(f"{timestamp}: {text[:100]}...")
            else:
                print("No recent logs found")
        else:
            print("No logs available")
    except Exception as e:
        print(f"Error getting logs: {e}")


def fix_common_issues():
    """Fix common configuration issues."""
    print("\n=== FIXING COMMON ISSUES ===")
    
    # 1. Set lower thresholds
    print("1. Setting training thresholds for testing...")
    config_ref = db.collection('training_configs').document('ddc065df69bfa3b5')
    config_ref.set({
        'enabled': True,
        'min_documents_for_initial_training': 3,
        'min_documents_for_incremental': 2,
        'min_accuracy_for_deployment': 0.7,
        'check_interval_minutes': 60,
        'created_at': datetime.now(timezone.utc)
    })
    print("   ✓ Config updated")
    
    # 2. Convert stuck documents
    print("\n2. Checking for stuck documents...")
    pending_docs = list(db.collection('processed_documents')
                       .where('processor_id', '==', 'ddc065df69bfa3b5')
                       .where('status', '==', 'pending').get())
    
    if pending_docs:
        print(f"   Found {len(pending_docs)} stuck documents")
        for doc in pending_docs:
            doc.reference.update({'status': 'pending_initial_training'})
        print("   ✓ Fixed stuck documents")
    else:
        print("   ✓ No stuck documents")


def main():
    print("Document AI Pipeline Status Check")
    print("=" * 50)
    
    # Run all checks
    check_eventarc_triggers()
    check_cloud_function()
    check_workflow()
    check_workflow_executions()
    check_firestore_data()
    check_gcs_files()
    check_function_logs()
    
    # Fix issues
    print("\n" + "=" * 50)
    response = input("\nFix common issues? (y/n): ")
    if response.lower() == 'y':
        fix_common_issues()
    
    print("\n" + "=" * 50)
    print("RECOMMENDATIONS:")
    print("1. Delete the Eventarc trigger to avoid conflicts")
    print("2. Make sure Cloud Function has correct environment variables")
    print("3. Upload at least 3 PDFs to trigger initial training")
    print("4. Monitor logs: gcloud functions logs read document-ai-auto-trainer --follow")


if __name__ == "__main__":
    main()