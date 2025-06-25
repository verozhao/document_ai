# Document AI Complete Automation System

**Complete end-to-end automation: Creation → Deployment → Local Doc → GCS → Cloud Function → Firestore → Workflow → Document AI Processor → Update Firestore → Scheduler**

This system provides **zero-manual-intervention** Document AI automation with complete infrastructure deployment and continuous operation monitoring.

## 🎯 Complete System Architecture

```
Local Documents → GCS Upload → Cloud Function Trigger → Firestore Tracking → 
Cloud Workflow Orchestration → Document AI Processing → Training → 
Firestore Updates → Scheduler Monitoring → Continuous Retraining
```

## 🚀 Complete Infrastructure Components

### **1. Cloud Infrastructure**
- **Cloud Functions** (`cloud_function_main.py`) - GCS upload triggers
- **Cloud Workflows** (`automation_workflow.yaml`) - Single comprehensive training orchestration
- **Firestore** (`firestore.indexes.json`) - Document tracking and state management
- **Cloud Scheduler** - Periodic training checks every 6 hours
- **Pub/Sub** - Event-driven communication between components

### **2. Document Processing Pipeline**
- **OCR Processing** (`2369784b09e9d56a`) - Text extraction from PDFs
- **Auto-labeling** - Based on folder structure and content analysis
- **Classification Training** (`ddc065df69bfa3b5`) - Custom model training
- **Continuous Learning** - Automatic retraining with new documents

### **3. Monitoring & Management**
- **Real-time Status** - Firestore document tracking
- **Operation Monitoring** - Training and import progress tracking
- **Health Checks** - Automated system validation
- **Error Handling** - Automatic retry and failure notifications

## 🎬 Quick Start - Complete Deployment

### **Phase 1: Infrastructure Setup**

1. **Prerequisites**
```bash
# Authenticate
gcloud auth login
gcloud auth application-default login
gcloud config set project tetrix-462721
gcloud auth application-default set-quota-project tetrix-462721

# Install dependencies
pip install -r requirements.txt
```

2. **Deploy Complete Infrastructure**
```bash
# Deploy all components: Cloud Functions, Workflows, Firestore, Scheduler
chmod +x deploy.sh
./deploy.sh
```

**What gets deployed:**
- ✅ Cloud Function for GCS triggers
- ✅ Cloud Workflows for training orchestration
- ✅ Firestore with proper indexes
- ✅ Cloud Scheduler for periodic checks
- ✅ Pub/Sub topics for messaging
- ✅ IAM roles and permissions
- ✅ API enablement

### **Phase 2: Document Processing**

3. **Organize Documents**
```
/Users/test/Downloads/test_documents_v2/
├── capital_call/
│   ├── document1.pdf
│   └── document2.pdf
├── financial_statement/
│   ├── statement1.pdf
│   └── statement2.pdf
└── distribution_notice/
    ├── notice1.pdf
    └── notice2.pdf
```

4. **Upload and Watch Automation**
```bash
# Upload documents - automation takes over completely
gsutil -m cp -r /Users/test/Downloads/test_documents_v2/* gs://document-ai-test-veronica/documents/
```

**Automatic Flow After Upload:**
1. 🔄 Cloud Function triggered on GCS upload
2. 📝 Document auto-labeled based on folder name
3. 💾 Metadata stored in Firestore
4. 🎯 Training threshold checked
5. ⚡ Cloud Workflow triggered if threshold met
6. 🤖 Documents processed and imported
7. 🎓 Training started automatically
8. 📊 Firestore updated with results

### **Phase 3: Continuous Operation**

5. **Add New Documents (Triggers Retraining)**
```bash
# Any new uploads automatically trigger retraining
gsutil cp new_document.pdf gs://document-ai-test-veronica/documents/capital_call/
```

6. **Monitor Operations**
```bash
# Check system status
python -c "
from document_ai.utils import monitor_operation
# Monitor specific operation
monitor_operation('projects/969504446715/locations/us/operations/12345', 'training')
"
```

## 📊 Complete System Flow

### **1. Document Upload Trigger**
```
PDF Upload → GCS Event → Cloud Function → Auto-labeling → Firestore Storage
```

### **2. Training Threshold Logic**
```python
# Automatic threshold checking (in Cloud Function)
if pending_documents >= 3:  # Initial training
    trigger_workflow('initial')
elif new_documents >= 2:   # Incremental training
    trigger_workflow('incremental')
```

### **3. Cloud Workflow Orchestration**
```yaml
# automation_workflow.yaml - Single comprehensive workflow
- import_documents:
    call: googleapis.documentai.v1beta3.importDocuments
    args:
      autoSplitConfig:
        trainingSplitRatio: 0.8

- start_training:
    call: googleapis.documentai.v1.train
    
- update_firestore:
    call: googleapis.firestore.v1.patch
    # Updates training status in real-time
```

### **4. Continuous Monitoring**
```
Cloud Scheduler (6h) → Check Firestore → Trigger Training → Update Status
```

## 🏗️ Complete File Structure

```
document_ai/
├── README.md                          # This documentation
├── requirements.txt                   # Python dependencies
│
├── 🚀 COMPLETE AUTOMATION SYSTEM
├── deploy.sh                          # Complete infrastructure deployment
├── cloud_function_main.py             # GCS-triggered Cloud Function
├── automation_workflow.yaml           # Single comprehensive workflow
├── firestore.indexes.json             # Firestore configuration
├── config_env.sh                      # Environment configuration
├── validate-setup.sh                  # System validation
│
├── 📦 CORE MODULES (No Duplication)
├── document_ai/                       # Unified utilities package
│   ├── __init__.py
│   ├── utils.py                       # Consolidated common functions
│   ├── api.py                         # Document AI API wrapper
│   ├── client.py                      # Enhanced client utilities
│   ├── incremental_training.py        # AutomatedTrainingManager
│   └── models.py                      # Data models and types
│
└── ⚡ PIPELINE SCRIPTS (Manual Mode)
    ├── document_pipeline.py           # Complete organized pipeline
    ├── import_and_train.py            # Direct import/training
    ├── auto_labeling.py               # Document auto-labeling
    └── manual_pipeline.py             # Alternative manual approach
```

