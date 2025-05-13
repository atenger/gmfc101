from typing import Literal, Dict
from core.workflow_metadatapath import MetadataPath
import json
import logging
from core.utils import get_required_env_var
from prompts.workflow_prompts import ROUTING_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set logging level based on environment variable
VERBOSE_LOGGING = get_required_env_var("VERBOSE_LOGGING").lower() == 'true'
if VERBOSE_LOGGING:
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug logging ON")

class WorkflowRouter:
    def __init__(self, openai_client):
        logger.debug("WorkflowRouter init - OpenAI client: %s", openai_client)
        self.openai_client = openai_client
        self.metadata_handler = MetadataPath(openai_client)
        self.routing_prompt = ROUTING_PROMPT
        
    def route_query(self, query: str) -> str:
        """
        Main routing function that determines the appropriate path for a query.
        Returns: str - One of: "metadata", "contextual", "hybrid", or "other"
        """
        try:
            if not query or query.isspace():
                logger.debug("Query is empty or whitespace only")
                return "other"
            
            messages = [
                {"role": "system", "content": self.routing_prompt},
                {"role": "user", "content": query}
            ]
            
            logger.info("Messages being sent to OpenAI: %s", json.dumps(messages, indent=2))
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                temperature=0
            )
            
            llm_response = response.choices[0].message.content.strip()
            logger.info("LLM Workflow Router response: '%s'", llm_response)
            
            # Convert response to lowercase for case-insensitive matching
            llm_response = llm_response.lower()
            
            path_mapping = {
                "metadata": "metadata",
                "contextual": "contextual",
                "hybrid": "hybrid",
                "ignore": "ignore"  # Added new category
            }
            
            final_path = path_mapping.get(llm_response, "other")
            logger.info("Selected path: %s", final_path)
            
            return final_path
            
        except Exception as e:
            logger.error("Error in route_query: %s", str(e))
            logger.error("Error type: %s", type(e))
            return "other"
