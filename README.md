# Automated Document AI Incremental Training System

## Overview

This system provides **fully automated incremental training** for Google Document AI processors. When new documents are uploaded to Google Cloud Storage, the system automatically:

1. **Processes** documents using the current model (if available)
2. **Stores** documents for training
3. **Triggers** training automatically when thresholds are met
4. **Deploys** new models without manual intervention
5. **Monitors** the entire pipeline in real-time

**No manual training required** - everything is event-driven and automated!

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   GCS Bucket    │────▶│  Cloud Function  │────▶│  Cloud Workflow │
│  (Documents)    │     │  (Trigger)       │     │  (Training)     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                          │
                               ▼                          ▼
                        ┌─────────────┐           ┌──────────────┐
                        │  Firestore  │           │ Document AI  │
                        │  (State)    │           │ (Training)   │
                        └─────────────┘           └──────────────┘
```

## Key Features

### 🚀 Fully Automated Training
- **GCS-triggered processing**: Documents uploaded to GCS automatically trigger processing
- **Threshold-based training**: Training starts automatically when document thresholds are met
- **No manual API calls**: Everything happens through event-driven architecture

### 📊 Intelligent Document Management
- **Initial training**: Automatically trains the first model when enough documents are collected
- **Incremental training**: Retrains with new documents to improve accuracy
- **Document tracking**: Tracks which documents have been used for training

### 🔄 Continuous Improvement
- **Automatic deployment**: Deploys new models when accuracy thresholds are met
- **Version management**: Maintains processor versions automatically
- **Rollback capability**: Previous versions remain available if needed

### 📈 Real-time Monitoring
- **Live dashboard**: Monitor training progress in real-time
- **Health checks**: System component health monitoring
- **Activity logs**: Track all system activities

## Quick Start

### Environment Setup

```bash
chmod +x setup_env.sh
source setup_env.sh
```

### One-Command Deployment

```bash
curl -O https://raw.githubusercontent.com/document-ai/deployment-script.sh
chmod +x deployment-script.sh
./deployment-script.sh
```

This single command will:
- Enable all required APIs
- Create GCS bucket with proper structure
- Set up Pub/Sub topics
- Initialize Firestore database
- Deploy Cloud Function for GCS triggers
- Deploy Cloud Workflow for training orchestration
- Configure Cloud Scheduler for periodic checks
- Set up all IAM permissions
- Create initial configuration

## Usage

### Uploading Documents

Once deployed, simply upload PDFs to the GCS bucket:

```bash
# Upload a single document
gsutil cp invoice.pdf gs://${GCS_BUCKET_NAME}/documents/

# Upload multiple documents
gsutil -m cp *.pdf gs://${GCS_BUCKET_NAME}/documents/
```

**That's it!** The system will:
1. Detect the new document
2. Process it if a model exists
3. Store it for training if no model exists
4. Trigger training when thresholds are met

### Monitoring

Run the real-time monitoring dashboard:

```bash
python monitoring_dashboard.py
```

The dashboard shows:
- Processor status and versions
- Document processing statistics
- Training progress and history
- System health status
- Recent activity logs

### Configuration

The system uses sensible defaults, but you can customize via Firestore:

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Enable/disable automated training |
| `min_documents_for_initial_training` | `10` | Documents needed for first training |
| `min_documents_for_incremental` | `5` | Documents needed for retraining |
| `min_accuracy_for_deployment` | `0.8` | Minimum accuracy to deploy model |
| `check_interval_minutes` | `360` | Periodic check interval |

## How It Works

### Initial Training Flow

1. **No Model State**: When no trained model exists
2. **Document Collection**: Uploads are stored as `pending_initial_training`
3. **Threshold Check**: System monitors document count
4. **Automatic Training**: Triggers when threshold (default: 10) is reached
5. **Model Deployment**: Deploys the first model automatically

### Incremental Training Flow

1. **Document Processing**: New documents are processed with current model
2. **Training Pool**: Processed documents marked as `unused_for_training`
3. **Threshold Check**: Monitors unused document count
4. **Incremental Training**: Triggers when threshold (default: 5) is reached
5. **Model Update**: New version deployed if accuracy improves

### Training Process

1. **Batch Creation**: Groups documents by type for balanced training
2. **Schema Generation**: Creates document schema based on types
3. **Training Execution**: Submits training job to Document AI
4. **Progress Monitoring**: Tracks training operation status
5. **Deployment Decision**: Deploys if accuracy meets threshold
6. **Document Marking**: Marks documents as used for training

## Advanced Features

### Document Types

The system automatically handles various document types:
- Capital Calls
- Distribution Notices
- Financial Statements
- Investment Overviews
- Portfolio Summaries
- Tax Documents
- And more...

### Custom Processing

You can extend the Cloud Function to add custom logic:

```python
# In the Cloud Function
def custom_preprocessing(document_content):
    # Add your custom logic
    return processed_content

