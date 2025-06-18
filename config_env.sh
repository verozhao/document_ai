# Required environment variables
export GCP_PROJECT_ID="tetrix-462721"
export DOCUMENT_AI_PROCESSOR_ID="ddc065df69bfa3b5"
export GOOGLE_APPLICATION_CREDENTIALS="/Users/test/Downloads/tetrix-462721-71bf62848ec2.json"
export PDF_DIRECTORY="/Users/test/Downloads/test_documents"
export GCS_BUCKET_NAME="document-ai-test-veronica"

# Workflow configuration
export LOCATION='us'
export WORKFLOW_NAME='workflow-1-veronica'
export WORKFLOW_LOCATION='us-central1'
export FIRESTORE_COLLECTION='processed_documents'

# Function configuration  
export FUNCTION_NAME='document-ai-auto-trainer'
export FUNCTION_REGION='us-central1'

# Training configuration
export MIN_DOCUMENTS_INITIAL=3
export MIN_DOCUMENTS_INCREMENTAL=2
export MIN_ACCURACY_DEPLOYMENT=0.7

# Validation function
validate_env() {
    echo "=== Environment Validation ==="
    echo "GCP_PROJECT_ID: $GCP_PROJECT_ID"
    echo "PROCESSOR_ID: $DOCUMENT_AI_PROCESSOR_ID"
    echo "BUCKET: $GCS_BUCKET_NAME"
    echo "WORKFLOW: $WORKFLOW_NAME"
    echo "WORKFLOW_LOCATION: $WORKFLOW_LOCATION"
    
    # Check if all required vars are set
    local missing=()
    [[ -z "$GCP_PROJECT_ID" ]] && missing+=("GCP_PROJECT_ID")
    [[ -z "$DOCUMENT_AI_PROCESSOR_ID" ]] && missing+=("DOCUMENT_AI_PROCESSOR_ID")
    [[ -z "$GCS_BUCKET_NAME" ]] && missing+=("GCS_BUCKET_NAME")
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "Missing variables: ${missing[*]}"
        return 1
    else
        echo "All required variables set"
        return 0
    fi
}

# Auto-validate when sourced
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    validate_env
fi

echo "Environment configured. Run 'validate_env' to check."