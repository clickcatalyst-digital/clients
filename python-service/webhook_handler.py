"""
S3 Website Generator and Namecheap DNS Integration
--------------------------------------------------
This script:
1. Validates API requests via API key
2. Downloads and decompresses content.json.gz from S3
3. Downloads assets (images) from S3 (OPTIMIZED with ThreadPoolExecutor)
4. Renders the appropriate template based on website type
5. Saves output to clients/{folder}/index.html
6. Configures a CNAME record on Namecheap for custom domain

Environment Variables Required:
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_REGION
- S3_BUCKET_NAME
- API_KEY (for webhook authentication)
- NAMECHEAP_API_KEY
- NAMECHEAP_USERNAME
- NAMECHEAP_API_IP
- DOMAIN_NAME (base domain, e.g., clickcatalyst.digital)
"""

import os
import json
import boto3
import gzip
import requests
import shutil
import xmltodict
import subprocess
import tempfile
import concurrent.futures
from io import BytesIO
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize the Flask app
app = Flask(__name__)

# Get environment variables
API_KEY = os.getenv("API_KEY")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
NAMECHEAP_API_KEY = os.getenv("NAMECHEAP_API_KEY")
NAMECHEAP_USERNAME = os.getenv("NAMECHEAP_USERNAME")
NAMECHEAP_API_IP = os.getenv("NAMECHEAP_API_IP")
DOMAIN_NAME = os.getenv("DOMAIN_NAME", "clickcatalyst.digital")
GITHUB_PAGES_TARGET = os.getenv("GITHUB_PAGES_TARGET", "clickcatalyst.github.io")
GITHUB_REPO = os.getenv("GITHUB_REPO", "clickcatalyst/client")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_EMAIL = os.getenv("GITHUB_EMAIL")
CALLBACK_URL = os.getenv("CALLBACK_URL")  # Optional webhook callback URL
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")  # Optional Slack notification

# Maximum number of concurrent S3 downloads
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))

# Initialize AWS S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

# Initialize Jinja2 environment
jinja_env = Environment(
    loader=FileSystemLoader('templates'),
    autoescape=True
)

# Ensure the clients directory exists
Path("clients").mkdir(exist_ok=True)

def validate_api_key():
    """Validate the API key provided in the request headers."""
    auth_header = request.headers.get('x-api-key')
    if not auth_header or auth_header != API_KEY:
        return False
    return True