## 📋 Configuration

### **Pre-configured Settings**
- **Project ID**: `tetrix-462721`
- **OCR Processor**: `2369784b09e9d56a` (text extraction)
- **Classifier Processor**: `ddc065df69bfa3b5` (training)
- **GCS Bucket**: `document-ai-test-veronica`
- **Location**: `us`

### **Firestore Collections**
```javascript
// processed_documents - Track all document processing
{
  document_id: "doc_12345",
  gcs_uri: "gs://bucket/documents/capital_call/doc1.pdf",
  document_label: "capital_call",
  status: "completed",
  used_for_training: false,
  created_at: timestamp
}

// training_batches - Monitor training operations
{
  processor_id: "ddc065df69bfa3b5",
  operation_id: "projects/.../operations/12345",
  status: "training",
  started_at: timestamp
}

// training_configs - Automation settings
{
  enabled: true,
  min_documents_for_initial_training: 3,
  min_documents_for_incremental: 2,
  check_interval_minutes: 360
}
```

### **Cloud Scheduler Jobs**
```bash
# Periodic training checks
JOB_NAME="document-ai-training-scheduler"
SCHEDULE="0 */6 * * *"  # Every 6 hours
```

## 🔍 Monitoring & Verification

### **Real-time Monitoring**
```bash
# Cloud Function logs
gcloud functions logs read document-ai-service --project=tetrix-462721

# Workflow executions
gcloud workflows executions list --workflow=automation-workflow --location=us-central1 --project=tetrix-462721

# Firestore data
gcloud firestore collections list --project=tetrix-462721
```

### **Console Links**
- **Processor**: https://console.cloud.google.com/ai/document-ai/processors/details/ddc065df69bfa3b5?project=tetrix-462721
- **Cloud Functions**: https://console.cloud.google.com/functions/list?project=tetrix-462721
- **Workflows**: https://console.cloud.google.com/workflows?project=tetrix-462721
- **Firestore**: https://console.cloud.google.com/firestore?project=tetrix-462721
- **Scheduler**: https://console.cloud.google.com/cloudscheduler?project=tetrix-462721
- **Operations**: https://console.cloud.google.com/ai/operations?project=tetrix-462721

### **Health Check Commands**
```bash
# Validate complete system
./validate-setup.sh

# Check processor status
gcloud ai document-ai processors describe ddc065df69bfa3b5 --location=us --project=tetrix-462721

# Check recent operations
gcloud ai operations list --project=tetrix-462721 --limit=5

# Check Firestore collections
gcloud firestore collections list --project=tetrix-462721
```

## 🎯 Success Verification

After deployment and document upload, verify complete automation:

### **1. Cloud Function Triggered**
```bash
# Check function logs for document processing
gcloud functions logs read document-ai-service --limit=10 --project=tetrix-462721
```

### **2. Firestore Updated**
```bash
# Verify documents tracked in Firestore
gcloud firestore collections documents list processed_documents --limit=5 --project=tetrix-462721
```

### **3. Training Started**
```bash
# Check for training operations
gcloud ai operations list --filter="metadata.type:TRAIN_PROCESSOR_VERSION" --project=tetrix-462721
```

### **4. Processor Updated**
```bash
# Verify new processor version
gcloud ai document-ai processor-versions list --processor=ddc065df69bfa3b5 --location=us --project=tetrix-462721
```

## 🔄 Continuous Operation

### **Automatic Retraining**
- **Upload trigger**: Any new PDF upload automatically triggers retraining
- **Threshold-based**: Trains when 2+ new documents available
- **Scheduled checks**: Every 6 hours via Cloud Scheduler
- **Error handling**: Automatic retries and failure notifications

### **Manual Override**
```bash
# Force manual training
python working_import_and_train.py

# Manual pipeline execution
python document_pipeline.py --local-folder /path/to/documents
```

## 🚨 Troubleshooting

### **Cloud Function Issues**
```bash
# Check function status
gcloud functions describe document-ai-service --region=us-central1 --project=tetrix-462721

# View detailed logs
gcloud functions logs read document-ai-service --project=tetrix-462721
```

### **Workflow Issues**
```bash
# Check workflow status
gcloud workflows describe automation-workflow --location=us-central1 --project=tetrix-462721

# View execution history
gcloud workflows executions list --workflow=automation-workflow --location=us-central1 --project=tetrix-462721
```

### **Firestore Issues**
```bash
# Verify indexes
gcloud firestore indexes list --project=tetrix-462721

# Check collection data
gcloud firestore collections documents list processed_documents --project=tetrix-462721
```

## 🔧 Technical Implementation

### **Event-Driven Architecture**
- **GCS Events** → Cloud Function → Firestore → Workflow
- **Pub/Sub Messaging** for component communication
- **Automatic scaling** based on document volume

### **State Management**
- **Firestore** for persistent state tracking
- **Operation monitoring** for long-running processes
- **Error recovery** with automatic retries

### **Security & Permissions**
- **Service accounts** with minimal required permissions
- **IAM roles** properly configured for each component
- **Secure API** access with proper authentication

This system provides **complete automation** from document upload to trained model deployment with **zero manual intervention** required for ongoing operation.