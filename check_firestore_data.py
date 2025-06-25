#!/usr/bin/env python3
"""
Check Firestore for any remaining corrupted data with 'document-ai-service'
"""

from google.cloud import firestore

PROJECT_ID = "tetrix-462721"
PROCESSOR_ID = "ddc065df69bfa3b5"

def check_firestore_data():
    """Check all Firestore collections for corrupted data"""
    db = firestore.Client(project=PROJECT_ID)
    
    print("🔍 Checking Firestore for corrupted data...")
    
    # Check processed_documents for any with wrong document_type
    print("\n📄 Checking processed_documents:")
    docs_query = db.collection('processed_documents').limit(10)
    docs = list(docs_query.get())
    
    for doc in docs:
        doc_data = doc.to_dict()
        doc_type = doc_data.get('document_type', 'None')
        doc_label = doc_data.get('document_label', 'None')
        
        if 'document-ai-service' in str(doc_type) or 'document-ai-service' in str(doc_label):
            print(f"❌ FOUND CORRUPTED: {doc.id}")
            print(f"   document_type: {doc_type}")
            print(f"   document_label: {doc_label}")
        else:
            print(f"✅ Clean: {doc.id} - type: {doc_type}, label: {doc_label}")
    
    # Check training_configs
    print(f"\n⚙️  Checking training_configs for {PROCESSOR_ID}:")
    config_ref = db.collection('training_configs').document(PROCESSOR_ID)
    config_doc = config_ref.get()
    
    if config_doc.exists:
        config_data = config_doc.to_dict()
        doc_types = config_data.get('document_types', [])
        print(f"Document types: {doc_types}")
        
        if 'document-ai-service' in doc_types:
            print("❌ FOUND 'document-ai-service' in document_types!")
        else:
            print("✅ No 'document-ai-service' found in config")
    else:
        print("❌ No training config found")
    
    # Check training_batches
    print(f"\n📊 Checking training_batches:")
    batches_query = db.collection('training_batches').limit(5)
    batches = list(batches_query.get())
    
    for batch in batches:
        batch_data = batch.to_dict()
        print(f"Batch: {batch.id} - Status: {batch_data.get('status')}")

if __name__ == "__main__":
    check_firestore_data()