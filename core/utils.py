import os
import logging
import requests
from typing import Optional, Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_required_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value

NEYNAR_KEY = get_required_env_var("NEYNAR_API_KEY")

# Initialize the Neynar client
NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"

NEYNAR_HEADERS = {
    "x-api-key": NEYNAR_KEY,
    "accept": "application/json",
    "content-type": "application/json"    
}


def format_timestamp(seconds: float) -> str:
    """Convert seconds to readable timestamp format (MM:SS or HH:MM:SS)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"


def get_conversation_history_DEPRECATED(first_cast_hash):
    """
    Fetches the conversation history for a given cast hash using a recursive approach to build complete thread history.    
    Returns the formatted conversation as a string so the bot has memory and can have a back and forth conversatin.
    This function has been replaced by get_conversation_summary() which uses a neynar API but is kept for reference or potential future use.

    """
    conversation = []
    depth = 0
    initial_author_fid = None
    last_author_fid = None
    bot_account_fid = 885236  # Your bot's FID
    
    def fetch_cast(hash: str) -> dict:
        response = requests.get(
            f"{NEYNAR_CAST_URL}",
            params={"identifier": hash, "type": "hash"},
            headers=NEYNAR_HEADERS
        )
        response.raise_for_status()
        return response.json()["cast"]
    
    def build_thread(current_hash: str):
        nonlocal initial_author_fid, depth, last_author_fid
        cast_data = fetch_cast(current_hash)
        current_author_fid = cast_data["author"]["fid"]

        if initial_author_fid is None:
            initial_author_fid = cast_data["author"]["fid"]
        
        print(f'IN RECURSIVE FUNCTION\nDEPTH: {depth}\nCAST AUTHOR: {cast_data["author"]["username"]}\nCAST TEXT: {cast_data["text"][:15]}...')

        # Only process if this is a valid author AND either:
        # 1. This is the first message (last_author_fid is None) OR
        # 2. The last author was different from the current author
        if (current_author_fid in [initial_author_fid, bot_account_fid] and 
            (last_author_fid is None or last_author_fid != current_author_fid)):
            
            if cast_data.get("parent_hash"):
                last_author_fid = current_author_fid  # Update last author
                depth += 1
                build_thread(cast_data["parent_hash"])
            
            conversation.append({
                "text": cast_data["text"],
                "author": cast_data["author"]["username"],
                "timestamp": cast_data["timestamp"]
            })
    
    try:
        build_thread(first_cast_hash)
        # Format the conversation into a string
        formatted_conversation = "\n".join(
            f"{msg['author']}: {msg['text']}" 
            for msg in conversation
        )
        return formatted_conversation, depth
        
    except Exception as e:
        print(f"Error getting conversation history: {e}")
        return "", 0
