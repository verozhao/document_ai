#!/usr/bin/env python3
"""
Script to manually update training status in Firestore to unblock new training
"""

from google.cloud import firestore
from datetime import datetime, timezone

PROJECT_ID = "tetrix-462721"
PROCESSOR_ID = "ddc065df69bfa3b5"

def update_training_status():
    """Update training status to completed"""
    db = firestore.Client(project=PROJECT_ID)
    
    # Find active training records
    active_training = db.collection('training_batches').where(
        'processor_id', '==', PROCESSOR_ID
    ).where(
        'status', 'in', ['pending', 'preparing', 'training', 'deploying']
    ).get()
    
    print(f"Found {len(active_training)} active training records")
    
    for doc in active_training:
        doc_ref = db.collection('training_batches').document(doc.id)
        doc_ref.update({
            'status': 'completed',
            'completed_at': datetime.now(timezone.utc)
        })
        print(f"Updated training batch {doc.id} to completed status")
    
    print("All training records updated successfully")

if __name__ == "__main__":
    update_training_status()