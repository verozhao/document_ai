#!/bin/bash
# Fixed Automated Document AI Training Pipeline Deployment Script

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-tetrix-462721}"
PROCESSOR_ID="${DOCUMENT_AI_PROCESSOR_ID:-ddc065df69bfa3b5}"
DOCAI_LOCATION="us"
STORAGE_LOCATION="us"
CLOUD_LOCATION="us-central1"
FUNCTION_LOCATION="us-central1"  # Changed to match workflow location
BUCKET_NAME="${GCS_BUCKET_NAME:-document-ai-test-veronica}"
FUNCTION_NAME="document-ai-auto-trainer"
WORKFLOW_NAME="workflow-1-veronica"
SCHEDULER_JOB_NAME="document-ai-training-scheduler"
SERVICE_ACCOUNT="${FUNCTION_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    if [ -z "$PROJECT_ID" ]; then
        print_error "GCP_PROJECT_ID environment variable is not set"
        exit 1
    fi
    
    if [ -z "$PROCESSOR_ID" ]; then
        print_error "DOCUMENT_AI_PROCESSOR_ID environment variable is not set"
        exit 1
    fi
    
    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        print_error "gcloud CLI is not installed"
        exit 1
    fi
    
    # Check if required files exist
    if [ ! -f "main.py" ]; then
        print_error "main.py not found in current directory"
        exit 1
    fi
    
    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt not found in current directory"
        exit 1
    fi
    
    if [ ! -f "training-workflow.yaml" ]; then
        print_error "training-workflow.yaml not found in current directory"
        exit 1
    fi
    
    # Set project
    gcloud config set project $PROJECT_ID
    
    print_status "Prerequisites check completed"
}

# Enable required APIs
enable_apis() {
    print_status "Enabling required APIs..."
    
    APIs=(
        "documentai.googleapis.com"
        "storage.googleapis.com"
        "cloudfunctions.googleapis.com"
        "workflows.googleapis.com"
        "cloudscheduler.googleapis.com"
        "pubsub.googleapis.com"
        "firestore.googleapis.com"
        "cloudbuild.googleapis.com"
        "logging.googleapis.com"
        "eventarc.googleapis.com"
    )
    
    for api in "${APIs[@]}"; do
        gcloud services enable $api --quiet
    done
    
    print_status "APIs enabled successfully"
}

# Create service account for Cloud Function
create_service_account() {
    print_status "Creating service account for Cloud Function..."
    
    # Create service account
    if gcloud iam service-accounts describe $SERVICE_ACCOUNT &> /dev/null; then
        print_warning "Service account already exists"
    else
        gcloud iam service-accounts create $FUNCTION_NAME \
            --display-name="Document AI Auto Trainer Function"
        print_status "Created service account: $SERVICE_ACCOUNT"
    fi
    
    # Grant necessary roles
    ROLES=(
        "roles/documentai.editor"
        "roles/storage.objectViewer"
        "roles/datastore.user"
        "roles/workflows.invoker"
        "roles/logging.logWriter"
    )
    
    for role in "${ROLES[@]}"; do
        gcloud projects add-iam-policy-binding $PROJECT_ID \
            --member="serviceAccount:$SERVICE_ACCOUNT" \
            --role="$role" \
            --quiet
    done
    
    print_status "Service account configured with necessary permissions"
}

# Create GCS bucket
create_storage_bucket() {
    print_status "Creating GCS bucket..."
    
    if gsutil ls -b gs://$BUCKET_NAME &> /dev/null; then
        print_warning "Bucket $BUCKET_NAME already exists"
    else
        gsutil mb -p $PROJECT_ID -c STANDARD -l $STORAGE_LOCATION gs://$BUCKET_NAME
        print_status "Created bucket: gs://$BUCKET_NAME"
    fi
    
    # Create folder structure
    echo "Initializing bucket structure" | gsutil cp - gs://$BUCKET_NAME/documents/README.txt
    echo "Training outputs" | gsutil cp - gs://$BUCKET_NAME/training/README.txt
    echo "Processed documents" | gsutil cp - gs://$BUCKET_NAME/processed/README.txt
    echo "Failed documents" | gsutil cp - gs://$BUCKET_NAME/failed/README.txt
    
    # Grant service account access to bucket
    gsutil iam ch serviceAccount:$SERVICE_ACCOUNT:objectViewer gs://$BUCKET_NAME
}

