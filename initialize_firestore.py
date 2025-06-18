"""Initialize Firestore collections and configuration for Document AI training."""

import os
from datetime import datetime, timezone
from google.cloud import firestore


def initialize_processor_config(project_id: str, processor_id: str):
    """Initialize training configuration for a processor."""
    try:
        db = firestore.Client(project=project_id)
        
        # Create default training configuration
        config_ref = db.collection('training_configs').document(processor_id)
        
        # Check if config already exists
        if config_ref.get().exists:
            print(f"Training config already exists for processor {processor_id}")
            return
        
        default_config = {
            'processor_id': processor_id,
            'enabled': True,
            'min_documents_for_initial_training': int(os.environ.get('MIN_DOCUMENTS_INITIAL', 3)),
            'min_documents_for_incremental': int(os.environ.get('MIN_DOCUMENTS_INCREMENTAL', 2)),
            'min_accuracy_for_deployment': float(os.environ.get('MIN_ACCURACY_DEPLOYMENT', 0.7)),
            'check_interval_minutes': 60,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc)
        }
        
        config_ref.set(default_config)
        print(f"Initialized training config for processor {processor_id}")
        
        # Create initial indexes by adding placeholder documents
        _create_firestore_indexes(db, processor_id)
        
    except Exception as e:
        print(f"Error initializing Firestore configuration: {e}")
        raise


def _create_firestore_indexes(db: firestore.Client, processor_id: str):
    """Create Firestore indexes by adding placeholder documents."""
    try:
        # Add placeholder processed document to ensure collection exists
        placeholder_doc = {
            'document_id': 'placeholder',
            'processor_id': processor_id,
            'status': 'placeholder',
            'document_label': 'PLACEHOLDER',
            'used_for_training': False,
            'created_at': datetime.now(timezone.utc)
        }
        
        doc_ref = db.collection('processed_documents').document('placeholder')
        doc_ref.set(placeholder_doc)
        
        # Add placeholder training batch
        batch_placeholder = {
            'batch_id': 'placeholder',
            'processor_id': processor_id,
            'status': 'placeholder',
            'started_at': datetime.now(timezone.utc)
        }
        
        batch_ref = db.collection('training_batches').document('placeholder')
        batch_ref.set(batch_placeholder)
        
        print("Created placeholder documents for indexing")
        
        # Clean up placeholders
        doc_ref.delete()
        batch_ref.delete()
        
        print("Cleaned up placeholder documents")
        
    except Exception as e:
        print(f"Warning: Could not create indexes: {e}")
        # Non-fatal error


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("Usage: python3 initialize_firestore.py <project_id> <processor_id>")
        sys.exit(1)
    
    project_id = sys.argv[1]
    processor_id = sys.argv[2]
    
    initialize_processor_config(project_id, processor_id)