# Before processing
content = custom_preprocessing(content)
```

### Notification Integration

The system publishes events to Pub/Sub topics:
- `document-ai-training`: Training triggers
- `document-ai-notifications`: Status updates

Subscribe to these topics for custom integrations.

## Troubleshooting

### Common Issues

1. **Documents not processing**
   - Check Cloud Function logs
   - Verify GCS permissions
   - Ensure documents are in `/documents/` folder

2. **Training not triggering**
   - Check document count in Firestore
   - Verify training configuration
   - Look for active training batches

3. **Deployment failures**
   - Check accuracy threshold
   - Verify Document AI quotas
   - Review workflow execution logs

### Debugging Commands

```bash
# Check Cloud Function logs
gcloud functions logs read document-ai-auto-trainer --limit 50

# View Workflow executions
gcloud workflows executions list --workflow=document-ai-training-workflow

# Check Firestore data
gcloud firestore documents list --collection-path=processed_documents --limit=10

# View Document AI processor
gcloud ai document-processors describe $DOCUMENT_AI_PROCESSOR_ID --location=$LOCATION
```

## Cost Optimization

### Storage
- Documents are stored in Standard storage class
- Consider lifecycle policies for old documents
- Training outputs can be moved to Coldline

### Processing
- Cloud Function runs only on document upload
- Workflow executes only during training
- Scheduler runs periodically (configurable)

### Best Practices
1. Batch document uploads when possible
2. Set appropriate training thresholds
3. Monitor and adjust accuracy thresholds
4. Clean up old processor versions

## Security Considerations

### IAM Roles
The system uses least-privilege principles:
- Cloud Function: `documentai.editor`, `storage.admin`
- Workflow: `documentai.admin`, `firestore.user`
- Service Account: Limited to required resources

### Data Protection
- Documents remain in your GCS bucket
- Firestore stores only metadata
- No data leaves your project

### Audit Logging
- All operations are logged
- Cloud Audit Logs track access
- Monitoring dashboard shows activity

## Extending the System

### Adding New Document Types

1. Update the `DocumentType` enum in your models
2. Add schema properties in the training manager
3. Update classification logic if needed

### Custom Workflows

Create additional workflows for:
- Model evaluation
- A/B testing
- Custom notifications
- Data export

### Integration Points

- **Pre-processing**: Add custom logic before Document AI
- **Post-processing**: Extract and store specific fields
- **Notifications**: Send alerts on training completion
- **Analytics**: Track accuracy improvements over time

## Support and Resources

- [Document AI Documentation](https://cloud.google.com/document-ai/docs)
- [Cloud Functions Guide](https://cloud.google.com/functions/docs)
- [Cloud Workflows Reference](https://cloud.google.com/workflows/docs)
- [Firestore Best Practices](https://cloud.google.com/firestore/docs/best-practices)

## Conclusion

This automated training system eliminates manual intervention in Document AI model improvement. Simply upload documents and let the system handle:

✅ Processing  
✅ Training  
✅ Deployment  
✅ Monitoring  

The result is a continuously improving document processing pipeline that gets more accurate with every document!