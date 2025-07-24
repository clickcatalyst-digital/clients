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
import gzip
from pathlib import Path
from datetime import datetime, timedelta, timedelta
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

def get_all_website_folders_from_github(gh_pages_path):
    """Get list of all website folders from GitHub Pages."""
    try:
        clients_dir = Path(gh_pages_path)
        folders = set()
        
        if not clients_dir.exists():
            logger.info("No clients directory found in GitHub Pages")
            return []
        
        # Get all directories in clients folder
        for item in clients_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                folders.add(item.name)
        
        logger.info(f"Found {len(folders)} website folders in GitHub Pages")
        return list(folders)
        
    except Exception as e:
        logger.error(f"Error listing GitHub Pages folders: {e}")
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
        
        # Get trial_end from trial_info or fallback to top-level
        trial_end = None
        if content_data.get('trial_info', {}).get('trial_end'):
            trial_end = content_data['trial_info']['trial_end']
        elif content_data.get('trial_end'):
            trial_end = content_data['trial_end']
            
        return {
            'trial_end': trial_end,
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
        import subprocess
        
        # Validate folder name
        if not re.match(r'^[a-zA-Z0-9\-_]+$', folder_name):
            logger.error(f"Invalid GitHub folder name format: {folder_name}")
            return False
        
        # Use gh-pages checkout path from environment
        gh_pages_path = os.environ.get('GH_PAGES_PATH')
        if not gh_pages_path:
            logger.error("GH_PAGES_PATH environment variable not set")
            return False
        
        # Construct folder path
        folder_path = Path(gh_pages_path) / folder_name
        
        # Check if specific folder exists
        if not folder_path.exists():
            logger.info(f"GitHub folder {folder_name} already deleted or doesn't exist")
            return True
        
        # Safe to delete
        shutil.rmtree(folder_path)
        logger.info(f"Successfully deleted GitHub folder: {folder_name}")
        
        # Commit and push the deletion with proper error handling
        try:
            # Save original directory
            original_cwd = os.getcwd()
            
            # Change to gh-pages directory
            os.chdir(gh_pages_path)
            
            # Configure git
            subprocess.run(['git', 'config', 'user.name', 'GitHub Actions'], 
                         check=True, capture_output=True, text=True)
            subprocess.run(['git', 'config', 'user.email', 'actions@github.com'], 
                         check=True, capture_output=True, text=True)
            
            # Add all changes
            subprocess.run(['git', 'add', '-A'], 
                          check=True, capture_output=True, text=True)
            
            # Check if there are changes to commit
            status_result = subprocess.run(['git', 'status', '--porcelain'], 
                                         capture_output=True, text=True, check=True)
            
            if not status_result.stdout.strip():
                logger.info(f"No changes to commit for {folder_name} deletion")
                return True
            
            # Commit changes
            subprocess.run([
                'git', 'commit', '-m', f'Delete expired website: {folder_name}'
            ], check=True, capture_output=True, text=True)
            
            # Push changes
            subprocess.run([
                'git', 'push', 'origin', 'gh-pages'
            ], check=True, capture_output=True, text=True)
            
            logger.info(f"Successfully committed and pushed deletion of {folder_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Git operation failed for {folder_name}: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during git operations: {e}")
            return False
        finally:
            # Always restore original directory
            try:
                os.chdir(original_cwd)
            except Exception as restore_error:
                logger.error(f"Failed to restore original directory: {restore_error}")
        
    except Exception as e:
        logger.error(f"Error deleting GitHub folder {folder_name}: {e}")
        return False

def regenerate_suspended_website(s3_client, bucket, folder_name, content_data, templates_dir, trial_end=None):
    """Regenerate a website with suspended template."""
    try:
        from website_generator import generate_website
        
        # Add suspension flag to content data
        content_data['website_status'] = 'suspended'
        content_data['status'] = 'suspended'  # Also update main status
        content_data['lastUpdated'] = datetime.now().isoformat()

        # Add trial_end for template countdown (use parameter first, fallback to content_data)
        if trial_end:
            content_data['trial_end'] = trial_end
        elif 'trial_info' in content_data and 'trial_end' in content_data['trial_info']:
            content_data['trial_end'] = content_data['trial_info']['trial_end']
        else:
            logger.warning(f"No trial_end found for {folder_name} - countdown will not work")
        
        # UPDATE S3 CONTENT.JSON WITH SUSPENDED FLAG
        content_key = f"{folder_name}/content.json.gz"
        json_string = json.dumps(content_data, indent=2)
        json_bytes = json_string.encode('utf-8')
        gzipped_bytes = gzip.compress(json_bytes)
        
        s3_client.put_object(
            Bucket=bucket,
            Key=content_key,
            Body=gzipped_bytes,
            ContentType='application/json',
            ContentEncoding='gzip'
        )
        logger.info(f"Updated S3 content.json with suspended status for {folder_name}")

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
    
    # Get all website folders from BOTH S3 and GitHub Pages
    s3_folders = get_all_website_folders_from_s3(s3_client, bucket)

    # Get gh-pages path
    gh_pages_path = os.environ.get('GH_PAGES_PATH')
    github_folders = []
    if gh_pages_path:
        github_folders = get_all_website_folders_from_github(gh_pages_path)
    else:
        logger.warning("GH_PAGES_PATH not set - cannot check GitHub folders")

    # Create union of both sets to ensure we check all folders
    all_folders = set(s3_folders + github_folders)
    website_folders = list(all_folders)

    logger.info(f"Total unique folders to check: {len(website_folders)} (S3: {len(s3_folders)}, GitHub: {len(github_folders)})")

    if not website_folders:
        logger.info("No website folders found in either S3 or GitHub Pages")
        return True
    
    # Track cleanup statistics
    stats = {
        'total_checked': 0,
        'suspended': 0,
        'deleted': 0,
        'errors': 0,
        'orphaned_cleaned': 0
    }
    
    # Process each website
    for folder_name in website_folders:
        try:
            stats['total_checked'] += 1
            
            # If folder doesn't exist in S3 but exists in GitHub, handle as orphaned
            if folder_name not in s3_folders:
                logger.info(f"Cleaning orphaned GitHub folder: {folder_name}")
                github_deleted = safe_delete_github_folder(folder_name)
                if github_deleted:
                    stats['orphaned_cleaned'] += 1
                    stats['deleted'] += 1
                else:
                    logger.error(f"Failed to delete orphaned GitHub folder: {folder_name}")
                    stats['errors'] += 1
                continue  # Skip further processing for this folder
            
            # Get website dates
            date_info = get_website_dates_from_s3(s3_client, bucket, folder_name)
            if not date_info:
                continue  # Skip folders without content.json
            
            trial_end = date_info['trial_end']
            content_data = date_info['content_data']
            
            # Parse trial_end date (ISO format from your content.json)
            trial_end_date = None
            deletion_date_obj = None
            
            if trial_end:
                try:
                    # Handle ISO format: "2025-08-21T13:52:50.573Z"
                    if 'T' in trial_end:
                        trial_end_date = datetime.fromisoformat(trial_end.replace('Z', '+00:00')).date()
                    else:
                        # Handle simple date format: "2025-08-21"
                        trial_end_date = datetime.strptime(trial_end, '%Y-%m-%d').date()
                    
                    # Calculate deletion date (60 days after trial ends)
                    deletion_date_obj = trial_end_date + timedelta(days=60)
                    
                except ValueError as e:
                    logger.warning(f"Invalid trial_end format for {folder_name}: {trial_end}")
            
            # Decision logic
            if deletion_date_obj and today >= deletion_date_obj:
                # Delete the website completely from both S3 and GitHub
                logger.info(f"Deleting expired website: {folder_name} (deletion date: {deletion_date_obj})")
                
                s3_deleted = safe_delete_s3_folder(s3_client, bucket, folder_name)
                github_deleted = safe_delete_github_folder(folder_name)
                
                if s3_deleted and github_deleted:
                    logger.info(f"Successfully deleted website: {folder_name}")
                    stats['deleted'] += 1
                else:
                    logger.error(f"Partial deletion failure for {folder_name} (S3: {s3_deleted}, GitHub: {github_deleted})")
                    stats['errors'] += 1
                    
            elif trial_end_date and today > trial_end_date:
                # Check if already suspended
                current_website_status = content_data.get('website_status')
                current_status = content_data.get('status', '')
                
                if current_website_status == 'suspended' or current_status == 'suspended':
                    continue  # Already suspended
                
                # Only suspend if it's actually a trial website
                is_trial = content_data.get('trial_info', {}).get('is_trial', False)
                
                if is_trial or current_status == 'trial':
                    logger.info(f"Suspending expired trial: {folder_name} (trial ended: {trial_end_date})")
        
                    success = regenerate_suspended_website(s3_client, bucket, folder_name, content_data, templates_dir, trial_end)
                    if success:
                        stats['suspended'] += 1
                    else:
                        stats['errors'] += 1
                
        except Exception as e:
            logger.error(f"Error processing website {folder_name}: {e}")
            stats['errors'] += 1
            continue
    
    # Log final statistics
    logger.info(f"Cleanup completed. Stats: {stats}")
    
    return stats['errors'] == 0


if __name__ == '__main__':
    success = cleanup_expired_websites()
    exit(0 if success else 1)
