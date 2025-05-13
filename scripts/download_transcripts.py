"""
Transcript Download and Verification Script
=========================================

This script is designed to be run once at application startup or anytime new transcripts are added to the S3 bucket 
to ensure the latest transcripts are available locally. It handles downloading and verifying both metadata and transcript files
from either S3 (production) or local sample data (development).

Key Features:
------------
1. Dual mode operation (sample/production)
2. Downloads metadata.json and all transcript files
3. Verifies all files are valid JSON
4. Performs a full refresh (deletes existing files)
5. Provides detailed timing information

Environment Variables Required:
----------------------------
- USE_SAMPLES: Set to true to use sample data, false for production
- DATA_DIR: Base directory for storing files (defaults to './data')
- S3_BUCKET: Name of the S3 bucket containing the files (production mode only)
- AWS_ACCESS_KEY_ID: AWS access key for S3 access (production mode only)
- AWS_SECRET_ACCESS_KEY: AWS secret key for S3 access (production mode only)

File Structure:
--------------
Sample Mode:
- Source: ./data/sample_transcripts/sample_metadata.json and ./data/sample_transcripts/*
- Destination: ./data/metadata.json and ./data/transcripts/*

Production Mode:
- Source: S3 bucket (metadata.json and transcript_*.json)
- Destination: ./data/metadata.json and ./data/transcripts/*

Process Flow:
------------
1. Load environment variables and initialize logging
2. Determine operation mode (sample/production)
3. Clean existing data directory
4. Copy/download files based on mode
5. Verify all files
6. Log timing information

Error Handling:
--------------
- Exits with code 1 if any step fails
- Provides detailed error messages
- Verifies file integrity before proceeding

Usage:
------
Run at application startup to ensure latest transcripts are available:
    python download_transcripts.py

Author: GM Farcaster Network

TO DO: 
- Add a check to only download transcripts if they are new or have changed
"""

