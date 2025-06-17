#!/bin/bash

# Automated Document AI Training Pipeline Deployment Script
# This script sets up the complete automated training pipeline

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-tetrix-462721}"
PROCESSOR_ID="${DOCUMENT_AI_PROCESSOR_ID:-ddc065df69bfa3b5}"
DOCAI_LOCATION="us"  # Location for Document AI processor
STORAGE_LOCATION="us"  # Location for Cloud Storage
CLOUD_LOCATION="us-central1"  # Location for Functions and Workflows
FUNCTION_LOCATION="us-east1"
BUCKET_NAME="${GCS_BUCKET_NAME:-document-ai-test-veronica}"
FUNCTION_NAME="document-ai-auto-trainer"
WORKFLOW_NAME="workflow-1-veronica"
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
    
    # Ensure requirements.txt exists with correct dependencies
    cat > requirements.txt << EOF
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
        --source . \
        --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,DOCUMENT_AI_PROCESSOR_ID=$PROCESSOR_ID,DOCUMENT_AI_LOCATION=$DOCAI_LOCATION,WORKFLOW_NAME=$WORKFLOW_NAME" \
        --memory 512MB \
        --timeout 540s \
        --region $FUNCTION_LOCATION \
        --no-gen2
    
    print_status "Cloud Function deployed successfully"
}

# Deploy Workflow
deploy_workflow() {
    print_status "Deploying Workflow..."
    
    if [ -f "training-workflow.yaml" ]; then
        gcloud workflows deploy $WORKFLOW_NAME \
            --source=training-workflow.yaml \
            --location=us-central1
        print_status "Workflow deployed successfully"
    else
        print_error "training-workflow.yaml not found"
        exit 1
    fi
}

# Create Cloud Scheduler job
create_scheduler_job() {
    print_status "Creating Cloud Scheduler job..."
    
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

# Main deployment process
main() {
    print_status "Starting deployment process..."
    
    check_prerequisites
    enable_apis
    create_storage_bucket
    create_pubsub_topics
    setup_firestore
    deploy_cloud_function
    deploy_workflow
    create_scheduler_job
    
    print_status "Deployment completed successfully!"
    print_status "Your Document AI training pipeline is now set up and ready to use."
    print_status "Upload PDF documents to gs://$BUCKET_NAME/documents/ to start processing."
}

# Run main function
main