# Create Pub/Sub topics
create_pubsub_topics() {
    print_status "Creating Pub/Sub topics..."
    
    # Training trigger topic
    if gcloud pubsub topics describe document-ai-training &> /dev/null; then
        print_warning "Topic document-ai-training already exists"
    else
        gcloud pubsub topics create document-ai-training
        print_status "Created topic: document-ai-training"
    fi
    
    # Notification topic
    if gcloud pubsub topics describe document-ai-notifications &> /dev/null; then
        print_warning "Topic document-ai-notifications already exists"
    else
        gcloud pubsub topics create document-ai-notifications
        print_status "Created topic: document-ai-notifications"
    fi
}

# Setup Firestore
setup_firestore() {
    print_status "Setting up Firestore..."
    
    # Create Firestore database if it doesn't exist
    if ! gcloud firestore databases list --format="value(name)" | grep -q "projects/$PROJECT_ID/databases/(default)"; then
        gcloud firestore databases create --location=$CLOUD_LOCATION --type=firestore-native
        print_status "Created Firestore database"
        
        # Wait for database to be ready
        sleep 10
    else
        print_warning "Firestore database already exists"
    fi
    
    # Initialize collections with test documents to ensure they exist
    print_status "Initializing Firestore collections..."
    
    # Create a temporary Python script to initialize collections
    cat > init_firestore.py << 'EOF'
import os
from google.cloud import firestore
from datetime import datetime, timezone

project_id = os.environ.get('GCP_PROJECT_ID')
processor_id = os.environ.get('DOCUMENT_AI_PROCESSOR_ID')

db = firestore.Client(project=project_id)

# Initialize training config
config_ref = db.collection('training_configs').document(processor_id)
config_ref.set({
    'processor_id': processor_id,
    'enabled': True,
    'min_documents_for_initial_training': 3,
    'min_documents_for_incremental': 2,
    'min_accuracy_for_deployment': 0.7,
    'check_interval_minutes': 60,
    'created_at': datetime.now(timezone.utc),
    'updated_at': datetime.now(timezone.utc)
}, merge=True)

print(f"Initialized training config for processor {processor_id}")
EOF

    # Run the initialization script
    python3 init_firestore.py
    rm init_firestore.py
    
    print_status "Firestore setup completed"
}

# Deploy Cloud Function
deploy_cloud_function() {
    print_status "Deploying Cloud Function..."
    
    # Create a deployment directory
    DEPLOY_DIR=$(mktemp -d)
    cp main.py $DEPLOY_DIR/
    cp requirements.txt $DEPLOY_DIR/
    
    # Deploy function
    gcloud functions deploy $FUNCTION_NAME \
        --runtime python39 \
        --trigger-resource $BUCKET_NAME \
        --trigger-event google.storage.object.finalize \
        --entry-point process_document_upload \
        --source $DEPLOY_DIR \
        --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,DOCUMENT_AI_PROCESSOR_ID=$PROCESSOR_ID,DOCUMENT_AI_LOCATION=$DOCAI_LOCATION,WORKFLOW_NAME=$WORKFLOW_NAME" \
        --memory 512MB \
        --timeout 540s \
        --region $FUNCTION_LOCATION \
        --service-account $SERVICE_ACCOUNT \
        --no-gen2
    
    # Clean up
    rm -rf $DEPLOY_DIR
    
    print_status "Cloud Function deployed successfully"
}

