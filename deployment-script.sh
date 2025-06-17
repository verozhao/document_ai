#!/bin/bash

# Automated Document AI Training Pipeline Deployment Script
# This script sets up the complete automated training pipeline

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-}"
PROCESSOR_ID="${DOCUMENT_AI_PROCESSOR_ID:-}"
DOCAI_LOCATION="us"  # Document AI processor location
STORAGE_LOCATION="us"  # Cloud Storage location (multi-region)
CLOUD_LOCATION="us-central1"  # Location for other cloud services (Functions, Workflows, etc.)
FUNCTION_LOCATION="us-east1"  # Cloud Function location (closest to us multi-region)
BUCKET_NAME="${GCS_BUCKET_NAME:-${PROJECT_ID}-document-ai}"
FUNCTION_NAME="document-ai-auto-trainer"
WORKFLOW_NAME="document-ai-training-workflow"
SCHEDULER_JOB_NAME="document-ai-training-scheduler"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Function to print colored output
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
    
    # Check if jq is installed
    if ! command -v jq &> /dev/null; then
        print_error "jq is not installed. Please install it first: brew install jq"
        exit 1
    fi
    
    # Set project
    gcloud config set project $PROJECT_ID
    
    print_status "Prerequisites check completed"
}

# Enable required APIs
enable_apis() {
    print_status "Enabling required APIs..."
    
    gcloud services enable documentai.googleapis.com
    gcloud services enable storage.googleapis.com
    gcloud services enable cloudfunctions.googleapis.com
    gcloud services enable workflows.googleapis.com
    gcloud services enable cloudscheduler.googleapis.com
    gcloud services enable pubsub.googleapis.com
    gcloud services enable firestore.googleapis.com
    gcloud services enable cloudbuild.googleapis.com
    
    print_status "APIs enabled successfully"
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

# Create Firestore database
setup_firestore() {
    print_status "Setting up Firestore..."
    
    # Create Firestore database if it doesn't exist
    if ! gcloud firestore databases list --format="value(name)" | grep -q "projects/$PROJECT_ID/databases/(default)"; then
        gcloud firestore databases create --location=$CLOUD_LOCATION
        print_status "Created Firestore database"
    else
        print_warning "Firestore database already exists"
    fi
    
    # Create composite indexes for processed_documents
    print_status "Creating Firestore indexes..."
    
    # Function to create index with error handling
    create_index() {
        local collection=$1
        shift
        local fields=("$@")
        local field_configs=""
        for field in "${fields[@]}"; do
            field_configs="$field_configs --field-config field-path=$field,order=ASCENDING"
        done
        
        if gcloud firestore indexes composite create \
            --collection-group=$collection \
            --query-scope=COLLECTION \
            $field_configs 2>/dev/null; then
            print_status "Created index for $collection on ${fields[*]}"
        else
            print_warning "Index for $collection on ${fields[*]} already exists"
        fi
    }
    
    # Create indexes
    create_index "processed_documents" "processor_id" "status" "created_at"
    create_index "processed_documents" "processor_id" "used_for_training"
    create_index "training_configs" "processor_id" "enabled"
    
    print_status "Firestore setup completed"
}

# Deploy Cloud Function
deploy_cloud_function() {
    print_status "Deploying Cloud Function..."
    
    # Create function directory
    mkdir -p cloud-function
    
    # Do not overwrite main.py; assume user has already provided the correct code
    # cat > cloud-function/main.py << 'EOF'
    # # Insert the cloud function code here (from gcs-trigger-function artifact)
    # EOF
    
    # Create requirements.txt
    cat > cloud-function/requirements.txt << EOF
google-cloud-documentai==2.20.0
google-cloud-firestore==2.13.1
google-cloud-workflows==1.12.1
google-cloud-storage==2.10.0
EOF
    
    # Deploy function
    gcloud functions deploy $FUNCTION_NAME \
        --runtime python39 \
        --trigger-resource $BUCKET_NAME \
        --trigger-event google.storage.object.finalize \
        --entry-point process_document_upload \
        --source cloud-function \
        --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,DOCUMENT_AI_PROCESSOR_ID=$PROCESSOR_ID,DOCUMENT_AI_LOCATION=$DOCAI_LOCATION,WORKFLOW_NAME=$WORKFLOW_NAME" \
        --memory 512MB \
        --timeout 540s \
        --region $FUNCTION_LOCATION \
        --no-gen2
    
    # Clean up
    rm -rf cloud-function
    
    print_status "Cloud Function deployed successfully"
}

# Deploy Cloud Workflow
deploy_workflow() {
    print_status "Deploying Cloud Workflow..."
    
    gcloud workflows deploy $WORKFLOW_NAME \
        --location=$CLOUD_LOCATION \
        --source=training-workflow.yaml \
        --service-account="${PROJECT_ID}@appspot.gserviceaccount.com"
    
    print_status "Cloud Workflow deployed successfully"
}

# Create Cloud Scheduler job for periodic checks
create_scheduler_job() {
    print_status "Creating Cloud Scheduler job..."
    
    # Create App Engine app if it doesn't exist (required for Cloud Scheduler)
    if ! gcloud app describe &> /dev/null; then
        print_status "Creating App Engine app..."
        gcloud app create --region=$CLOUD_LOCATION
    fi
    
    # Create or update scheduler job
    if gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$CLOUD_LOCATION &> /dev/null; then
        gcloud scheduler jobs delete $SCHEDULER_JOB_NAME --location=$CLOUD_LOCATION --quiet
    fi
    
    gcloud scheduler jobs create pubsub $SCHEDULER_JOB_NAME \
        --location=$CLOUD_LOCATION \
        --schedule="0 */6 * * *" \
        --topic=document-ai-training \
        --message-body='{"action":"periodic_check","processor_id":"'$PROCESSOR_ID'"}' \
        --time-zone="UTC"
    
    print_status "Cloud Scheduler job created"
}

# Set up IAM permissions
setup_iam_permissions() {
    print_status "Setting up IAM permissions..."
    
    # Get the default service account
    SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"
    
    # Grant necessary roles
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/documentai.editor"
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/storage.admin"
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/datastore.user"
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/workflows.invoker"
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/pubsub.publisher"
    
    print_status "IAM permissions configured"
}

# Create initial training configuration
create_initial_config() {
    print_status "Creating initial training configuration..."
    
    # Create a Python script to initialize Firestore config
    cat > init_config.py << EOF
from google.cloud import firestore
import os

db = firestore.Client(project=os.environ['PROJECT_ID'])

# Create default training configuration
config_ref = db.collection('training_configs').document(os.environ['PROCESSOR_ID'])
config_ref.set({
    'enabled': True,
    'min_documents_for_initial_training': 10,
    'min_documents_for_incremental': 5,
    'min_accuracy_for_deployment': 0.8,
    'check_interval_minutes': 360,
    'created_at': firestore.SERVER_TIMESTAMP
})

print("Initial configuration created")
EOF
    
    PROJECT_ID=$PROJECT_ID PROCESSOR_ID=$PROCESSOR_ID python3 init_config.py
    rm init_config.py
    
    print_status "Initial configuration created"
}

# Main deployment function
main() {
    print_status "Starting Document AI Automated Training Pipeline deployment..."
    
    check_prerequisites
    enable_apis
    create_storage_bucket
    create_pubsub_topics
    setup_firestore
    deploy_cloud_function
    deploy_workflow
    create_scheduler_job
    setup_iam_permissions
    create_initial_config
    
    print_status "=========================================="
    print_status "Deployment completed successfully!"
    print_status "=========================================="
    print_status ""
    print_status "Next steps:"
    print_status "1. Upload PDF documents to: gs://$BUCKET_NAME/documents/"
    print_status "2. Documents will be automatically processed and used for training"
    print_status "3. Training will trigger automatically when thresholds are met"
    print_status "4. Monitor progress in Cloud Console:"
    print_status "   - Cloud Functions: https://console.cloud.google.com/functions"
    print_status "   - Workflows: https://console.cloud.google.com/workflows"
    print_status "   - Firestore: https://console.cloud.google.com/firestore"
    print_status ""
    print_status "To upload documents:"
    print_status "  gsutil cp your-document.pdf gs://$BUCKET_NAME/documents/"
    print_status ""
}

# Run main function
main