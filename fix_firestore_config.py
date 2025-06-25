#!/usr/bin/env python3
"""
Fix the corrupted Firestore configuration with correct document types
"""

from google.cloud import firestore
from datetime import datetime, timezone

PROJECT_ID = "tetrix-462721"
PROCESSOR_ID = "ddc065df69bfa3b5"

def fix_firestore_config():
    """Fix the Firestore training config with correct document types"""
    db = firestore.Client(project=PROJECT_ID)
    
    print("🔧 Fixing Firestore training configuration...")
    
    # Get current config
    config_ref = db.collection('training_configs').document(PROCESSOR_ID)
    config_doc = config_ref.get()
    
    if config_doc.exists:
        current_config = config_doc.to_dict()
        print(f"Current document_types: {current_config.get('document_types', 'Not found')}")
    else:
        print("No existing config found")
        current_config = {}
    
    # Update with correct configuration
    correct_config = {
        'processor_id': PROCESSOR_ID,
        'processor_name': 'document_classifier_veronica',
        'enabled': True,
        'min_documents_for_initial_training': 3,
        'min_documents_for_incremental': 2,
        'min_accuracy_for_deployment': 0,
        'check_interval_minutes': 60,
        'auto_deploy': True,
        'document_types': [
            'capital_call',        # lowercase to match folder names
            'distribution_notice',
            'financial_statement',
            'portfolio_summary',
            'tax',
            'OTHER'
        ],
        'created_at': current_config.get('created_at', datetime.now(timezone.utc)),
        'updated_at': datetime.now(timezone.utc)
    }
    
    # Update the configuration
    config_ref.set(correct_config, merge=True)
    
    print("✅ Updated Firestore configuration with correct document types:")
    for doc_type in correct_config['document_types']:
        print(f"   - {doc_type}")
    
    print("\n🎯 Configuration now matches folder structure:")
    print("   Folders: capital_call, distribution_notice, financial_statement, etc.")
    print("   Config:  capital_call, distribution_notice, financial_statement, etc.")

if __name__ == "__main__":
    fix_firestore_config()