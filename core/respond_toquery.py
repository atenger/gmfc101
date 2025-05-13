from flask import jsonify
from pinecone import Pinecone
from openai import OpenAI
import time
from cachetools import TTLCache
import requests
from collections import defaultdict
from typing import Optional
import logging
from core.workflow_router import WorkflowRouter
from core.workflow_metadatapath import MetadataPath
from core.workflow_contextpath import ContextualPath
from core.workflow_hybridpath import HybridPath
from core.utils import get_required_env_var

# Configure logging
logging.basicConfig(level=logging.INFO)  # Set default level to INFO
logger = logging.getLogger(__name__)

# Set logging level based on environment variable
VERBOSE_LOGGING = get_required_env_var("VERBOSE_LOGGING").lower() == 'true'
if VERBOSE_LOGGING:
    logger.setLevel(logging.DEBUG)


# Print current logging level
current_level = logger.getEffectiveLevel()
level_name = logging.getLevelName(current_level)
logger.info(f"Current logging level: {level_name}")

BOT_ACCOUNT_FID = get_required_env_var("BOT_ACCOUNT_FID")


# Initialize cache for processed casts
processed_casts = TTLCache(maxsize=1000, ttl=300)

def format_timestamp(seconds: float) -> str:
    """Convert seconds to readable timestamp format (MM:SS or HH:MM:SS)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"






def get_conversation_summary(cast_hash, neynar_headers, dry_run):    
    """
    Fetches a summary of the conversation thread from Neynar API. 
    Does not give the full back and forth conversation just between bot and user, but rather a summary of the thread.
    """
    try:
        NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"
        response = requests.get(
            f"{NEYNAR_CAST_URL}/conversation/summary",
            params={"identifier": cast_hash, "type": "hash"},
            headers=neynar_headers
        )
        response.raise_for_status()
        
        summary = response.json().get("summary", {}).get("text", "No summary available")       
        return summary

    except Exception as e:
        logger.error(f"Error getting conversation summary: {e}")
        return "No summary available right now."


def get_conversation_history_recursive(cast_hash, author_fid, neynar_headers, dry_run=False) -> tuple[list, int]:
    """
    Uses recursive approach to build complete chat between bot and user.
    Returns the conversation as a formatted message array for the LLM, excluding the current query.
    Messages from the bot are marked as "assistant" and messages from the user are marked as "user".
    Only includes the direct conversation between the original author and the bot.
    Returns a tuple of (messages, depth)
    """
    messages = []
    last_author_fid = None
    conversation_started = False
    depth = 0
    
    NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"
    
    def fetch_cast(hash: str) -> dict:
        response = requests.get(
            f"{NEYNAR_CAST_URL}",
            params={"identifier": hash, "type": "hash"},
            headers=neynar_headers
        )
        response.raise_for_status()
        return response.json()["cast"]
    
    def build_thread(current_hash: str):
        nonlocal last_author_fid, conversation_started, depth
        cast_data = fetch_cast(current_hash)
        
        current_author_fid = str(cast_data["author"]["fid"])
        author_fid_str = str(author_fid)
        bot_fid_str = str(BOT_ACCOUNT_FID)
        
        logger.debug(f"\nProcessing cast to buid conversation history: {current_hash} | Author FID: {author_fid} ")
        
        # Check if this message is from a valid participant
        is_valid_participant = current_author_fid in [author_fid_str, bot_fid_str]
        
        # If we've started the conversation and hit an invalid participant, stop traversing
        if conversation_started and not is_valid_participant:
            logger.debug("❌ Breaking conversation chain - found message from another user")
            return
            
        # If this is a valid participant, mark conversation as started
        if is_valid_participant:
            conversation_started = True
            
            # Only process parent if we're still in the valid conversation
            if cast_data.get("parent_hash"):
                # Increment depth when speaker changes
                if last_author_fid is None or last_author_fid != current_author_fid:
                    depth += 1
                build_thread(cast_data["parent_hash"])
            
            # Check if it's a different speaker from last message
            is_different_speaker = last_author_fid is None or last_author_fid != current_author_fid
            
            if is_different_speaker:
                logger.debug(f"✅ Adding message to history: {cast_data['text'][:50]}...")
                messages.append({
                    "role": "user" if current_author_fid == author_fid_str else "assistant",
                    "content": cast_data["text"]
                })
                last_author_fid = current_author_fid
    
    try:
        build_thread(cast_hash)
        # Return tuple of (messages without current query, depth)
        return messages[:-1] if messages else [], depth
        
    except Exception as e:
        logger.error(f"Error constructing conversation history: {e}")
        return [], 1 if dry_run else 999


        
        
        
     



def get_conversation_depth_DEPRECATED(cast_hash, neynar_headers, dry_run=False):
    """
    Fetches the depth of the conversation thread.
    DECPECATING this function b/c we are going to use the recursive function above to get the conversation history and depth.
    """
    depth = 0
    initial_author_fid = None
    last_author_fid = None
    
    NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"
    
    def fetch_cast(hash: str) -> dict:
        response = requests.get(
            f"{NEYNAR_CAST_URL}",
            params={"identifier": hash, "type": "hash"},
            headers=neynar_headers
        )
        response.raise_for_status()
        return response.json()["cast"]
    
    def build_thread(current_hash: str):
        nonlocal initial_author_fid, depth, last_author_fid
        cast_data = fetch_cast(current_hash)
        current_author_fid = cast_data["author"]["fid"]

        if initial_author_fid is None:
            initial_author_fid = cast_data["author"]["fid"]

        if (current_author_fid in [initial_author_fid, BOT_ACCOUNT_FID] and 
            (last_author_fid is None or last_author_fid != current_author_fid)):
            
            if cast_data.get("parent_hash"):
                last_author_fid = current_author_fid
                depth += 1
                build_thread(cast_data["parent_hash"])
    
    try:
        build_thread(cast_hash)
        return depth
        
    except Exception as e:
        logger.error(f"Error getting conversation depth: {e}")
        return 1 if dry_run else 999

def truncate_to_byte_limit(text: str, limit: int = 1000) -> str:
    """
    Smartly truncate text to stay under byte limit while preserving complete sentences.
    """
    if len(text.encode('utf-8')) <= limit:
        return text
        
    # Leave room for truncation notice
    working_limit = limit - len(" [...response too long, truncating. cc: @adrienne]".encode('utf-8'))
    
    # Convert to bytes to handle UTF-8 characters correctly
    encoded = text.encode('utf-8')
    truncated = encoded[:working_limit].decode('utf-8', 'ignore')
    
    # Find the last complete sentence
    last_sentence = max(
        truncated.rfind('.'),
        truncated.rfind('!'),
        truncated.rfind('?')
    )
    
    if last_sentence > 0:
        truncated = truncated[:last_sentence + 1]
    
    logger.info(f"TRUNCATED RESPONSE: {truncated} [...response too long, truncating. cc: @adrienne]")
    return truncated + " [...response too long, truncating. cc: @adrienne]"

def post_reply_to_neynar(payload, neynar_headers, dry_run=False):
    """
    Accepts a payload containing the LLM response.
    Will truncate the response if it's too long for Farcaster's length limit.
    Will not post the reply if dry_run is True.
    Finally, uses Neynar to send the cast.
    """
    NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"
    TIMEOUT_SECONDS = 10
        
    try:
        # Ensure text fits within Neynar's byte limit
        logger.info(f"RAW LLM RESPONSE: {payload['text']}")

        payload['text'] = truncate_to_byte_limit(payload['text'])
       

        if dry_run:
            logger.warning("DRY_RUN_SIMULATION: Reply will not be posted to Neynar")
            return
        
        response = requests.post(
            NEYNAR_CAST_URL, 
            json=payload, 
            headers=neynar_headers,
            timeout=TIMEOUT_SECONDS
        )
        
        if response.status_code != 200:
            logger.error(f"Neynar API error response: {response.text}")
            logger.error(f"Status code: {response.status_code}")
        
        response.raise_for_status()
        logger.info(f"REPLY SUCCESSFULLY POSTED TO NEYNAR...")
    except requests.Timeout:
        logger.error("Timeout while posting reply to Neynar")
        raise
    except requests.RequestException as e:
        logger.error(f"Error posting reply to Neynar: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Error response from Neynar: {e.response.text}")
        raise


def handle_webhook_v2(data, openai_client, pinecone_index, neynar_headers, neynar_signer_uuid, use_llm=True, dry_run=False):
    """
    V2 of the webhook handler - now with workflow routing
    This is the MAIN function which is called from api.py which is called every time GMFC101 is tagged in Farcaster.
    """
    try:
        logger.debug("ENTERED WEBHOOK HANDLER...")  

        """
        STEP 1: Validate incoming data and exit if any validation fails
        """
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        if 'type' not in data:
            return jsonify({"error": "Missing event type"}), 400
        
        event_type = data.get('type')
        if event_type != "cast.created":            
            return jsonify({"status": "Event type was not cast.created; ignoring request"}), 200

        """
        STEP 2: Webhook Dedupe logic
        Get the cast_hash and check if it's already been processed; if it has, then exit; if it hasn't, add to the cache continue with processing        
        """
        
        cast_data = data.get('data', {})
        cast_hash = cast_data.get('hash')

        if cast_hash in processed_casts and not dry_run:
            logger.warning(f"DUPLICATE EVENT DETECTED FOR CAST: {cast_hash}. IGNORING...")
            return jsonify({"status": "ignored duplicate"}), 200

        # Mark this cast hash as processed  
        processed_casts[cast_hash] = time.time()
        logger.debug(f"CAST HASH DEEMED UNIQUE. CONTINUING...")      
        
        """
        STEP 3: Extract the cast text and author from the cast.
        If the author is the bot itself, exit b/c we don't want to reply to ourself.
        TODO: Add checks on author FID to ignore spam users and/or other bots (OPTIONAL)
        """
        cast_text = cast_data.get('text', '')      
        author = cast_data.get('author', {}).get('username', 'Unknown')          
        author_fid = str(cast_data.get('author', {}).get('fid', '0'))

        if author_fid == str(BOT_ACCOUNT_FID):
            logger.warning("BOT MENTIONED ITSELF IN CAST. IGNORING...")
            return jsonify({"status": "Bot tagged itself; ignoring and not replying..."}), 200

        try:
            if use_llm:
                """
                STEP 4: Get thread context and history to be passed into the LLM
                Conversation summary is the neynar generated summary of a conversation thread.
                Conversation history is the full conversation thread between the bot and the user.
                Conversation depth is the depth of the conversation thread (number of replies, used to prevent infinite chats between 2 bots and/or control spam and cost).
                """                
                conversation_summary = get_conversation_summary(cast_hash, neynar_headers, dry_run)                
                conversation_history, depth = get_conversation_history_recursive(cast_hash, author_fid, neynar_headers, dry_run)
                
                logger.debug(f"CONVERSATION HISTORY: {conversation_history}")
                logger.debug(f"CONVERSATION SUMMARY: {conversation_summary}")        
                logger.debug(f"CONVERSATION DEPTH: {depth}")

                # Check if the conversation depth exceeds the limit
                if depth > 8:
                    logger.warning(f"CONVERSATION DEPTH {depth} EXCEEDS LIMIT. NOT RESPONDING...")
                    return jsonify({"status": "conversation depth limit reached"}), 200

                """
                STEP 5: Workflow Routing
                Use an LLM to determine the best workflow to use for the query. Options are:
                - Metadata: Use metadata as its source
                - Contextual: Use the LLM and RAG context
                - Hybrid: Use a hybrid of the two
                """                       
                router = WorkflowRouter(openai_client)
                route_result = router.route_query(cast_text)
                logger.info(f"ROUTE DETERMINED: {route_result}")  
                
                
                # Use the router's response
                if route_result == "metadata":
                    # Handle metadata query using MetadataPath
                    metadata_handler = MetadataPath(openai_client)
                    llm_response = metadata_handler.handle_query(
                        query=cast_text,
                        user_name=author,
                        conversation_history=conversation_history,
                        conversation_summary=conversation_summary,
                        depth=depth
                    )
                elif route_result == "contextual":
                    # Handle contextual queries using ContextualPath
                    
                    contextual_handler = ContextualPath(openai_client)
                    llm_response = contextual_handler.handle_query(
                        query=cast_text,
                        user_name=author,
                        conversation_history=conversation_history,
                        conversation_summary=conversation_summary,
                        pinecone_index=pinecone_index,
                        depth=depth
                    )
                elif route_result == "hybrid":
                    # Handle hybrid queries                    
                    hybrid_handler = HybridPath(openai_client)
                    llm_response = hybrid_handler.handle_query(
                        query=cast_text,
                        user_name=author,
                        conversation_history=conversation_history,
                        conversation_summary=conversation_summary,                        
                        depth=depth
                    )
                elif route_result == "ignore":
                    logger.warning(f"IGNORE QUERY DETECTED. NOT RESPONDING...")
                    return jsonify({"status": "ignore query detected"}), 200
                else:
                    # Fallback for any other route_result values
                    contextual_handler = ContextualPath(openai_client)
                    llm_response = contextual_handler.handle_query(
                        query=cast_text,
                        user_name=author,
                        conversation_history=conversation_history,
                        conversation_summary=conversation_summary,
                        pinecone_index=pinecone_index,
                        depth=depth
                    )
            else:
                llm_response = (
                    f"Hey @{author}! 👋 I'm a bot that will help with Farcaster questions but "
                    f"I'm still being developed and take frequent rests! I'm offline now but you can check back later."
                )
            
            payload = {
                "text": llm_response,
                "signer_uuid": neynar_signer_uuid,
                "parent": cast_hash
            }

            
            post_reply_to_neynar(payload, neynar_headers, dry_run)     
            

        except Exception as e:
            logger.error(f"Error posting reply: {e}")
            return jsonify({"error": "Unknown error"}), 500

        logger.info("WEBHOOK PROCESSING COMPLETE... SENDING RESPONSE CODE 200 to NEYNAR")
        return jsonify({"message": "Webhook processed"}), 200

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


