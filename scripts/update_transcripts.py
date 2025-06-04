"""
Transcript Update Script
=======================

This script is used for ongoing operations to update transcripts and metadata in an existing setup.
It allows downloading individual transcript files and/or updating the metadata.json file that lists all available transcripts.

Environment Variables Required:
----------------------------
- DATA_DIR: Base directory for storing files (defaults to './data')
- S3_BUCKET: Name of the S3 bucket containing the files
- AWS_ACCESS_KEY_ID: AWS access key for S3 access
- AWS_SECRET_ACCESS_KEY: AWS secret key for S3 access

Usage:
------
# Update metadata and download a new transcript
python update_transcripts.py --metadata --transcript transcript_123.json

# Update only metadata.json
python update_transcripts.py --metadata

# Download only a new transcript
python update_transcripts.py --transcript transcript_123.json

# Force overwrite existing files without confirmation
python update_transcripts.py --metadata --transcript transcript_123.json --force

Options:
    --metadata: Update metadata.json file
    --transcript FILENAME: Download specific transcript file
    --force: Skip confirmation and overwrite existing files
    --verify: Verify downloaded files (default: True)

Note: For initial project setup or complete database refresh, use download_transcripts.py instead.
"""

import os
import boto3
import logging
import sys
import json
from dotenv import load_dotenv
import time
from datetime import datetime
import argparse

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_aws_credentials():
    """Verify that AWS credentials are properly configured."""
    required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'S3_BUCKET']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required AWS environment variables: {', '.join(missing_vars)}")
        logger.error("Please ensure these are set in your .env file")
        sys.exit(1)
    
    try:
        # Test AWS credentials by checking access to the specific bucket
        s3 = boto3.client('s3')
        bucket = os.getenv('S3_BUCKET')
        # List objects in bucket - this is what download_transcripts.py uses
        s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
        logger.info(f"AWS credentials verified successfully for bucket: {bucket}")
        return True
    except Exception as e:
        logger.error(f"AWS credentials verification failed: {str(e)}")
        logger.error("Please ensure your AWS user has s3:ListBucket permission for the specified bucket")
        sys.exit(1)

def verify_transcript(file_path):
    """Verify that the downloaded transcript is a valid JSON file."""
    try:
        with open(file_path, 'r') as f:
            json.load(f)  # Verify it's valid JSON
        logger.info(f"Successfully verified transcript file: {os.path.basename(file_path)}")
        return True
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in file: {file_path}")
        return False
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {str(e)}")
        return False

def verify_metadata(metadata_path):
    """Verify that metadata.json is valid and contains expected structure."""
    try:
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
            # Verify it's a list
            if not isinstance(metadata, list):
                logger.error("Metadata file is not a valid JSON array")
                return False
            # Count and log the number of records
            record_count = len(metadata)
            logger.info(f"Metadata file contains {record_count} records")
            return True
    except json.JSONDecodeError:
        logger.error("Invalid JSON in metadata file")
        return False
    except Exception as e:
        logger.error(f"Error reading metadata file: {str(e)}")
        return False

def check_file_exists(file_path, force=False):
    """Check if file exists and handle user confirmation."""
    if os.path.exists(file_path):
        if not force:
            response = input(f"File {os.path.basename(file_path)} already exists. Overwrite? (y/n): ").lower()
            if response != 'y':
                logger.info("Operation cancelled by user")
                return False
        logger.info(f"Overwriting existing file: {os.path.basename(file_path)}")
    return True

def update_transcripts(transcript_filename=None, download_metadata=False, force=False, verify=True):
    start_time = time.time()
    logger.info(f"Starting update process at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Verify AWS credentials first
        verify_aws_credentials()
        
        # Get environment variables
        data_dir = os.getenv('DATA_DIR', './data')
        bucket = os.getenv('S3_BUCKET')
        
        # Initialize S3 client
        s3 = boto3.client('s3')
        
        # Handle metadata download
        if download_metadata:
            metadata_path = os.path.join(data_dir, 'metadata.json')
            if check_file_exists(metadata_path, force):
                logger.info(f"Downloading metadata.json from {bucket}")
                try:
                    s3.download_file(bucket, 'metadata.json', metadata_path)
                    logger.info(f"Downloaded metadata.json to {metadata_path}")
                    if verify and not verify_metadata(metadata_path):
                        logger.error("Metadata verification failed")
                        sys.exit(1)
                except Exception as e:
                    logger.error(f"Error downloading metadata: {str(e)}")
                    sys.exit(1)
        
        # Handle transcript download
        if transcript_filename:
            if not transcript_filename.startswith('transcript_') or not transcript_filename.endswith('.json'):
                logger.error("Invalid transcript filename. Must start with 'transcript_' and end with '.json'")
                sys.exit(1)
            
            # Verify file exists in S3 before attempting download
            try:
                s3.head_object(Bucket=bucket, Key=transcript_filename)
            except Exception as e:
                logger.error(f"Transcript file {transcript_filename} not found in S3 bucket")
                sys.exit(1)
                
            transcript_dir = os.path.join(data_dir, 'transcripts')
            local_path = os.path.join(transcript_dir, transcript_filename)
            
            # Create transcript directory if it doesn't exist
            os.makedirs(transcript_dir, exist_ok=True)
            
            if check_file_exists(local_path, force):
                logger.info(f"Downloading {transcript_filename} from {bucket}")
                try:
                    s3.download_file(bucket, transcript_filename, local_path)
                    logger.info(f"Downloaded {transcript_filename} to {local_path}")
                    if verify and not verify_transcript(local_path):
                        logger.error("Transcript verification failed")
                        sys.exit(1)
                except Exception as e:
                    logger.error(f"Error downloading transcript: {str(e)}")
                    sys.exit(1)
        
        duration = time.time() - start_time
        logger.info(f"Update process completed in {duration:.2f} seconds")
        return True
        
    except Exception as e:
        logger.error(f"Error in update process: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Update transcripts and metadata in an existing setup')
    parser.add_argument('--metadata', action='store_true', help='Update metadata.json file')
    parser.add_argument('--transcript', help='Name of the transcript file to download (e.g., transcript_123.json)')
    parser.add_argument('--force', action='store_true', help='Skip confirmation and overwrite existing files')
    parser.add_argument('--verify', action='store_true', default=True, help='Verify downloaded files (default: True)')
    args = parser.parse_args()
    
    if not args.metadata and not args.transcript:
        parser.error("At least one of --metadata or --transcript must be specified")
    
    update_transcripts(
        transcript_filename=args.transcript,
        download_metadata=args.metadata,
        force=args.force,
        verify=args.verify
    ) 