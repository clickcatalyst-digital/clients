"""
Website Generator Core Functionality
-----------------------------------
This module contains the core functionality for generating websites from S3 content.
It's designed to be used by both the GitHub Action workflow and the webhook handler.
"""

import os
import json
import boto3
import gzip
import html
import logging
import concurrent.futures
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Maximum number of concurrent S3 downloads
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "5"))

# Define Color Schemes (Map palette IDs to color values)
COLOR_SCHEMES = {
    'modern-minimalist': {
        'primary': '#368cbf',
        'secondary': '#7ebc59',
        'background': '#eaeaea',
        'text': '#33363b'
    },
    'luxurious-chic': {
        'primary': '#1c77ac',
        'secondary': '#c7af6b',
        'background': '#e4decd',
        'text': '#33363b'
    },
    'nature-inspired': {
        'primary': '#5cbdb9',
        'secondary': '#ebf6f5',
        'background': '#fceed1',
        'text': '#2d545e'
    },
    'retro-pop': {
        'primary': '#7d3cff',
        'secondary': '#f2d53c',
        'background': '#e1b382',
        'text': '#12343b'
    },
    'futuristic-tech': {
        'primary': '#1400c6',
        'secondary': '#7ebc59',
        'background': '#eaeaea',
        'text': '#33363b'
    },
    'dreamy-sunset': {
        'primary': '#6B7A8F',
        'secondary': '#F7882F',
        'background': '#DCC7AA',
        'text': '#2d545e'
    },
    'minimal': {
        'primary': '#4A90E2',
        'secondary': '#50E3C2',
        'background': '#FFFFFF',
        'text': '#333333'
    },
    'default': {
        'primary': '#4A90E2',
        'secondary': '#6FCF97',
        'background': '#FFFFFF',
        'text': '#333333'
    }
}

def get_contrast_color(hex_color, light_color, dark_color):
    """
    Determines if light or dark text provides better contrast against a given hex background color.
    """
    if not hex_color or not hex_color.startswith('#') or len(hex_color) != 7:
        logger.warning(f"Invalid hex color format '{hex_color}' for contrast check, returning dark.")
        return dark_color

    try:
        # Convert hex to RGB
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        r, g, b = rgb

        # Calculate luminance
        luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255

        # Determine contrast color
        threshold = 0.5
        return dark_color if luma > threshold else light_color
    except Exception as e:
        logger.error(f"Error calculating contrast for {hex_color}: {e}")
        return dark_color

def initialize_s3_client(aws_access_key_id, aws_secret_access_key, aws_region):
    """Initialize and return an S3 client."""
    return boto3.client(
        's3',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=aws_region
    )

