import json
import sys
import os
import shutil
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# Add python-service to path (might not be needed if run from root, but safe)
# sys.path.append('./python-service')  # Usually not needed if script is in python-service

try:
    # Import the shared website_generator module
    from website_generator import generate_website
    logger.info('Successfully imported website_generator module.')
except ImportError as import_err:
    logger.error(f'Failed to import: {import_err}')
    sys.exit(1)  # Exit with non-zero code on failure
except Exception as setup_err:
    logger.error(f'Error during setup/import: {setup_err}')
    sys.exit(1)

# Get event data from GitHub Actions
event_path = os.environ.get('GITHUB_EVENT_PATH')
if not event_path or not os.path.exists(event_path):
    logger.error('GITHUB_EVENT_PATH environment variable is invalid or file does not exist.')
    sys.exit(1)

try:
    with open(event_path) as f:
        event_data = json.load(f)
except Exception as json_err:
    logger.error(f'Failed to load or parse JSON from GITHUB_EVENT_PATH: {json_err}')
    sys.exit(1)

# Extract payload data
payload = event_data.get('client_payload', {})
bucket = payload.get('bucket')
folder_name = payload.get('folderName')
website_id = payload.get('websiteId')

if not all([bucket, folder_name, website_id]):
    logger.error('Missing required keys (bucket, folderName, websiteId) in client_payload.')
    sys.exit(1)

logger.info(f'Processing website generation request: ID={website_id}, Folder={folder_name}, Bucket={bucket}')

# Get AWS credentials from environment (passed by the 'env' block in YAML)
aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
aws_region = os.environ.get('AWS_REGION')

if not all([aws_access_key_id, aws_secret_access_key, aws_region]):
    logger.error('Missing AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION) in environment.')
    sys.exit(1)

# Define templates directory relative to the script's location or workspace root
# Assuming the script runs from the repo root in the Action
templates_dir = './python-service/templates'
logger.info(f"Using templates directory: {templates_dir}")

# Call the shared module to generate the website
result = generate_website(
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    aws_region=aws_region,
    bucket=bucket,
    folder_name=folder_name,
    website_id=website_id,
    templates_dir=templates_dir
)

# Check result and exit accordingly
if result['success']:
    logger.info(f"Website generation successful: {result['message']}")
    sys.exit(0)  # Explicitly exit with success code 0
else:
    logger.error(f"Website generation failed: {result['message']}")
    sys.exit(1)  # Explicitly exit with failure code 1
