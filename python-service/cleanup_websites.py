"""
Weekly Website Cleanup Script
-----------------------------
This script runs every Saturday to:
1. Check all websites for expired trials and deletion dates
2. Update suspended websites to show suspended.html template
3. Delete websites that have reached their deletion date
4. Clean up both S3 storage and GitHub Pages folders
"""

import os
import json
import boto3
import shutil
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta
from website_generator import initialize_s3_client, initialize_jinja_env, extract_content_json, download_from_s3

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_all_website_folders_from_s3(s3_client, bucket):
    """Get list of all website folders from S3."""
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        folders = set()
        
        for page in paginator.paginate(Bucket=bucket, Delimiter='/'):
            # Get top-level folders (website folders)
            for prefix in page.get('CommonPrefixes', []):
                folder_name = prefix['Prefix'].rstrip('/')
                # Skip system folders
                if folder_name not in ['temp', '.github', 'system']:
                    folders.add(folder_name)
        
        logger.info(f"Found {len(folders)} website folders in S3")
        return list(folders)
        
    except Exception as e:
        logger.error(f"Error listing S3 folders: {e}")
        return []

def get_website_dates_from_s3(s3_client, bucket, folder_name):
    """Download and parse content.json to get trial dates."""
    try:
        # Try both content.json and content.json.gz
        content_key_plain = f"{folder_name}/content.json"
        content_key_gz = f"{folder_name}/content.json.gz"
        
        content_bytes = download_from_s3(s3_client, bucket, content_key_plain)
        if not content_bytes:
            content_bytes = download_from_s3(s3_client, bucket, content_key_gz)
            
        if not content_bytes:
            logger.warning(f"No content.json found for {folder_name}")
            return None
            
        # Extract and parse JSON
        content_data = extract_content_json(content_bytes)
        if not content_data:
            logger.warning(f"Failed to parse content.json for {folder_name}")
            return None
            
        return {
            'trial_end': content_data.get('trial_end'),
            'deletion_date': content_data.get('deletion_date'),
            'content_data': content_data
        }
        
    except Exception as e:
        logger.error(f"Error getting dates for {folder_name}: {e}")
        return None

def safe_delete_s3_folder(s3_client, bucket, folder_name):
    """Safely delete a website folder from S3."""
    try:
        # Validate folder name
        if not re.match(r'^[a-zA-Z0-9\-_]+$', folder_name):
            logger.error(f"Invalid S3 folder name format: {folder_name}")
            return False
        
        # List all objects in the folder
        paginator = s3_client.get_paginator('list_objects_v2')
        objects_to_delete = []
        
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{folder_name}/"):
            for obj in page.get('Contents', []):
                objects_to_delete.append({'Key': obj['Key']})
        
        if not objects_to_delete:
            logger.info(f"S3 folder {folder_name} already empty or doesn't exist")
            return True
        
        # Delete objects in batches (max 1000 per batch)
        for i in range(0, len(objects_to_delete), 1000):
            batch = objects_to_delete[i:i+1000]
            response = s3_client.delete_objects(
                Bucket=bucket,
                Delete={'Objects': batch}
            )
            
            if response.get('Errors'):
                logger.error(f"S3 deletion errors for {folder_name}: {response['Errors']}")
                return False
        
        logger.info(f"Successfully deleted S3 folder: {folder_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error deleting S3 folder {folder_name}: {e}")
        return False

def safe_delete_github_folder(folder_name):
    """Safely delete a website folder from GitHub Pages."""
    try:
        # Validate folder name
        if not re.match(r'^[a-zA-Z0-9\-_]+$', folder_name):
            logger.error(f"Invalid GitHub folder name format: {folder_name}")
            return False
        
        # Ensure it's in the clients directory
        folder_path = Path(f"clients/{folder_name}")
        
        # Double-check the path is what we expect
        if not folder_path.parent.name == "clients":
            logger.error(f"Folder not in clients directory: {folder_path}")
            return False
        
        # Check if folder exists
        if not folder_path.exists():
            logger.info(f"GitHub folder {folder_name} already deleted or doesn't exist")
            return True
        
        # Verify it contains expected website files
        if not (folder_path / "index.html").exists():
            logger.warning(f"No index.html found in {folder_name} - may not be a website folder")
            # Continue with deletion anyway
        
        # Safe to delete
        shutil.rmtree(folder_path)
        logger.info(f"Successfully deleted GitHub folder: {folder_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error deleting GitHub folder {folder_name}: {e}")
        return False

