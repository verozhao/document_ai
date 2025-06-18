#!/bin/bash
# Comprehensive validation script for Document AI training pipeline

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-tetrix-462721}"
PROCESSOR_ID="${DOCUMENT_AI_PROCESSOR_ID:-ddc065df69bfa3b5}"
BUCKET_NAME="${GCS_BUCKET_NAME:-document-ai-test-veronica}"
FUNCTION_NAME="document-ai-auto-trainer"
WORKFLOW_NAME="workflow-1-veronica"
FUNCTION_REGION="us-central1"
WORKFLOW_REGION="us-central1"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Document AI Training Pipeline Validation ===${NC}"
echo "Project: $PROJECT_ID"
echo "Processor: $PROCESSOR_ID"
echo "Bucket: $BUCKET_NAME"
echo

# Counter for issues
ISSUES=0

# Function to check status
check_status() {
    local name=$1
    local status=$2
    local message=$3
    
    if [ "$status" = "ok" ]; then
        echo -e "${GREEN}✓${NC} $name"
        if [ -n "$message" ]; then
            echo "  $message"
        fi
    elif [ "$status" = "warning" ]; then
        echo -e "${YELLOW}⚠${NC} $name"
        echo "  ${YELLOW}$message${NC}"
    else
        echo -e "${RED}✗${NC} $name"
        echo "  ${RED}$message${NC}"
        ((ISSUES++))
    fi
}

# 1. Check APIs
echo -e "\n${BLUE}1. Checking APIs...${NC}"
REQUIRED_APIS=(
    "documentai.googleapis.com"
    "storage.googleapis.com"
    "cloudfunctions.googleapis.com"
    "workflows.googleapis.com"
    "firestore.googleapis.com"
)

for api in "${REQUIRED_APIS[@]}"; do
    if gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q "$api"; then
        check_status "$api" "ok"
    else
        check_status "$api" "error" "API not enabled. Run: gcloud services enable $api"
    fi
done

# 2. Check Cloud Function
echo -e "\n${BLUE}2. Checking Cloud Function...${NC}"
if gcloud functions describe $FUNCTION_NAME --region=$FUNCTION_REGION &> /dev/null; then
    # Get function details
    FUNCTION_STATUS=$(gcloud functions describe $FUNCTION_NAME --region=$FUNCTION_REGION --format="value(status)")
    FUNCTION_TRIGGER=$(gcloud functions describe $FUNCTION_NAME --region=$FUNCTION_REGION --format="value(eventTrigger.eventType)")
    
    if [ "$FUNCTION_STATUS" = "ACTIVE" ]; then
        check_status "Function deployed" "ok" "Status: $FUNCTION_STATUS, Trigger: $FUNCTION_TRIGGER"
    else
        check_status "Function deployed" "warning" "Status: $FUNCTION_STATUS"
    fi
    
    # Check recent errors
    ERROR_COUNT=$(gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_REGION --limit=50 --format=json | jq '[.[] | select(.severity == "ERROR")] | length')
    if [ "$ERROR_COUNT" -gt 0 ]; then
        check_status "Function errors" "warning" "Found $ERROR_COUNT errors in recent logs"
        echo "  View errors: gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_REGION --filter='severity=ERROR'"
    else
        check_status "Function errors" "ok" "No recent errors"
    fi
else
    check_status "Function deployed" "error" "Function not found. Deploy with: ./deployment-script.sh"
fi

# 3. Check Workflow
echo -e "\n${BLUE}3. Checking Workflow...${NC}"
if gcloud workflows describe $WORKFLOW_NAME --location=$WORKFLOW_REGION &> /dev/null; then
    WORKFLOW_STATE=$(gcloud workflows describe $WORKFLOW_NAME --location=$WORKFLOW_REGION --format="value(state)")
    
    if [ "$WORKFLOW_STATE" = "ACTIVE" ]; then
        check_status "Workflow deployed" "ok" "State: $WORKFLOW_STATE"
        
        # Check recent executions
        EXEC_COUNT=$(gcloud workflows executions list $WORKFLOW_NAME --location=$WORKFLOW_REGION --limit=5 --format=json | jq length)
        if [ "$EXEC_COUNT" -eq 0 ]; then
            check_status "Workflow executions" "warning" "No executions found yet"
        else
            FAILED_COUNT=$(gcloud workflows executions list $WORKFLOW_NAME --location=$WORKFLOW_REGION --limit=10 --format=json | jq '[.[] | select(.state == "FAILED")] | length')
            if [ "$FAILED_COUNT" -gt 0 ]; then
                check_status "Workflow executions" "warning" "$FAILED_COUNT failed executions in last 10"
            else
                check_status "Workflow executions" "ok" "$EXEC_COUNT recent executions"
            fi
        fi
    else
        check_status "Workflow deployed" "error" "State: $WORKFLOW_STATE"
    fi
else
    check_status "Workflow deployed" "error" "Workflow not found. Deploy with: gcloud workflows deploy $WORKFLOW_NAME --source=training-workflow.yaml --location=$WORKFLOW_REGION"
