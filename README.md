# Automated Document AI Training System

A fully automated system for Google Document AI processors that automatically processes documents uploaded to Google Cloud Storage, manages training data, triggers training when thresholds are met, and deploys new models without manual intervention.

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

## Key features

- GCS-triggered document processing and training
- Automatic initial and incremental training based on document thresholds
- Automatic model deployment and version management
- Live dashboard for system monitoring and health checks

1. **Initial Training**:
   - Collects documents until threshold is met
   - Triggers first model training
   - Deploys initial model

2. **Incremental Training**:
   - Processes new documents with current model
   - Triggers retraining when threshold reached
   - Deploys new version if accuracy improves

## Usage

1. Set up environment:
```bash
chmod +x setup_env.sh
source setup_env.sh
```

2. Deploy system:
```bash
curl -O https://raw.githubusercontent.com/document-ai/deployment-script.sh
chmod +x deployment-script.sh
./deployment-script.sh
```

3. Upload PDFs to the GCS bucket:
```bash
gsutil -m cp -r /Users/test/Downloads/test_documents_v2/* gs://document-ai-test-veronica/documents/
```

4. Configuration in Firestore
- `min_documents_for_initial_training`: 10 (default)
- `min_documents_for_incremental`: 5 (default)
- `min_accuracy_for_deployment`: 0.8 (default)
- `check_interval_minutes`: 360 (default)