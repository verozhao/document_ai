"""Document AI package for processing and training documents."""

# Core client
from .client import EnhancedDocumentAIClient

# Models
from .models import (
    DocumentAIStatus,
    DocumentType,
    ProcessedDocument,
    IncrementalTrainingBatch,
    AutomatedTrainingConfig,
)

# Training components
from .incremental_training import AutomatedTrainingManager

# API
from .api import router as document_ai_router

__all__ = [
    # Core client
    'EnhancedDocumentAIClient',
    
    # Models
    'DocumentAIStatus',
    'DocumentType',
    'ProcessedDocument',
    'IncrementalTrainingBatch',
    'AutomatedTrainingConfig',
    
    # Training
    'AutomatedTrainingManager',
    
    # API
    'document_ai_router',
]

# Version
__version__ = "2.0.0"