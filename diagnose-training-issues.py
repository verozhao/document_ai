#!/usr/bin/env python3
"""
Comprehensive diagnostic script to identify why Document AI training isn't working.
This will check all components of the automated training pipeline.
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta
from google.cloud import firestore
from google.cloud import storage
from google.cloud import documentai_v1 as documentai
from google.api_core.client_options import ClientOptions
from google.cloud.workflows import executions_v1
from google.cloud import logging as cloud_logging
import requests

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'tetrix-462721')
PROCESSOR_ID = os.environ.get('DOCUMENT_AI_PROCESSOR_ID', 'ddc065df69bfa3b5')
LOCATION = os.environ.get('DOCUMENT_AI_LOCATION', 'us')
BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME', 'document-ai-test-veronica')
WORKFLOW_NAME = 'workflow-1-veronica'
WORKFLOW_LOCATION = 'us-central1'
FUNCTION_NAME = 'document-ai-auto-trainer'
FUNCTION_REGION = 'us-central1'

# ANSI colors
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
MAGENTA = '\033[95m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'

print(f"{BLUE}{BOLD}=== Document AI Training Pipeline Diagnostics ==={RESET}")
print(f"Project: {PROJECT_ID}")
print(f"Processor: {PROCESSOR_ID}")
print(f"Bucket: {BUCKET_NAME}")
print()

# Initialize clients
db = firestore.Client(project=PROJECT_ID)
storage_client = storage.Client(project=PROJECT_ID)
logging_client = cloud_logging.Client(project=PROJECT_ID)
workflow_client = executions_v1.ExecutionsClient()

# Document AI client
opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
docai_client = documentai.DocumentProcessorServiceClient(client_options=opts)


def print_section(title):
    """Print a section header."""
    print(f"\n{CYAN}{BOLD}{'='*60}{RESET}")
    print(f"{CYAN}{BOLD}{title}{RESET}")
    print(f"{CYAN}{BOLD}{'='*60}{RESET}")


def print_success(message):
    """Print success message."""
    print(f"{GREEN}✓ {message}{RESET}")


def print_error(message):
    """Print error message."""
    print(f"{RED}✗ {message}{RESET}")


def print_warning(message):
    """Print warning message."""
    print(f"{YELLOW}⚠ {message}{RESET}")


def print_info(message):
    """Print info message."""
    print(f"{BLUE}ℹ {message}{RESET}")


def check_document_labels():
    """Check if documents have proper labels for training."""
    print_section("1. Document Labels Check")
    
    try:
        # Get all documents
        all_docs = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).limit(50).get()
        
        total_docs = len(all_docs)
        print_info(f"Total documents found: {total_docs}")
        
        if total_docs == 0:
            print_error("No documents found in Firestore!")
            print_warning("Upload PDFs to trigger the pipeline:")
            print(f"  gsutil cp your-file.pdf gs://{BUCKET_NAME}/documents/")
            return False
        
        # Analyze document labels
        label_stats = {
            'with_label': 0,
            'without_label': 0,
            'label_distribution': {}
        }
        
        status_stats = {
            'pending_initial_training': 0,
            'completed': 0,
            'pending': 0,
            'failed': 0,
            'other': 0
        }
        
        unused_with_labels = []
        
        for doc in all_docs:
            doc_data = doc.to_dict()
            doc_label = doc_data.get('document_label')
            status = doc_data.get('status', 'unknown')
            used = doc_data.get('used_for_training', False)
            
            # Count statuses
            if status in status_stats:
                status_stats[status] += 1
            else:
                status_stats['other'] += 1
            
            # Count labels
            if doc_label:
                label_stats['with_label'] += 1
                label_stats['label_distribution'][doc_label] = label_stats['label_distribution'].get(doc_label, 0) + 1
                
                # Track unused documents with labels
                if not used and status in ['pending_initial_training', 'completed']:
                    unused_with_labels.append({
                        'id': doc.id,
                        'label': doc_label,
                        'status': status,
                        'created': doc_data.get('created_at')
                    })
            else:
                label_stats['without_label'] += 1
        
        # Print statistics
        print(f"\n{BOLD}Document Status Distribution:{RESET}")
        for status, count in status_stats.items():
            if count > 0:
                print(f"  {status}: {count}")
        
        print(f"\n{BOLD}Label Statistics:{RESET}")
        print(f"  Documents with labels: {label_stats['with_label']}")
        print(f"  Documents without labels: {label_stats['without_label']}")
        
        if label_stats['with_label'] == 0:
            print_error("No documents have labels! Training requires labeled documents.")
            print_warning("The auto-labeling might not be working. Check main.py")
            return False
        
        print(f"\n{BOLD}Label Distribution:{RESET}")
        for label, count in label_stats['label_distribution'].items():
            print(f"  {label}: {count}")
        
        print(f"\n{BOLD}Unused Documents Ready for Training:{RESET}")
        print(f"  Total: {len(unused_with_labels)}")
        
        if len(unused_with_labels) > 0:
            print(f"\n  First 5 unused documents:")
            for doc in unused_with_labels[:5]:
                print(f"    - {doc['id']} ({doc['label']}) - Status: {doc['status']}")
        
        if len(unused_with_labels) >= 3:
            print_success(f"Sufficient labeled documents available for training ({len(unused_with_labels)} >= 3)")
        else:
            print_warning(f"Not enough labeled documents for training ({len(unused_with_labels)} < 3)")
        
        return True
        
    except Exception as e:
        print_error(f"Error checking document labels: {str(e)}")
        return False


def check_training_configuration():
    """Check training configuration in Firestore."""
    print_section("2. Training Configuration Check")
    
    try:
        config_ref = db.collection('training_configs').document(PROCESSOR_ID)
        config = config_ref.get()
        
        if not config.exists:
            print_warning("No training configuration found - using defaults")
            return True
        
        config_data = config.to_dict()
        print_success("Training configuration found:")
        print(f"  Enabled: {config_data.get('enabled', 'N/A')}")
        print(f"  Initial training threshold: {config_data.get('min_documents_for_initial_training', 'N/A')}")
        print(f"  Incremental threshold: {config_data.get('min_documents_for_incremental', 'N/A')}")
        print(f"  Min accuracy for deployment: {config_data.get('min_accuracy_for_deployment', 'N/A')}")
        
        if not config_data.get('enabled', True):
            print_error("Training is DISABLED in configuration!")
            return False
        
        return True
        
    except Exception as e:
        print_error(f"Error checking configuration: {str(e)}")
        return False


def check_processor_state():
    """Check Document AI processor state and versions."""
    print_section("3. Document AI Processor Check")
    
    try:
        processor_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"
        
        # Get processor
        processor = docai_client.get_processor(name=processor_path)
        print_success(f"Processor found: {processor.display_name}")
        print(f"  Type: {processor.type_}")
        print(f"  State: {processor.state.name}")
        
        # List versions
        versions_request = documentai.ListProcessorVersionsRequest(parent=processor_path)
        versions = list(docai_client.list_processor_versions(request=versions_request))
        
        print(f"\n{BOLD}Processor Versions:{RESET}")
        print(f"  Total versions: {len(versions)}")
        
        deployed_version = None
        training_versions = []
        
        for v in versions:
            state_color = GREEN if v.state.name == 'DEPLOYED' else YELLOW
            print(f"  - {v.display_name}: {state_color}{v.state.name}{RESET}")
            
            if v.state == documentai.ProcessorVersion.State.DEPLOYED:
                deployed_version = v
            elif v.state == documentai.ProcessorVersion.State.TRAINING:
                training_versions.append(v)
        
        if deployed_version:
            print_success(f"Deployed version found: {deployed_version.display_name}")
            if processor.default_processor_version:
                print(f"  Default version: {processor.default_processor_version.split('/')[-1]}")
        else:
            print_warning("No deployed version found - initial training needed")
        
        if training_versions:
            print_warning(f"{len(training_versions)} versions currently training")
            for v in training_versions:
                print(f"  - {v.display_name}")
        
        return True
        
    except Exception as e:
        print_error(f"Error checking processor: {str(e)}")
        return False


def check_training_batches():
    """Check training batch history."""
    print_section("4. Training Batch History")
    
    try:
        # Get recent training batches
        batches = db.collection('training_batches').where(
            'processor_id', '==', PROCESSOR_ID
        ).order_by('started_at', direction=firestore.Query.DESCENDING).limit(10).get()
        
        if not batches:
            print_warning("No training batches found")
            print_info("This means training has never been triggered")
            return True
        
        print(f"Found {len(batches)} training batches:")
        
        for batch in batches[:5]:
            batch_data = batch.to_dict()
            batch_id = batch_data.get('batch_id', 'N/A')
            status = batch_data.get('status', 'unknown')
            doc_count = batch_data.get('document_count', 0)
            started = batch_data.get('started_at')
            
            status_color = GREEN if status == 'deployed' else (RED if 'failed' in status else YELLOW)
            
            print(f"\n  Batch: {batch_id}")
            print(f"    Status: {status_color}{status}{RESET}")
            print(f"    Documents: {doc_count}")
            print(f"    Started: {started}")
            
            if status in ['failed', 'training_failed']:
                error = batch_data.get('error_message', 'No error message')
                print(f"    {RED}Error: {error}{RESET}")
            
            label_counts = batch_data.get('label_counts', {})
            if label_counts:
                print(f"    Labels: {json.dumps(label_counts, indent=6)}")
        
        # Check for stuck training
        active_training = [b for b in batches if b.to_dict().get('status') in ['preparing', 'training', 'deploying']]
        if active_training:
            print_warning(f"\n{len(active_training)} training batches appear to be stuck:")
            for batch in active_training:
                batch_data = batch.to_dict()
                started = batch_data.get('started_at')
                if isinstance(started, datetime):
                    age = datetime.now(timezone.utc) - started.replace(tzinfo=timezone.utc)
                    if age > timedelta(hours=2):
                        print_error(f"  Batch {batch_data.get('batch_id')} stuck for {age}")
        
        return True
        
    except Exception as e:
        print_error(f"Error checking training batches: {str(e)}")
        return False


def check_workflow_executions():
    """Check recent workflow executions."""
    print_section("5. Workflow Execution History")
    
    try:
        parent = f"projects/{PROJECT_ID}/locations/{WORKFLOW_LOCATION}/workflows/{WORKFLOW_NAME}"
        
        # List executions
        request = executions_v1.ListExecutionsRequest(
            parent=parent,
            page_size=10
        )
        executions = list(workflow_client.list_executions(request=request))
        
        if not executions:
            print_warning("No workflow executions found")
            print_info("The workflow has never been triggered")
            return True
        
        print(f"Found {len(executions)} recent executions:")
        
        for exec in executions[:5]:
            exec_id = exec.name.split('/')[-1]
            state = exec.state.name
            
            state_color = GREEN if state == 'SUCCEEDED' else (RED if state == 'FAILED' else YELLOW)
            
            print(f"\n  Execution: {exec_id}")
            print(f"    State: {state_color}{state}{RESET}")
            
            if exec.error:
                print(f"    {RED}Error: {exec.error.message}{RESET}")
            
            # Try to get argument
            if exec.argument:
                try:
                    args = json.loads(exec.argument)
                    print(f"    Type: {args.get('training_type', 'N/A')}")
                    print(f"    Triggered: {args.get('triggered_at', 'N/A')}")
                except:
                    pass
        
        # Count failures
        failed_count = sum(1 for e in executions if e.state.name == 'FAILED')
        if failed_count > 0:
            print_error(f"\n{failed_count} out of {len(executions)} executions failed")
        
        return True
        
    except Exception as e:
        print_error(f"Error checking workflow executions: {str(e)}")
        return False


def check_cloud_function_logs():
    """Check Cloud Function logs for errors."""
    print_section("6. Cloud Function Logs")
    
    try:
        # Get recent logs
        filter_str = f'''
        resource.type="cloud_function"
        AND resource.labels.function_name="{FUNCTION_NAME}"
        AND severity>="INFO"
        AND timestamp>="{(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}"
        '''
        
        entries = list(logging_client.list_entries(
            filter_=filter_str,
            order_by=cloud_logging.DESCENDING,
            max_results=50
        ))
        
        if not entries:
            print_warning("No recent Cloud Function logs found")
            return True
        
        print(f"Found {len(entries)} log entries in the last hour")
        
        # Count by severity
        severity_counts = {}
        training_triggers = []
        errors = []
        
        for entry in entries:
            severity = entry.severity
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            # Look for specific patterns
            if isinstance(entry.payload, dict):
                message = entry.payload.get('message', '')
            else:
                message = str(entry.payload)
            
            if 'Triggering' in message and 'training' in message:
                training_triggers.append(message)
            
            if severity in ['ERROR', 'CRITICAL']:
                errors.append({
                    'time': entry.timestamp,
                    'message': message[:200]
                })
        
        print(f"\n{BOLD}Log Severity Distribution:{RESET}")
        for severity, count in severity_counts.items():
            color = RED if severity in ['ERROR', 'CRITICAL'] else (YELLOW if severity == 'WARNING' else '')
            print(f"  {color}{severity}: {count}{RESET}")
        
        if training_triggers:
            print_success(f"\nFound {len(training_triggers)} training trigger attempts")
            for trigger in training_triggers[:3]:
                print(f"  - {trigger}")
        else:
            print_warning("No training trigger attempts found in recent logs")
        
        if errors:
            print_error(f"\nFound {len(errors)} errors:")
            for error in errors[:5]:
                print(f"  [{error['time'].strftime('%H:%M:%S')}] {error['message']}")
        
        return True
        
    except Exception as e:
        print_error(f"Error checking logs: {str(e)}")
        return False


def diagnose_common_issues():
    """Diagnose common configuration issues."""
    print_section("7. Common Issues Diagnosis")
    
    issues_found = []
    
    # Check 1: Documents without labels
    try:
        no_label_docs = db.collection('processed_documents').where(
            'processor_id', '==', PROCESSOR_ID
        ).where('document_label', '==', None).limit(5).get()
        
        if no_label_docs:
            issues_found.append("Documents found without labels - auto-labeling may be broken")
    except:
        pass
    
    # Check 2: Stuck training batches
    try:
        stuck_batches = db.collection('training_batches').where(
            'processor_id', '==', PROCESSOR_ID
        ).where('status', 'in', ['preparing', 'training']).get()
        
        for batch in stuck_batches:
            batch_data = batch.to_dict()
            started = batch_data.get('started_at')
            if isinstance(started, datetime):
                age = datetime.now(timezone.utc) - started.replace(tzinfo=timezone.utc)
                if age > timedelta(hours=1):
                    issues_found.append(f"Training batch {batch_data.get('batch_id')} stuck for {age}")
    except:
        pass
    
    # Check 3: Workflow permissions
    try:
        # This is a simple check - actual permission issues would show in execution logs
        parent = f"projects/{PROJECT_ID}/locations/{WORKFLOW_LOCATION}/workflows/{WORKFLOW_NAME}"
        # If we can list executions, permissions are likely OK
        request = executions_v1.ListExecutionsRequest(parent=parent, page_size=1)
        list(workflow_client.list_executions(request=request))
    except Exception as e:
        if "403" in str(e):
            issues_found.append("Workflow permission issues detected")
    
    if issues_found:
        print_error(f"Found {len(issues_found)} potential issues:")
        for issue in issues_found:
            print(f"  - {issue}")
    else:
        print_success("No common issues detected")
    
    return len(issues_found) == 0


def suggest_fixes():
    """Suggest fixes based on diagnostics."""
    print_section("Suggested Actions")
    
    print(f"{BOLD}To trigger training manually:{RESET}")
    print(f"  python3 manual-trigger-training.py trigger-initial")
    
    print(f"\n{BOLD}To upload test documents:{RESET}")
    print(f"  gsutil cp test_capital_call.pdf gs://{BUCKET_NAME}/documents/")
    print(f"  gsutil cp test_financial_statement.pdf gs://{BUCKET_NAME}/documents/")
    
    print(f"\n{BOLD}To monitor in real-time:{RESET}")
    print(f"  gcloud functions logs read {FUNCTION_NAME} --region={FUNCTION_REGION} --follow")
    
    print(f"\n{BOLD}To check workflow execution details:{RESET}")
    print(f"  gcloud workflows executions list --workflow={WORKFLOW_NAME} --location={WORKFLOW_LOCATION}")
    
    print(f"\n{BOLD}If documents aren't getting labels:{RESET}")
    print(f"  1. Check that filenames contain keywords like 'capital_call', 'financial_statement'")
    print(f"  2. Update DOCUMENT_TYPE_KEYWORDS in main.py")
    print(f"  3. Ensure main.py auto_label_document() function is working")
    
    print(f"\n{BOLD}If training keeps failing:{RESET}")
    print(f"  1. Check that all documents are PDFs")
    print(f"  2. Ensure at least 2-3 documents per label type")
    print(f"  3. Check Document AI API quotas")
    print(f"  4. Verify service account permissions")


def main():
    """Run all diagnostics."""
    print(f"{MAGENTA}{BOLD}Starting comprehensive diagnostics...{RESET}\n")
    
    # Run all checks
    checks = [
        check_document_labels(),
        check_training_configuration(),
        check_processor_state(),
        check_training_batches(),
        check_workflow_executions(),
        check_cloud_function_logs(),
        diagnose_common_issues()
    ]
    
    # Summary
    passed = sum(checks)
    total = len(checks)
    
    print_section("Summary")
    if passed == total:
        print_success(f"All {total} checks passed!")
    else:
        print_error(f"{total - passed} out of {total} checks failed")
    
    # Provide suggestions
    suggest_fixes()


if __name__ == "__main__":
    main()