def regenerate_suspended_website(s3_client, bucket, folder_name, content_data, templates_dir):
    """Regenerate a website with suspended template."""
    try:
        from website_generator import generate_website
        
        # Add suspension flag to content data
        content_data['website_status'] = 'suspended'
        
        # Generate the website (will use suspended template due to status)
        result = generate_website(
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
            aws_region=os.environ.get('AWS_REGION'),
            bucket=bucket,
            folder_name=folder_name,
            website_id=content_data.get('websiteId', folder_name),
            templates_dir=templates_dir
        )
        
        if result['success']:
            logger.info(f"Successfully regenerated suspended website: {folder_name}")
            return True
        else:
            logger.error(f"Failed to regenerate suspended website {folder_name}: {result['message']}")
            return False
            
    except Exception as e:
        logger.error(f"Error regenerating suspended website {folder_name}: {e}")
        return False

def cleanup_expired_websites():
    """Main cleanup function that processes all websites."""
    # Get environment variables
    aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    aws_region = os.environ.get('AWS_REGION')
    bucket = os.environ.get('S3_BUCKET_NAME')
    
    if not all([aws_access_key_id, aws_secret_access_key, aws_region, bucket]):
        logger.error("Missing required AWS environment variables")
        return False
    
    # Initialize S3 client
    s3_client = initialize_s3_client(aws_access_key_id, aws_secret_access_key, aws_region)
    
    # Get templates directory
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    
    # Get current date
    today = datetime.now().date()
    logger.info(f"Starting cleanup for date: {today}")
    
    # Get all website folders
    website_folders = get_all_website_folders_from_s3(s3_client, bucket)
    
    if not website_folders:
        logger.info("No website folders found")
        return True
    
    # Track cleanup statistics
    stats = {
        'total_checked': 0,
        'suspended': 0,
        'deleted': 0,
        'errors': 0
    }
    
    # Process each website
    for folder_name in website_folders:
        try:
            stats['total_checked'] += 1
            logger.info(f"Processing website: {folder_name}")
            
            # Get website dates
            date_info = get_website_dates_from_s3(s3_client, bucket, folder_name)
            if not date_info:
                logger.warning(f"Skipping {folder_name} - no date information")
                stats['errors'] += 1
                continue
            
            trial_end = date_info['trial_end']
            deletion_date = date_info['deletion_date']
            content_data = date_info['content_data']
            
            # Parse dates if they exist
            trial_end_date = None
            deletion_date_obj = None
            
            if trial_end:
                try:
                    trial_end_date = datetime.strptime(trial_end, '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid trial_end format for {folder_name}: {trial_end}")
            
            if deletion_date:
                try:
                    deletion_date_obj = datetime.strptime(deletion_date, '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid deletion_date format for {folder_name}: {deletion_date}")
            
            # Decision logic
            if deletion_date_obj and today >= deletion_date_obj:
                # Delete the website completely
                logger.info(f"Deleting expired website: {folder_name} (deletion date: {deletion_date})")
                
                s3_deleted = safe_delete_s3_folder(s3_client, bucket, folder_name)
                github_deleted = safe_delete_github_folder(folder_name)
                
                if s3_deleted and github_deleted:
                    logger.info(f"Successfully deleted website: {folder_name}")
                    stats['deleted'] += 1
                else:
                    logger.error(f"Partial deletion failure for {folder_name}")
                    stats['errors'] += 1
                    
            elif trial_end_date and today > trial_end_date:
                # Suspend the website (regenerate with suspended template)
                logger.info(f"Suspending expired trial: {folder_name} (trial ended: {trial_end})")
                
                success = regenerate_suspended_website(s3_client, bucket, folder_name, content_data, templates_dir)
                if success:
                    stats['suspended'] += 1
                else:
                    stats['errors'] += 1
                    
            else:
                # Website is still active
                logger.info(f"Website {folder_name} is still active")
                
        except Exception as e:
            logger.error(f"Error processing website {folder_name}: {e}")
            stats['errors'] += 1
    
    # Log final statistics
    logger.info(f"Cleanup completed. Stats: {stats}")
    
    return stats['errors'] == 0

if __name__ == '__main__':
    success = cleanup_expired_websites()
    exit(0 if success else 1)