def download_from_s3(bucket, key):
    """Download a file from S3 and return its content."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()
    except Exception as e:
        logger.error(f"Error downloading {key} from S3: {e}")
        return None

def extract_content_json(content_bytes):
    """Decompress gzipped content.json and parse the JSON."""
    try:
        decompressed_data = gzip.decompress(content_bytes)
        return json.loads(decompressed_data.decode('utf-8'))
    except Exception as e:
        logger.error(f"Error decompressing or parsing content.json: {e}")
        return None

def download_single_asset(bucket, asset_key, local_path):
    """Download a single asset from S3 and save to local path."""
    try:
        s3_client.download_file(bucket, asset_key, str(local_path))
        return True
    except Exception as e:
        logger.error(f"Error downloading asset {asset_key}: {e}")
        return False

def download_assets(bucket, folder_name, asset_keys):
    """
    Download assets (images) from S3 and save to local directory.
    Optimized with ThreadPoolExecutor for parallel downloads.
    """
    assets_dir = Path(f"clients/{folder_name}/assets")
    assets_dir.mkdir(exist_ok=True, parents=True)
    
    downloaded_assets = {}
    download_tasks = []
    
    # Prepare download tasks
    for asset_type, asset_key in asset_keys.items():
        if not asset_key:
            continue
            
        # Extract filename from the S3 key
        filename = asset_key.split('/')[-1]
        local_path = assets_dir / filename
        
        # Add to task list
        download_tasks.append({
            'asset_type': asset_type,
            'asset_key': asset_key,
            'local_path': local_path,
            'filename': filename
        })
    
    # Use ThreadPoolExecutor to download assets in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
        # Submit download tasks
        future_to_task = {
            executor.submit(download_single_asset, bucket, task['asset_key'], task['local_path']): task
            for task in download_tasks
        }
        
        # Process completed downloads
        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            try:
                success = future.result()
                if success:
                    # Store the relative path for template usage
                    downloaded_assets[f"{task['asset_type']}_path"] = f"assets/{task['filename']}"
                    # downloaded_assets[task['asset_type']] = f"assets/{task['filename']}"
                    logger.info(f"Downloaded {task['asset_type']} to {task['local_path']}")
            except Exception as e:
                logger.error(f"Exception downloading {task['asset_key']}: {e}")
    
    return downloaded_assets

def render_template(content_data, assets):
    """Render the appropriate HTML template based on website type."""
    # Determine which template to use based on user_type
    website_type = content_data.get("user_type", "business")
    template_name = f"{website_type.lower()}.html"
    
    # Check if template exists, otherwise use default
    template_path = Path(f"templates/{template_name}")
    if not template_path.exists():
        template_name = "default.html"
        logger.warning(f"Template for {website_type} not found, using default")
    
    # Load template
    template = jinja_env.get_template(template_name)
    
    # Merge content data with asset paths
    template_data = {**content_data}
    for asset_type, asset_path in assets.items():
        template_data[asset_type] = asset_path
    
    # Add color schemes based on user's chosen theme
    theme = content_data.get("theme", "light")
    if theme == "light":
        template_data["colors"] = {
            "primary": "#4A90E2",
            "secondary": "#6FCF97",
            "background": "#FFFFFF",
            "text": "#333333"
        }
    elif theme == "dark":
        template_data["colors"] = {
            "primary": "#BB86FC",
            "secondary": "#03DAC6",
            "background": "#121212",
            "text": "#E1E1E1"
        }
    # Add more theme options as needed
    
    # Render the template with the data
    return template.render(**template_data)

def push_to_github(folder_name):
    """Push changes to GitHub repository to trigger GitHub Pages deployment."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.warning("GitHub token or repo not configured, skipping push")
        return False
        
    try:
        # Create a temporary directory for the Git operations
        with tempfile.TemporaryDirectory() as temp_dir:
            # Configure git
            subprocess.run(['git', 'config', '--global', 'user.name', GITHUB_USERNAME or 'ClickCatalyst Bot'], check=True)
            subprocess.run(['git', 'config', '--global', 'user.email', GITHUB_EMAIL or 'bot@clickcatalyst.digital'], check=True)
            
            # Clone the repository
            clone_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
            subprocess.run(['git', 'clone', clone_url, temp_dir], check=True)
            
            # Ensure clients directory exists
            client_dir_path = os.path.join(temp_dir, 'clients', folder_name)
            os.makedirs(client_dir_path, exist_ok=True)
            
            # Copy the generated site to the repository
            source_dir = os.path.join('clients', folder_name)
            if os.path.exists(source_dir):
                # Recursively copy all files
                for item in os.listdir(source_dir):
                    src_path = os.path.join(source_dir, item)
                    dst_path = os.path.join(client_dir_path, item)
                    
                    if os.path.isdir(src_path):
                        shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_path, dst_path)
            
            # Change to the repo directory
            cwd = os.getcwd()
            os.chdir(temp_dir)
            
            # Add changes
            subprocess.run(['git', 'add', '.'], check=True)
            
            # Create commit
            commit_message = f"Update website for {folder_name} - {datetime.now().isoformat()}"
            
            # Check if there are changes to commit
            status = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True, check=True)
            if status.stdout.strip():
                # There are changes to commit
                subprocess.run(['git', 'commit', '-m', commit_message], check=True)
                
                # Push changes
                subprocess.run(['git', 'push', 'origin', 'main'], check=True)
                logger.info(f"Successfully pushed changes to GitHub for {folder_name}")
                
                # Change back to original directory
                os.chdir(cwd)
                return True
            else:
                logger.info(f"No changes detected for {folder_name}, skipping commit")
                
            # Change back to original directory
            os.chdir(cwd)
            return True
            
    except Exception as e:
        logger.error(f"Error pushing to GitHub: {e}")
        return False

