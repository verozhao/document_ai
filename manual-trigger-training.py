#!/usr/bin/env python3
"""
Manual script to trigger Document AI training.
Use this for testing or when automatic triggers aren't working.
"""

import os
import json
import sys
from datetime import datetime, timezone
from google.cloud import firestore
from google.cloud import storage
from google.cloud.workflows import executions_v1
from google.cloud.workflows.executions_v1 import Execution

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'tetrix-462721')
PROCESSOR_ID = os.environ.get('DOCUMENT_AI_PROCESSOR_ID', 'ddc065df69bfa3b5')
BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME', 'document-ai-test-veronica')
WORKFLOW_NAME = 'workflow-1-veronica'
WORKFLOW_LOCATION = 'us-central1'

print(f"=== Manual Document AI Training Trigger ===")
print(f"Project: {PROJECT_ID}")
print(f"Processor: {PROCESSOR_ID}")
print()

def simulate_document_upload():
    """Simulate a document upload to test the pipeline."""
    print("Testing document upload simulation...")
    
    # Import the Cloud Function code
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    try:
        from main import process_document_upload, check_training_conditions
        
        # Create a mock event
        test_event = {
            'bucket': BUCKET_NAME,
            'name': 'documents/test_document.pdf',
            'contentType': 'application/pdf',
            'size': '1024',
            'timeCreated': datetime.now(timezone.utc).isoformat()
        }
        
        # Create a mock context
        class MockContext:
            event_id = 'test-event-123'
            timestamp = datetime.now(timezone.utc).isoformat()
            resource = {'name': f'projects/{PROJECT_ID}/buckets/{BUCKET_NAME}'}
        
        print(f"Simulating upload of: {test_event['name']}")
        
        # Call the function
        result = process_document_upload(test_event, MockContext())
        print(f"Result: {json.dumps(result, indent=2)}")
        
        # Check training conditions
        print("\nChecking training conditions...")
        should_train, training_type = check_training_conditions()
        print(f"Should train: {should_train}")
        if should_train:
            print(f"Training type: {training_type}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

def trigger_workflow_manually(training_type='initial'):
    """Manually trigger the training workflow."""
    print(f"\nManually triggering {training_type} training workflow...")
    
    try:
        client = executions_v1.ExecutionsClient()
        parent = f"projects/{PROJECT_ID}/locations/{WORKFLOW_LOCATION}/workflows/{WORKFLOW_NAME}"
        
        # Create execution request
        execution = Execution(
            argument=json.dumps({
                'processor_id': PROCESSOR_ID,
                'training_type': training_type,
                'triggered_at': datetime.now(timezone.utc).isoformat(),
                'manual_trigger': True
            })
        )
        
        # Create execution
        request = executions_v1.CreateExecutionRequest(
            parent=parent,
            execution=execution
        )
        
        response = client.create_execution(request=request)
        
        print(f"✓ Workflow execution started!")
        print(f"  Execution ID: {response.name.split('/')[-1]}")
        print(f"  State: {response.state.name}")
        print(f"\nMonitor progress:")
        print(f"  gcloud workflows executions describe {response.name.split('/')[-1]} \\")
        print(f"    --workflow={WORKFLOW_NAME} --location={WORKFLOW_LOCATION}")
        
        return response.name
        
    except Exception as e:
        print(f"✗ Error triggering workflow: {str(e)}")
        return None

def reset_document_training_status():
    """Reset training status for documents (useful for testing)."""
    print("\nResetting document training status...")
    
    try:
        db = firestore.Client(project=PROJECT_ID)
        
        # Get all completed documents that were used for training
        docs = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).where('used_for_training', '==', True).get()
        
        count = 0
        for doc in docs:
            doc_ref = db.collection('processed_documents').document(doc.id)
            doc_ref.update({
                'used_for_training': False,
                'training_batch_id': None
            })
            count += 1
        
        print(f"✓ Reset {count} documents to unused status")
        
        # Check current counts
        unused_docs = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).where('status', '==', 'completed').where(
            'used_for_training', '==', False
        ).get()
        
        print(f"  Total unused completed documents: {len(unused_docs)}")
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")

def upload_test_document():
    """Upload a test PDF to trigger the pipeline."""
    print("\nCreating and uploading test document...")
    
    try:
        # Create a simple test PDF
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            c = canvas.Canvas(tmp.name, pagesize=letter)
            c.drawString(100, 750, "Test Document for Training")
            c.drawString(100, 700, f"Generated at: {datetime.now()}")
            c.drawString(100, 650, "This is a financial statement")
            c.drawString(100, 600, "Total Assets: $1,000,000")
            c.save()
            
            # Upload to GCS
            storage_client = storage.Client(project=PROJECT_ID)
            bucket = storage_client.bucket(BUCKET_NAME)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            blob_name = f"documents/test_document_{timestamp}.pdf"
            blob = bucket.blob(blob_name)
            
            blob.upload_from_filename(tmp.name)
            print(f"✓ Uploaded test document: gs://{BUCKET_NAME}/{blob_name}")
            
            # Clean up
            os.unlink(tmp.name)
            
    except ImportError:
        print("✗ reportlab not installed. Install with: pip install reportlab")
        print("  Alternative: Upload manually with:")
        print(f"  gsutil cp your-document.pdf gs://{BUCKET_NAME}/documents/")
    except Exception as e:
        print(f"✗ Error: {str(e)}")

def main():
    """Main menu for manual operations."""
    while True:
        print("\n=== Manual Training Control ===")
        print("1. Test document upload simulation")
        print("2. Trigger initial training workflow")
        print("3. Trigger incremental training workflow")
        print("4. Reset document training status")
        print("5. Upload test document to GCS")
        print("6. Exit")
        
        choice = input("\nSelect option (1-6): ").strip()
        
        if choice == '1':
            simulate_document_upload()
        elif choice == '2':
            trigger_workflow_manually('initial')
        elif choice == '3':
            trigger_workflow_manually('incremental')
        elif choice == '4':
            reset_document_training_status()
        elif choice == '5':
            upload_test_document()
        elif choice == '6':
            break
        else:
            print("Invalid option")
        
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Command line mode
        if sys.argv[1] == 'simulate':
            simulate_document_upload()
        elif sys.argv[1] == 'trigger-initial':
            trigger_workflow_manually('initial')
        elif sys.argv[1] == 'trigger-incremental':
            trigger_workflow_manually('incremental')
        elif sys.argv[1] == 'reset':
            reset_document_training_status()
        elif sys.argv[1] == 'upload':
            upload_test_document()
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print("Available commands: simulate, trigger-initial, trigger-incremental, reset, upload")
    else:
        # Interactive mode
        main()