import os
import boto3
import logging
import sys
import json
import shutil
from dotenv import load_dotenv
import time
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def format_duration(seconds):
    """Format duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    minutes = int(seconds // 60)
    seconds = seconds % 60
    return f"{minutes} minutes and {seconds:.2f} seconds"

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

def verify_transcripts(directory):
    """Verify that downloaded transcripts are valid JSON files."""
    if not os.path.exists(directory):
        logger.error(f"Transcript directory {directory} does not exist")
        return False
    
    files = [f for f in os.listdir(directory) if f.startswith('transcript_') and f.endswith('.json')]
    if not files:
        logger.error("No transcript files found in directory")
        return False
    
    for file in files:
        try:
            with open(os.path.join(directory, file), 'r') as f:
                json.load(f)  # Verify it's valid JSON
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in file: {file}")
            return False
        except Exception as e:
            logger.error(f"Error reading file {file}: {str(e)}")
            return False
    
    logger.info(f"Successfully verified {len(files)} transcript files")
    return True

def setup_sample_data(data_dir):
    """Set up sample data by copying from sample directories."""
    start_time = time.time()
    logger.info("Setting up sample data")
    
    # Define paths
    sample_metadata = os.path.join(data_dir, 'sample_transcripts', 'sample_metadata.json')
    sample_transcripts = os.path.join(data_dir, 'sample_transcripts')
    metadata_path = os.path.join(data_dir, 'metadata.json')
    transcript_dir = os.path.join(data_dir, 'transcripts')
    
    # Verify source files exist
    if not os.path.exists(sample_metadata):
        logger.error(f"Sample metadata file not found: {sample_metadata}")
        return False
    if not os.path.exists(sample_transcripts):
        logger.error(f"Sample transcripts directory not found: {sample_transcripts}")
        return False
    
    # Clean and recreate directories
    if os.path.exists(metadata_path):
        os.remove(metadata_path)
    if os.path.exists(transcript_dir):
        shutil.rmtree(transcript_dir)
    os.makedirs(transcript_dir, exist_ok=True)
    
    # Copy metadata
    try:
        shutil.copy2(sample_metadata, metadata_path)
        logger.info("Copied sample metadata")
    except Exception as e:
        logger.error(f"Error copying sample metadata: {str(e)}")
        return False
    
    # Copy transcript files
    try:
        for file in os.listdir(sample_transcripts):
            if file.startswith('transcript_') and file.endswith('.json'):
                src = os.path.join(sample_transcripts, file)
                dst = os.path.join(transcript_dir, file)
                shutil.copy2(src, dst)
        logger.info("Copied sample transcripts")
    except Exception as e:
        logger.error(f"Error copying sample transcripts: {str(e)}")
        return False
    
    # Verify the copied files
    if not verify_metadata(metadata_path) or not verify_transcripts(transcript_dir):
        logger.error("Verification of sample data failed")
        return False
    
    duration = time.time() - start_time
    logger.info(f"Sample data setup completed in {format_duration(duration)}")
    return True

def download_transcripts():
    start_time = time.time()
    logger.info(f"Starting download process at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Get environment variables from .env file
        use_samples = os.getenv('USE_SAMPLES', 'true').lower() == 'true'
        data_dir = os.getenv('DATA_DIR', './data')
        
        logger.info(f"Using data directory: {data_dir}")
        logger.info(f"Mode: {'Sample' if use_samples else 'Production'}")
        
        if use_samples:
            return setup_sample_data(data_dir)
        
        # Production mode - get S3 configuration
        bucket = os.getenv('S3_BUCKET')
        if not bucket:
            logger.error("S3_BUCKET environment variable not set")
            sys.exit(1)
            
        transcript_dir = os.path.join(data_dir, 'transcripts')
        metadata_path = os.path.join(data_dir, 'metadata.json')
        
        # Clean and recreate directories
        if os.path.exists(metadata_path):
            os.remove(metadata_path)
        if os.path.exists(transcript_dir):
            shutil.rmtree(transcript_dir)
        os.makedirs(transcript_dir, exist_ok=True)
        
        # Initialize S3 client
        s3 = boto3.client('s3')
        
        # Download and verify metadata first
        metadata_start = time.time()
        logger.info("Downloading metadata.json")
        try:
            s3.download_file(bucket, 'metadata.json', metadata_path)
            if not verify_metadata(metadata_path):
                logger.error("Metadata verification failed")
                sys.exit(1)
            metadata_duration = time.time() - metadata_start
            logger.info(f"Metadata download and verification completed in {format_duration(metadata_duration)}")
        except Exception as e:
            logger.error(f"Error downloading metadata: {str(e)}")
            sys.exit(1)
        
        # List and download transcript files
        transcripts_start = time.time()
        logger.info(f"Downloading transcripts from {bucket} to {transcript_dir}")
        objects = s3.list_objects_v2(Bucket=bucket).get('Contents', [])
        transcript_objects = [obj for obj in objects if obj['Key'].startswith('transcript_') and obj['Key'].endswith('.json')]
        
        if not transcript_objects:
            logger.error("No transcript files found in S3 bucket")
            sys.exit(1)
            
        downloaded_files = []
        for obj in transcript_objects:
            key = obj['Key']
            local_path = os.path.join(transcript_dir, os.path.basename(key))
            logger.info(f"Downloading {key} to {local_path}")
            s3.download_file(bucket, key, local_path)
            downloaded_files.append(local_path)
        
        if not downloaded_files:
            logger.error("No transcript files were downloaded")
            sys.exit(1)
            
        logger.info(f"Downloaded {len(downloaded_files)} transcript files")
        
        # Verify the downloaded transcript files
        if not verify_transcripts(transcript_dir):
            logger.error("Transcript verification failed")
            sys.exit(1)
            
        transcripts_duration = time.time() - transcripts_start
        logger.info(f"Transcript download and verification completed in {format_duration(transcripts_duration)}")
        
        total_duration = time.time() - start_time
        logger.info(f"Total process completed in {format_duration(total_duration)}")
        return True
        
    except Exception as e:
        logger.error(f"Error in download process: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    download_transcripts() 