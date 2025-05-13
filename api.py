from flask import Flask, request, jsonify
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI
import os
from cachetools import TTLCache
import requests
import logging
from core.respond_toquery import handle_webhook_v2
from core.utils import get_required_env_var
from datetime import datetime
import time



# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set logging level based on environment variable
VERBOSE_LOGGING = get_required_env_var("VERBOSE_LOGGING").lower() == 'true'
if VERBOSE_LOGGING:
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug logging ON")


# Environment variables with validation
PINECONE_API_KEY = get_required_env_var("PINECONE_API_KEY")
ENVIRONMENT = get_required_env_var("PINECONE_ENVIRONMENT")
PINECONE_INDEX_NAME = get_required_env_var("PINECONE_INDEX_NAME")
OPENAI_KEY = get_required_env_var("OPENAI_API_KEY")
NEYNAR_KEY = get_required_env_var("NEYNAR_API_KEY")
NEYNAR_SIGNER_UUID = get_required_env_var("NEYNAR_BOT_SIGNER_UUID")
DRY_RUN_SIMULATION = os.getenv("DRY_RUN_SIMULATION", "false").lower() == "true"
USE_LLM = os.getenv("USE_LLM", "true").lower() == "true"

# Add timeouts to API clients
TIMEOUT_SECONDS = 10

app = Flask(__name__)

# Updated Pinecone initialization
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)

# Initialize the OpenAI client
openai_client = OpenAI(api_key=OPENAI_KEY)

# Initialize the Neynar client
NEYNAR_CAST_URL = "https://api.neynar.com/v2/farcaster/cast"

NEYNAR_HEADERS = {
    "x-api-key": NEYNAR_KEY,
    "accept": "application/json",
    "content-type": "application/json"    
}

# Create a cache to store processed cast hashes with a TTL to avoid duplicate replies
processed_casts = TTLCache(maxsize=1000, ttl=300)  # Stores up to 1000 hashes for 5 minutes




@app.route("/")
def home():
    return jsonify({"message": "API is running!"})


@app.route("/gm", methods=["POST"])
def post_gm():
    ### Use this end point to post a top level cast from the bot;
    ### Used to test the bot's functionality from postman 
    try:
        cast_text = "I have access to hundreds of hours of GM Farcaster Network content. Ask me a question and I'll do my best to answer it."
        #cast_text = "gm ☕🌞"
        #cast_text = "hello from the command line 👋"

        payload = {            
            "text": cast_text,            
            "signer_uuid": NEYNAR_SIGNER_UUID
        }
        response = requests.post(NEYNAR_CAST_URL, json=payload, headers=NEYNAR_HEADERS)       
       
        print (response.text)
        return jsonify({"message": "Cast created successfully"}), 200
    
    except Exception as e:
        print(f"Error creating cast: {str(e)}")
        return jsonify({"error": "Failed to create cast"}), 500



@app.route("/test_webhook", methods=["POST"])
def test_webhook():
    ### Use this end point to test the LLM response    
    ### Accepts a cast URL, creates the JSON payload that would be sent to the webhook 
    ### This will then call the webhook handler to generate a response, but response will not be posted to Farcaster
    
    try:
        # Get the cast URL from the POST request
        data = request.get_json()
        cast_url = data.get("cast_url")
        
        if not cast_url:
            return jsonify({"error": "cast_url is required"}), 400

        logger.debug(f"Received cast URL: {cast_url}")

        # Hydrate the cast using Neynar
        response = requests.get(
            f"{NEYNAR_CAST_URL}",
            params={"identifier": cast_url, "type": "url"},
            headers=NEYNAR_HEADERS
        )
        response.raise_for_status()
        cast_data = response.json()["cast"]
        
        logger.debug(f"Retrieved cast data: {cast_data}")
        
        # Parse the ISO timestamp to Unix timestamp
        timestamp_str = cast_data["timestamp"]
        dt = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        unix_timestamp = int(time.mktime(dt.timetuple()))
        
        # Create the webhook payload
        webhook_payload = {
            "data": cast_data,
            "type": "cast.created",
            "created_at": unix_timestamp,
            "event_timestamp": timestamp_str
        }
        
        logger.debug(f"Created webhook payload: {webhook_payload}")
        
        # Call the workflow to simulate a response
        webhook_response, status_code = handle_webhook_v2(
            data=webhook_payload,
            openai_client=openai_client,
            pinecone_index=index,
            neynar_headers=NEYNAR_HEADERS,
            neynar_signer_uuid=NEYNAR_SIGNER_UUID,
            use_llm=True,
            dry_run=True
        )
        
        # Extract the response data from the webhook response
        response_data = webhook_response.get_json()
        
        logger.debug(f"Webhook response: {response_data}")
        
        return jsonify({
            "webhook_response": response_data,
            "status_code": status_code,
            "cast_data": cast_data
        })

    except Exception as e:
        logger.error(f"Error type: {type(e)}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Error location: {e.__traceback__.tb_frame.f_code.co_name}")
        return jsonify({"error": "An error occurred processing your request"}), 500




@app.route('/webhook_v2', methods=['POST'])
def handle_webhook_v2_endpoint():
    try:
        
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400

        data = request.get_json()
        
        return handle_webhook_v2(
            data=data,
            openai_client=openai_client,
            pinecone_index=index,
            neynar_headers=NEYNAR_HEADERS,
            neynar_signer_uuid=NEYNAR_SIGNER_UUID,
            use_llm=USE_LLM,
            dry_run=DRY_RUN_SIMULATION
        )
    
        

    except Exception as e:
        logger.error(f"Error in webhook_v2 endpoint: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(debug=True)