def initialize_jinja_env(templates_dir):
    """Initialize and return a Jinja2 environment."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(['html', 'xml'])
    )
    
    # Add date filter
    def date_filter(value, format='%Y-%m-%d'):
        if value == "now":
            value = datetime.now()
        return value.strftime(format)
    
    env.filters['date'] = date_filter
    
    return env

def download_from_s3(s3_client, bucket, key):
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
        try:
            # First try to decompress (if it's gzipped)
            decompressed_data = gzip.decompress(content_bytes)
            return json.loads(decompressed_data.decode('utf-8'))
        except:
            # If decompression fails, try parsing directly (if it's not gzipped)
            return json.loads(content_bytes.decode('utf-8'))
    except Exception as e:
        logger.error(f"Error decompressing or parsing content.json: {e}")
        return None

def download_single_asset(s3_client, bucket, asset_key, local_path):
    """Download a single asset from S3 and save to local path."""
    try:
        s3_client.download_file(bucket, asset_key, str(local_path))
        return True
    except Exception as e:
        logger.error(f"Error downloading asset {asset_key}: {e}")
        return False

def download_assets(s3_client, bucket, folder_name, asset_keys):
    """
    Download assets (images) from S3 and save to local directory.
    Optimized with ThreadPoolExecutor for parallel downloads.
    """
    assets_dir = Path(f"clients/{folder_name}/assets")
    assets_dir.mkdir(exist_ok=True, parents=True)

    downloaded_assets = {}
    download_tasks = []

    for asset_type, asset_key in asset_keys.items():
        if not asset_key:
            continue

        filename = asset_key.split('/')[-1]
        local_path = assets_dir / filename

        download_tasks.append({
            'asset_type': asset_type,
            'asset_key': asset_key,
            'local_path': local_path,
            'filename': filename
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
        future_to_task = {
            executor.submit(download_single_asset, s3_client, bucket, task['asset_key'], task['local_path']): task
            for task in download_tasks
        }

        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            try:
                success = future.result()
                if success:
                    # Determine the key for the template data
                    template_key = task['asset_type']
                    # Add _path suffix only for standard keys like logo and banner
                    if task['asset_type'] in ['logo', 'banner']:
                         template_key = f"{task['asset_type']}_path"

                    # Store the relative path
                    downloaded_assets[template_key] = f"assets/{task['filename']}"
                    logger.info(f"Downloaded {task['asset_type']} to {task['local_path']}")
            except Exception as e:
                logger.error(f"Exception downloading {task['asset_key']}: {e}")

    return downloaded_assets

def render_template(jinja_env, content_data, assets):
    """Render the appropriate HTML template based on website type."""
    # Basic Data Validation
    if "headline" not in content_data:
        content_data["headline"] = content_data.get("site_url", "Website")
    if "tagline" not in content_data:
        content_data["tagline"] = ""

    website_type = content_data.get("user_type", "business")
    primary_template_name = f"{website_type.lower()}.html"
    fallback_template_name = "default.html"

    # Load Template (with fallback)
    template = None
    template_to_render = ""
    try:
        template = jinja_env.get_template(primary_template_name)
        template_to_render = primary_template_name
        logger.info(f"Using primary template: {template_to_render}")
    except TemplateNotFound:
        logger.warning(f"Primary template '{primary_template_name}' not found. Attempting fallback '{fallback_template_name}'.")
        try:
            template = jinja_env.get_template(fallback_template_name)
            template_to_render = fallback_template_name
            logger.info(f"Using fallback template: {template_to_render}")
        except TemplateNotFound:
            logger.error(f"CRITICAL: Fallback template '{fallback_template_name}' also not found in search path: {jinja_env.loader.searchpath}")
            return generate_error_html("Required template files could not be loaded")
        except Exception as e_load_fallback:
            logger.error(f"Failed to load fallback template '{fallback_template_name}': {e_load_fallback}")
            return generate_error_html(f"Error loading fallback template: {str(e_load_fallback)}")
    except Exception as e_load_primary:
        logger.error(f"Failed to load primary template '{primary_template_name}': {e_load_primary}")
        return generate_error_html(f"Error loading primary template: {str(e_load_primary)}")

    # Prepare Template Data
    template_data = {**content_data}
    for asset_type, asset_path in assets.items():
        template_data[asset_type] = asset_path

    palette_id = content_data.get("color_palette", "default")
    selected_colors = COLOR_SCHEMES.get(palette_id, COLOR_SCHEMES["default"]).copy()
    selected_colors.setdefault('background', '#FFFFFF')
    selected_colors.setdefault('text', '#333333')

    light_contrast = selected_colors['background']
    dark_contrast = selected_colors['text']

    selected_colors['text_on_primary'] = get_contrast_color(selected_colors.get('primary'), light_contrast, dark_contrast)
    selected_colors['text_on_secondary'] = get_contrast_color(selected_colors.get('secondary'), light_contrast, dark_contrast)
    selected_colors['text_on_gradient'] = get_contrast_color(selected_colors.get('primary'), light_contrast, dark_contrast)
    selected_colors['text_on_dark'] = get_contrast_color(dark_contrast, light_contrast, dark_contrast)

    template_data["colors"] = selected_colors
    logger.info(f"Applied color palette: {palette_id} with calculated contrasts")

    # Render the loaded template
    try:
        return template.render(**template_data)
    except Exception as e_render:
        logger.error(f"Template rendering error for '{template_to_render}': {e_render}")
        return generate_error_html(f"Template rendering error: {str(e_render)}", template_data)

def generate_error_html(error_message, template_data=None):
    """Generate a simple HTML error page."""
    error_html = f"""<!DOCTYPE html>
    <html><head><title>Error</title></head><body>
    <h1>Website Generation Error</h1>
    <p>{html.escape(error_message)}</p>"""
    
    if template_data:
        error_html += f"""
        <h2>Data Passed:</h2>
        <pre>{html.escape(json.dumps(template_data, indent=2, default=str))}</pre>"""
    
    error_html += """
    </body></html>"""
    
    return error_html

def generate_website(
    aws_access_key_id,
    aws_secret_access_key,
    aws_region,
    bucket,
    folder_name,
    website_id,
    templates_dir
):
    """
    Main function to generate a website.
    """
    try:
        # Initialize clients
        s3_client = initialize_s3_client(aws_access_key_id, aws_secret_access_key, aws_region)
        jinja_env = initialize_jinja_env(templates_dir)
        
        # Download content.json
        content_key_plain = f"{folder_name}/content.json"
        content_key_gz = f"{folder_name}/content.json.gz"
        
        content_bytes = download_from_s3(s3_client, bucket, content_key_plain)
        if not content_bytes:
            content_bytes = download_from_s3(s3_client, bucket, content_key_gz)
            
        if not content_bytes:
            raise Exception(f"Failed to download content file ({content_key_plain} or {content_key_gz})")
            
        # Extract content data
        content_data = extract_content_json(content_bytes)
        if not content_data:
            raise Exception("Failed to parse content data")
        
        # Create client directory
        client_dir = Path(f"clients/{folder_name}")
        client_dir.mkdir(exist_ok=True, parents=True)
        
        # Save the raw content.json for reference
        with open(client_dir / "content.json", "w") as f:
            json.dump(content_data, f, indent=2)
        
        # Download assets
        asset_keys = {
            'logo': content_data.get('logo'),
            'banner': content_data.get('banner'),
            'about_image': content_data.get('about_image')
        }
        
        # Add additional assets if present
        if content_data.get('gallery'):
            for i, image in enumerate(content_data.get('gallery', [])):
                asset_keys[f'gallery_{i}'] = image
                
        if content_data.get('team_photos'):
            for i, image in enumerate(content_data.get('team_photos', [])):
                asset_keys[f'team_{i}'] = image
                
        # Add portfolio project images if they exist
        if 'portfolioProjects' in content_data:
            for i, project in enumerate(content_data['portfolioProjects']):
                if project.get('imagePreview'):
                    asset_keys[f'project_{i}_image'] = project['imagePreview']
        
        downloaded_assets = download_assets(s3_client, bucket, folder_name, asset_keys)
        
        # Render HTML
        html_output = render_template(jinja_env, content_data, downloaded_assets)
        
        # Save HTML
        with open(client_dir / "index.html", "w", encoding='utf-8') as f:
            f.write(html_output)
        logger.info(f"Generated index.html for {folder_name}")
        
        # Copy CSS file if it exists
        css_source_path = Path(f"{templates_dir}/styles.css")
        css_target_path = client_dir / "styles.css"
        
        if css_source_path.exists():
            import shutil
            shutil.copy2(css_source_path, css_target_path)
            logger.info(f"Copied CSS to {css_target_path}")
        else:
            logger.warning(f"CSS file not found at {css_source_path}")

        # Copy images folder if it exists for the logo on the sidebar
        images_source_path = Path(f"{templates_dir}/images")
        images_target_path = client_dir / "images"
        
        if images_source_path.exists():
            import shutil
            if not images_target_path.exists():
                images_target_path.mkdir(parents=True)
            for image_file in images_source_path.glob('*.*'):
                shutil.copy2(image_file, images_target_path / image_file.name)
            logger.info(f"Copied images to {images_target_path}")
        else:
            logger.warning(f"Images folder not found at {images_source_path}")
        
        return {
            'success': True,
            'message': f'Successfully generated website for {folder_name}',
            'folder_name': folder_name,
            'website_id': website_id
        }
        
    except Exception as e:
        logger.exception(f"Error generating website: {e}")
        return {
            'success': False,
            'message': str(e),
            'folder_name': folder_name,
            'website_id': website_id
        }
