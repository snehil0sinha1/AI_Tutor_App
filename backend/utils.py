import time
import logging
import os
import random
import boto3
from botocore.exceptions import ClientError
from google.api_core import exceptions

logger = logging.getLogger(__name__)

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION', 'us-east-1')
    )

def upload_to_s3(file_obj, bucket, object_name, content_type=None):
    """Upload a file to an S3 bucket"""
    s3_client = get_s3_client()
    extra_args = {}
    if content_type:
        extra_args['ContentType'] = content_type
        
    try:
        s3_client.upload_fileobj(file_obj, bucket, object_name, ExtraArgs=extra_args)
    except ClientError as e:
        logger.error(e)
        return False
    return True

def generate_presigned_url(bucket, object_name, expiration=3600, response_content_type=None):
    """Generate a presigned URL to share an S3 object"""
    s3_client = get_s3_client()
    try:
        params = {'Bucket': bucket, 'Key': object_name}
        if response_content_type:
            params['ResponseContentType'] = response_content_type
            
        response = s3_client.generate_presigned_url('get_object',
                                                    Params=params,
                                                    ExpiresIn=expiration)
    except ClientError as e:
        logger.error(e)
        return None
    return response

def download_from_s3(bucket, object_name, file_name):
    """Download a file from S3"""
    s3_client = get_s3_client()
    try:
        s3_client.download_file(bucket, object_name, file_name)
    except ClientError as e:
        logger.error(e)
        return False
    return True

def generate_with_retry(model, content, retries=3, initial_delay=1):
    """
    Generates content using the Gemini model with retry logic for rate limits (429).
    """
    delay = initial_delay
    for attempt in range(retries + 1):
        try:
            return model.generate_content(content)
        except Exception as e:
            # Check for 429 or ResourceExhausted
            is_rate_limit = "429" in str(e) or "Resource exhausted" in str(e)
            
            if is_rate_limit and attempt < retries:
                sleep_time = delay + random.uniform(0, 1)
                logger.warning(f"Rate limit hit. Retrying in {sleep_time:.2f}s (Attempt {attempt+1}/{retries})")
                time.sleep(sleep_time)
                delay *= 2 # Exponential backoff
            else:
                raise e

def download_youtube_video(url, output_path):
    """
    Downloads a YouTube video using yt-dlp.
    Returns the filename if successful, None otherwise.
    """
    import yt_dlp
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        logger.error(f"Error downloading YouTube video: {e}")
        return False
