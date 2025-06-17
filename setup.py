"""Setup script to verify environment and dependencies."""

import os
import sys
import subprocess
from pathlib import Path


def check_python_version():
    """Check if Python version is 3.8+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ Python 3.8+ is required")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_environment_variables():
    """Check required environment variables."""
    required_vars = {
        "GCP_PROJECT_ID": "Your Google Cloud Project ID",
        "DOCUMENT_AI_PROCESSOR_ID": "Your Document AI Processor ID", 
        "GOOGLE_APPLICATION_CREDENTIALS": "Path to service account JSON",
        "GCS_BUCKET_NAME": "Your GCS bucket name (optional)",
        "PDF_DIRECTORY": "Directory containing test PDFs (optional, defaults to 'test_documents')"
    }
    
    print("\nEnvironment Variables:")
    all_set = True
    
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            if var == "GOOGLE_APPLICATION_CREDENTIALS":
                # Check if file exists
                if os.path.exists(value):
                    print(f"✅ {var}: {value}")
                else:
                    print(f"❌ {var}: File not found: {value}")
                    all_set = False
            else:
                print(f"✅ {var}: {value}")
        else:
            if "optional" in description:
                print(f"⚠️  {var}: Not set ({description})")
            else:
                print(f"❌ {var}: Not set ({description})")
                all_set = False
    
    return all_set


def check_mongodb():
    """Check if MongoDB is running."""
    try:
        import pymongo
        client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
        client.server_info()
        print("\n✅ MongoDB is running on localhost:27017")
        return True
    except Exception as e:
        print("\n❌ MongoDB is not running. Please start MongoDB:")
        print("   - macOS: brew services start mongodb-community")
        print("   - Linux: sudo systemctl start mongod")
        print("   - Windows: net start MongoDB")
        return False


def check_gcloud_auth():
    """Check Google Cloud authentication."""
    try:
        result = subprocess.run(
            ["gcloud", "auth", "list"],
            capture_output=True,
            text=True,
            check=True
        )
        if "ACTIVE" in result.stdout:
            print("\n✅ Google Cloud authentication is configured")
            return True
        else:
            print("\n⚠️  No active Google Cloud authentication")
            return False
    except subprocess.CalledProcessError:
        print("\n⚠️  gcloud CLI not found or not configured")
        return False


def check_test_documents():
    """Check if test documents exist."""
    pdf_dir = os.getenv("PDF_DIRECTORY", "test_documents")
    pdf_path = Path(pdf_dir)
    
    if not pdf_path.exists():
        print(f"\n❌ Test documents directory not found: {pdf_dir}")
        return False
    
    pdf_files = list(pdf_path.glob("*.pdf"))
    if not pdf_files:
        print(f"\n❌ No PDF files found in {pdf_dir}")
        return False
    
    print(f"\n✅ Found {len(pdf_files)} PDF files in {pdf_dir}")
    return True


def create_env_template():
    """Create .env.template file."""
    template = """# Google Cloud Configuration
GCP_PROJECT_ID=your-project-id
DOCUMENT_AI_PROCESSOR_ID=your-processor-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# GCS Configuration
GCS_BUCKET_NAME=your-bucket-name

# Local Configuration
PDF_DIRECTORY=test_documents

# MongoDB Configuration (optional)
MONGODB_URL=mongodb://localhost:27017/document_ai
"""
    
    with open(".env.template", "w") as f:
        f.write(template)
    
    print("\n📄 Created .env.template file for reference")


def main():
    """Run all checks."""
    print("🔍 Document AI Setup Verification\n")
    print("="*50)
    
    checks = [
        ("Python Version", check_python_version),
        ("Environment Variables", check_environment_variables),
        ("MongoDB", check_mongodb),
        ("Google Cloud Auth", check_gcloud_auth),
        ("Test Documents", check_test_documents),
    ]
    
    all_passed = True
    for name, check_func in checks:
        if not check_func():
            all_passed = False
    
    # Create template file
    create_env_template()
    
    print("\n" + "="*50)
    if all_passed:
        print("✅ All checks passed! You're ready to run the pipeline.")
        print("\nNext steps:")
        print("1. Run: pip install -r requirements.txt")
        print("2. Run: python test_training.py")
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        print("\nFor detailed setup instructions, see README.md")


if __name__ == "__main__":
    main()