def send_callback_notification(data):
    """Send notification to callback URL that website is published."""
    if not CALLBACK_URL:
        return
        
    try:
        requests.post(
            CALLBACK_URL,
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=5  # Don't wait too long
        )
        logger.info(f"Callback notification sent to {CALLBACK_URL}")
    except Exception as e:
        logger.error(f"Error sending callback notification: {e}")

def send_slack_notification(message, website_url=None):
    """Send notification to Slack channel."""
    if not SLACK_WEBHOOK_URL:
        return
        
    try:
        payload = {
            "text": message,
            "attachments": []
        }
        
        if website_url:
            payload["attachments"].append({
                "title": "View Website",
                "title_link": website_url,
                "color": "#36a64f"
            })
            
        requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        logger.info("Slack notification sent")
    except Exception as e:
        logger.error(f"Error sending Slack notification: {e}")

def create_namecheap_cname(subdomain, target):
    """Create a CNAME record on Namecheap for the subdomain."""
    try:
        # Namecheap API endpoint
        base_url = "https://api.namecheap.com/xml.response"
        
        # Common parameters
        params = {
            'ApiUser': NAMECHEAP_USERNAME,
            'ApiKey': NAMECHEAP_API_KEY,
            'UserName': NAMECHEAP_USERNAME,
            'ClientIp': NAMECHEAP_API_IP,
            'Command': 'namecheap.domains.dns.getHosts',
            'SLD': DOMAIN_NAME.split('.')[0],
            'TLD': DOMAIN_NAME.split('.')[1]
        }
        
        # First, get current DNS records
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            logger.error(f"Failed to get DNS records: {response.text}")
            return False
        
        # Parse the XML response
        response_data = xmltodict.parse(response.text)
        
        # Extract existing hosts
        hosts = response_data['ApiResponse']['CommandResponse']['DomainDNSGetHostsResult']['host']
        if not isinstance(hosts, list):
            hosts = [hosts]
        
        # Check if CNAME already exists
        cname_exists = False
        for host in hosts:
            if host.get('@Name') == subdomain and host.get('@Type') == 'CNAME':
                cname_exists = True
                if host.get('@Address') == target:
                    logger.info(f"CNAME {subdomain} already points to {target}")
                    return True
                # Will need to update
                break
        
        # Prepare hosts for update
        host_records = []
        for host in hosts:
            if host.get('@Name') != subdomain or host.get('@Type') != 'CNAME':
                host_records.append({
                    'HostName': host.get('@Name'),
                    'RecordType': host.get('@Type'),
                    'Address': host.get('@Address'),
                    'MXPref': host.get('@MXPref', 10),
                    'TTL': host.get('@TTL', 1800)
                })
        
        # Add the new CNAME record
        host_records.append({
            'HostName': subdomain,
            'RecordType': 'CNAME',
            'Address': target,
            'MXPref': 10,
            'TTL': 1800
        })
        
        # Update parameters for setting hosts
        params['Command'] = 'namecheap.domains.dns.setHosts'
        
        # Add host records to parameters
        for i, record in enumerate(host_records):
            for key, value in record.items():
                params[f"{key}{i+1}"] = value
        
        # Make the API request
        response = requests.get(base_url, params=params)
        
        if response.status_code != 200:
            logger.error(f"Failed to update DNS records: {response.text}")
            return False
        
        # Parse response to confirm success
        response_data = xmltodict.parse(response.text)
        is_success = response_data['ApiResponse']['CommandResponse']['DomainDNSSetHostsResult'].get('@IsSuccess')
        
        if is_success == 'true':
            logger.info(f"CNAME record created for {subdomain}.{DOMAIN_NAME}")
            return True
        else:
            logger.error(f"Failed to create CNAME record: {response_data}")
            return False
            
    except Exception as e:
        logger.error(f"Error creating CNAME record: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    """Handle incoming webhook requests from the Next.js API."""
    # Validate API key
    if not validate_api_key():
        return jsonify({
            'success': False,
            'message': 'Invalid API key'
        }), 401
    
    # Parse request data
    try:
        data = request.json
        bucket = data.get('bucket')
        folder_name = data.get('folderName')
        website_id = data.get('websiteId')
        website_type = data.get('websiteType')
        
        logger.info(f"Processing website: {website_id} ({folder_name}) of type {website_type}")
        
        if not all([bucket, folder_name, website_id]):
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400
            
    except Exception as e:
        logger.error(f"Error parsing request data: {e}")
        return jsonify({
            'success': False,
            'message': f'Invalid request format: {str(e)}'
        }), 400
    
    try:
        # Download and extract content.json.gz
        content_key = f"{folder_name}/content.json"  # Note: Next.js uploads as content.json with gzip encoding
        try:
            content_bytes = download_from_s3(bucket, content_key)
            if not content_bytes:
                # Try alternative filename with .gz extension
                content_key = f"{folder_name}/content.json.gz"
                content_bytes = download_from_s3(bucket, content_key)
                
            if not content_bytes:
                return jsonify({
                    'success': False,
                    'message': f'Failed to download content.json or content.json.gz from S3'
                }), 500
        except Exception as e:
            logger.error(f"Error downloading content file: {e}")
            return jsonify({
                'success': False,
                'message': f'Failed to download content file: {str(e)}'
            }), 500
            
        content_data = extract_content_json(content_bytes)
        if not content_data:
            return jsonify({
                'success': False,
                'message': 'Failed to parse content data'
            }), 500
        
        # Create client directory
        client_dir = Path(f"clients/{folder_name}")
        client_dir.mkdir(exist_ok=True, parents=True)
        
        # Save the raw content.json for reference
        with open(client_dir / "content.json", "w") as f:
            json.dump(content_data, f, indent=2)
        
        # Download assets (logo and banner) in parallel
        start_time = datetime.now()
        asset_keys = {
            'logo': content_data.get('logo'),
            'banner': content_data.get('banner')
        }
        
        # Add additional assets if present in the content
        if content_data.get('gallery'):
            for i, image in enumerate(content_data.get('gallery', [])):
                asset_keys[f'gallery_{i}'] = image
                
        if content_data.get('team_photos'):
            for i, image in enumerate(content_data.get('team_photos', [])):
                asset_keys[f'team_{i}'] = image
        
        downloaded_assets = download_assets(bucket, folder_name, asset_keys)
        logger.info(f"Downloaded {len(downloaded_assets)} assets in {(datetime.now() - start_time).total_seconds():.2f} seconds")
        
        # Render the HTML with the appropriate template
        html_output = render_template(content_data, downloaded_assets)
        
        # Save the HTML to index.html
        with open(client_dir / "index.html", "w") as f:
            f.write(html_output)
        
        # Create a CNAME record for the subdomain
        subdomain = folder_name
        cname_target = f"{GITHUB_PAGES_TARGET}"
        dns_success = create_namecheap_cname(subdomain, cname_target)
        
        # Push to GitHub to trigger Pages deployment
        github_success = push_to_github(folder_name)
        
        # Generate the website URL
        website_url = f"https://{subdomain}.{DOMAIN_NAME}"
        
        # Prepare response data
        response_data = {
            'success': True,
            'message': 'Website generated successfully',
            'websiteUrl': website_url,
            'dnsConfigured': dns_success,
            'githubPushed': github_success,
            'websiteId': website_id,
            'timestamp': datetime.now().isoformat()
        }
        
        # Send notifications
        send_callback_notification(response_data)
        
        slack_message = f"🎉 New website deployed: *{content_data.get('business_name', folder_name)}*\nType: {website_type}\nFolder: {folder_name}"
        send_slack_notification(slack_message, website_url)
        
        # Return success response
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error processing website: {e}")
        return jsonify({
            'success': False,
            'message': f'Error generating website: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