# Deploy Workflow
deploy_workflow() {
    print_status "Deploying Workflow..."
    
    PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
    WORKFLOW_SA="service-${PROJECT_NUMBER}@gcp-sa-workflows.iam.gserviceaccount.com"

    # Grant workflow service account necessary permissions
    WORKFLOW_ROLES=(
        "roles/documentai.editor"
        "roles/datastore.user"
        "roles/logging.logWriter"
        "roles/workflows.invoker"           # Ensure invoker role is present
        "roles/documentai.apiUser"          # Ensure Document AI API user role is present
    )
    
    for role in "${WORKFLOW_ROLES[@]}"; do
        gcloud projects add-iam-policy-binding $PROJECT_ID \
            --member="serviceAccount:$WORKFLOW_SA" \
            --role="$role" \
            --quiet
    done
    print_status "Workflow service account permissions updated."

    if [ -f "training-workflow.yaml" ]; then
        gcloud workflows deploy $WORKFLOW_NAME \
            --source=training-workflow.yaml \
            --location=$CLOUD_LOCATION \
            --service-account=$WORKFLOW_SA
        print_status "Workflow deployed successfully"
    else
        print_error "training-workflow.yaml not found"
        exit 1
    fi
}

# Create Cloud Scheduler job
create_scheduler_job() {
    print_status "Creating Cloud Scheduler job..."
    
    # First, ensure App Engine is initialized (required for Cloud Scheduler)
    if ! gcloud app describe &> /dev/null; then
        print_status "Initializing App Engine (required for Cloud Scheduler)..."
        gcloud app create --region=$CLOUD_LOCATION
    fi
    
    if gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$CLOUD_LOCATION &> /dev/null; then
        print_warning "Scheduler job $SCHEDULER_JOB_NAME already exists"
    else
        gcloud scheduler jobs create pubsub $SCHEDULER_JOB_NAME \
            --schedule="0 */6 * * *" \
            --topic=document-ai-training \
            --message-body="{\"action\":\"check_training\"}" \
            --location=$CLOUD_LOCATION
        print_status "Created scheduler job: $SCHEDULER_JOB_NAME"
    fi
}

# Test the deployment
test_deployment() {
    print_status "Testing deployment..."
    
    # Check Cloud Function
    print_status "Checking Cloud Function status..."
    gcloud functions describe $FUNCTION_NAME --region=$FUNCTION_LOCATION --format="table(name,status,entryPoint)"
    
    # Check Workflow
    print_status "Checking Workflow status..."
    gcloud workflows describe $WORKFLOW_NAME --location=$CLOUD_LOCATION --format="table(name,state)"
    
    # Check recent logs
    print_status "Checking recent Cloud Function logs (last 5 entries)..."
    gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_LOCATION --limit=5
}

# Main deployment process
main() {
    print_status "Starting deployment process..."
    
    check_prerequisites
    enable_apis
    create_service_account
    create_storage_bucket
    create_pubsub_topics
    setup_firestore
    deploy_cloud_function
    deploy_workflow
    create_scheduler_job
    test_deployment
    
    print_status "======================================"
    print_status "Deployment completed successfully!"
    print_status "======================================"
    print_status ""
    print_status "Next steps:"
    print_status "1. Upload PDF documents to: gs://$BUCKET_NAME/documents/"
    print_status "2. Monitor Cloud Function logs: gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_LOCATION --follow"
    print_status "3. Check Firestore for document records"
    print_status "4. Training will trigger automatically when threshold is met (3 documents for initial training)"
    print_status ""
    print_status "Useful commands:"
    print_status "- View function logs: gcloud functions logs read $FUNCTION_NAME --region=$FUNCTION_LOCATION --limit=50"
    print_status "- Test with a file: gsutil cp your-file.pdf gs://$BUCKET_NAME/documents/"
    print_status "- Check Firestore: https://console.cloud.google.com/firestore/data/processed_documents"
}

# Run main function
main