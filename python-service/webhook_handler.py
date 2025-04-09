"""
S3 Website Generator and Namecheap DNS Integration
--------------------------------------------------
This script:
1. Validates API requests via API key
2. Uses shared website_generator module to generate websites
3. Configures a CNAME record on Namecheap for custom domain
4. Sends notifications and callbacks

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
import requests
import xmltodict
import subprocess
import tempfile
import shutil
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import logging
from pathlib import Path
from datetime import datetime

# Import shared module for website generation
from website_generator import initialize_s3_client, generate_website

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

# Initialize S3 client
s3_client = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_REGION:
    s3_client = initialize_s3_client(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )

# Ensure the clients directory exists
Path("clients").mkdir(exist_ok=True)

def validate_api_key():
    """Validate the API key provided in the request headers."""
    auth_header = request.headers.get('x-api-key')
    if not auth_header or auth_header != API_KEY:
        return False
    return True

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
    if not all([NAMECHEAP_API_KEY, NAMECHEAP_USERNAME, NAMECHEAP_API_IP, DOMAIN_NAME]):
        logger.warning("Namecheap API credentials not configured, skipping DNS setup")
        return False
        
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
        bucket = data.get('bucket') or S3_BUCKET_NAME
        folder_name = data.get('folderName')
        website_id = data.get('websiteId')
        website_type = data.get('websiteType', 'business')
        
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
        # Get the absolute path to the templates directory
        templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
        
        # Use the shared function to generate the website
        result = generate_website(
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            aws_region=AWS_REGION,
            bucket=bucket,
            folder_name=folder_name,
            website_id=website_id,
            templates_dir=templates_dir
        )
        
        if not result['success']:
            return jsonify({
                'success': False,
                'message': result['message']
            }), 500
        
        # Create a CNAME record for the subdomain
        subdomain = folder_name
        cname_target = GITHUB_PAGES_TARGET
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
        
        # Get business name from content.json if it exists
        client_dir = Path(f"clients/{folder_name}")
        business_name = folder_name
        try:
            with open(client_dir / "content.json", "r") as f:
                content = json.load(f)
                business_name = content.get('business_name', folder_name)
        except:
            pass
        
        slack_message = f"🎉 New website deployed: *{business_name}*\nType: {website_type}\nFolder: {folder_name}"
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