fi

# 4. Check GCS Bucket
echo -e "\n${BLUE}4. Checking GCS Bucket...${NC}"
if gsutil ls -b gs://$BUCKET_NAME &> /dev/null; then
    check_status "Bucket exists" "ok" "gs://$BUCKET_NAME"
    
    # Check documents folder
    DOC_COUNT=$(gsutil ls gs://$BUCKET_NAME/documents/*.pdf 2>/dev/null | wc -l)
    if [ "$DOC_COUNT" -gt 0 ]; then
        check_status "Documents folder" "ok" "$DOC_COUNT PDF files found"
    else
        check_status "Documents folder" "warning" "No PDF files found in documents/"
    fi
else
    check_status "Bucket exists" "error" "Bucket not found. Create with: gsutil mb gs://$BUCKET_NAME"
fi

# 5. Check Firestore
echo -e "\n${BLUE}5. Checking Firestore...${NC}"
if gcloud firestore databases describe --database="(default)" &> /dev/null; then
    check_status "Firestore database" "ok" "Database exists"
    
    # Check training config using gcloud (not ideal but works)
    echo "  Checking training configuration..."
    # This would require the Firebase CLI or a small Python script
else
    check_status "Firestore database" "error" "Database not found. Create with: gcloud firestore databases create --location=us-central1"
fi

# 6. Check Document AI Processor
echo -e "\n${BLUE}6. Checking Document AI Processor...${NC}"
PROCESSOR_PATH="projects/$PROJECT_ID/locations/us/processors/$PROCESSOR_ID"
ACCESS_TOKEN=$(gcloud auth print-access-token)
if curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
    "https://documentai.googleapis.com/v1/$PROCESSOR_PATH" | grep -q "name"; then
    check_status "Processor exists" "ok" "Processor ID: $PROCESSOR_ID"
    
    # Check for versions (this is a simplified check)
    VERSION_COUNT=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
        "https://documentai.googleapis.com/v1/$PROCESSOR_PATH/processorVersions" | jq '.processorVersions | length')
    if [ "$VERSION_COUNT" -gt 0 ]; then
        check_status "Processor versions" "ok" "$VERSION_COUNT versions found"
    else
        check_status "Processor versions" "warning" "No trained versions - initial training needed"
    fi
else
    check_status "Processor exists" "error" "Processor not found. Check processor ID: $PROCESSOR_ID"
fi

# 7. Test document upload
echo -e "\n${BLUE}7. Testing Document Upload...${NC}"
echo "Creating test document..."
cat > test_financial_statement.txt << EOF
FINANCIAL STATEMENT
Company: Test Corporation
Date: $(date +%Y-%m-%d)

Balance Sheet
Assets: \$1,000,000
Liabilities: \$500,000
Equity: \$500,000

This is a test document for the automated training pipeline.
EOF

# Convert to PDF using Python if available
if command -v python3 &> /dev/null && python3 -c "import reportlab" 2>/dev/null; then
    python3 << EOF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
c = canvas.Canvas("test_document.pdf", pagesize=letter)
with open("test_financial_statement.txt", "r") as f:
    y = 750
    for line in f:
        c.drawString(100, y, line.strip())
        y -= 20
c.save()
print("Created test_document.pdf")
EOF
    
    # Upload the test document
    echo "Uploading test document..."
    gsutil cp test_document.pdf gs://$BUCKET_NAME/documents/test_document_$(date +%s).pdf
    check_status "Test upload" "ok" "Document uploaded successfully"
    rm test_document.pdf test_financial_statement.txt
else
    check_status "Test upload" "warning" "Python/reportlab not available. Upload PDFs manually to gs://$BUCKET_NAME/documents/"
    rm test_financial_statement.txt
fi

# Summary
echo -e "\n${BLUE}=== Validation Summary ===${NC}"
if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${NC} Your pipeline should be working."
    echo
    echo "Next steps:"
    echo "1. Upload PDFs to gs://$BUCKET_NAME/documents/"
    echo "2. Monitor function logs: gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_REGION --follow"
    echo "3. Check Firestore console for document records"
else
    echo -e "${RED}Found $ISSUES issues that need attention.${NC}"
    echo
    echo "Fix the issues above and run this script again."
fi

# Show useful commands
echo -e "\n${BLUE}Useful Commands:${NC}"
echo "View function logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_REGION --limit=50"
echo
echo "View function errors only:"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_REGION --filter='severity=ERROR' --limit=20"
echo
echo "Describe function:"
echo "  gcloud functions describe $FUNCTION_NAME --region=$FUNCTION_REGION"
echo
echo "List workflow executions:"
echo "  gcloud workflows executions list --workflow=$WORKFLOW_NAME --location=$WORKFLOW_REGION"
echo
echo "Manually trigger workflow (for testing):"
echo "  gcloud workflows execute $WORKFLOW_NAME --location=$WORKFLOW_REGION \\"
echo "    --data='{\"processor_id\":\"$PROCESSOR_ID\",\"training_type\":\"initial\"}'"