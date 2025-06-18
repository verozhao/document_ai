#!/bin/bash
# Step-by-step guide to fix Document AI automated training

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-tetrix-462721}"
PROCESSOR_ID="${DOCUMENT_AI_PROCESSOR_ID:-ddc065df69bfa3b5}"
BUCKET_NAME="${GCS_BUCKET_NAME:-document-ai-test-veronica}"
FUNCTION_NAME="document-ai-auto-trainer"
WORKFLOW_NAME="workflow-1-veronica"
REGION="us-central1"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

echo -e "${BLUE}${BOLD}=== Document AI Training Fix Guide ===${NC}"
echo "This will help you fix the automated training pipeline step by step."
echo

# Step 1: Update the Cloud Function with fixed code
echo -e "\n${YELLOW}Step 1: Update Cloud Function with fixed code${NC}"
echo "The main issue is that documents need proper labels for training."
echo "Press Enter to update the Cloud Function with the fixed main.py..."
read

echo "Deploying updated Cloud Function..."
gcloud functions deploy $FUNCTION_NAME \
    --runtime python39 \
    --trigger-resource $BUCKET_NAME \
    --trigger-event google.storage.object.finalize \
    --entry-point process_document_upload \
    --source . \
    --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,DOCUMENT_AI_PROCESSOR_ID=$PROCESSOR_ID,DOCUMENT_AI_LOCATION=us,WORKFLOW_NAME=$WORKFLOW_NAME,GCS_BUCKET_NAME=$BUCKET_NAME" \
    --memory 512MB \
    --timeout 540s \
    --region $REGION \
    --no-gen2

echo -e "${GREEN}✓ Cloud Function updated${NC}"

# Step 2: Update the Workflow
echo -e "\n${YELLOW}Step 2: Update Workflow with fixed training logic${NC}"
echo "The workflow needs to properly format training data with labels."
echo "Press Enter to update the workflow..."
read

echo "Deploying updated workflow..."
gcloud workflows deploy $WORKFLOW_NAME \
    --source=training-workflow.yaml \
    --location=$REGION

echo -e "${GREEN}✓ Workflow updated${NC}"

# Step 3: Clear any stuck training batches
echo -e "\n${YELLOW}Step 3: Clear stuck training batches${NC}"
echo "Checking for stuck training batches..."

python3 << EOF
import os
from google.cloud import firestore
from datetime import datetime, timezone, timedelta

db = firestore.Client(project='$PROJECT_ID')
stuck_batches = db.collection('training_batches').where(
    'processor_id', '==', '$PROCESSOR_ID'
).where('status', 'in', ['preparing', 'training']).get()

count = 0
for batch in stuck_batches:
    batch_data = batch.to_dict()
    started = batch_data.get('started_at')
    if isinstance(started, datetime):
        age = datetime.now(timezone.utc) - started.replace(tzinfo=timezone.utc)
        if age > timedelta(hours=1):
            print(f"Clearing stuck batch: {batch.id}")
            batch.reference.update({'status': 'cancelled', 'error_message': 'Cleared by fix script'})
            count += 1

print(f"Cleared {count} stuck batches")
EOF

echo -e "${GREEN}✓ Stuck batches cleared${NC}"

# Step 4: Reset document training status
echo -e "\n${YELLOW}Step 4: Reset document training status${NC}"
echo "This will mark all documents as unused for training."
echo "Press Enter to reset document status..."
read

python3 << EOF
import os
from google.cloud import firestore

db = firestore.Client(project='$PROJECT_ID')
docs = db.collection('processed_documents').where(
    'processor_id', '==', '$PROCESSOR_ID'
).where('used_for_training', '==', True).get()

count = 0
for doc in docs:
    doc.reference.update({
        'used_for_training': False,
        'training_batch_id': None
    })
    count += 1

print(f"Reset {count} documents to unused status")
EOF

echo -e "${GREEN}✓ Document status reset${NC}"

# Step 5: Create and upload test documents
echo -e "\n${YELLOW}Step 5: Create test documents with proper labels${NC}"
echo "Creating test documents that will be auto-labeled correctly..."

if command -v python3 -c "import reportlab" &> /dev/null; then
    python3 create-test-documents.py
else
    echo -e "${YELLOW}reportlab not installed. Creating simple test files...${NC}"
    
    # Create test documents manually
    mkdir -p test_documents
    
    echo "CAPITAL CALL NOTICE - Test Document" > test_documents/capital_call_test_1.txt
    echo "FINANCIAL STATEMENT - Test Document" > test_documents/financial_statement_test_1.txt
    echo "DISTRIBUTION NOTICE - Test Document" > test_documents/distribution_notice_test_1.txt
    
    # Upload to GCS
    for file in test_documents/*.txt; do
        filename=$(basename "$file" .txt).pdf
        gsutil cp "$file" "gs://$BUCKET_NAME/documents/$filename"
        echo -e "${GREEN}✓ Uploaded $filename${NC}"
    done
fi

# Step 6: Monitor the pipeline
echo -e "\n${YELLOW}Step 6: Monitor the pipeline${NC}"
echo "Documents have been uploaded. The pipeline should:"
echo "1. Process each document"
echo "2. Auto-label them based on filename"
echo "3. Check if training threshold is met (3 documents)"
echo "4. Trigger the workflow to start training"
echo

echo "Monitoring Cloud Function logs..."
echo "Press Ctrl+C to stop monitoring"
echo

gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=50 --format="table(time,severity,message)"

echo -e "\n${BLUE}${BOLD}Next Steps:${NC}"
echo "1. Wait 2-3 minutes for documents to be processed"
echo "2. Run diagnostics to check status:"
echo "   python3 diagnose-training-issues.py"
echo
echo "3. Monitor function logs in real-time:"
echo "   gcloud functions logs read $FUNCTION_NAME --region=$REGION --follow"
echo
echo "4. Check workflow executions:"
echo "   gcloud workflows executions list --workflow=$WORKFLOW_NAME --location=$REGION"
echo
echo "5. If training doesn't trigger automatically, force it:"
echo "   python3 manual-trigger-training.py trigger-initial"
echo

echo -e "${GREEN}${BOLD}Training pipeline fix complete!${NC}"