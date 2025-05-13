import json
from typing import Dict, Optional, List, Any
import logging
import time
import tiktoken
import os
from prompts.metadata_prompts import get_farcaster_prompt_with_metadata_context

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set logging level based on environment variable
VERBOSE_LOGGING = os.getenv('VERBOSE_LOGGING', 'false').lower() == 'true'
if VERBOSE_LOGGING:
    logger.setLevel(logging.DEBUG)

class MetadataPath:
    def __init__(self, openai_client):
        logger.info("MetadataPath initialized with OpenAI client")  
        self.data_dir = os.getenv('DATA_DIR', './data')
        self.metadata = self._load_metadata()
        self.openai_client = openai_client
        # Define name mappings as a class attribute
        self.name_variations = {
            'dwr.eth': {'dan', 'dwr', 'dwr.eth', 'dan romero'},
            'heavygweit': {'erica', 'heavygweit'},
            'v': {'varun', 'v'},
            'afrochicks': {'afrochicks', 'naomi'},            
            'naomi': {'naomiii', 'naomi'},
            'proxystudio.eth': {'proxy', 'proxystudio', 'proxy studio', 'proxystudio.eth'},
            'ccarella': {'chris carella', 'ccarella'},
            'meonbase': {'meonbase', 'ceej'},
            'esteez.eth': {'esteez', 'emma'},
            'vpabundance': {'james', 'vpabundance'},
            's-mok-e': {'s-mok-e', 'smoke'},
            'fredwilson.eth': {'fred wilson', 'fred'},
        }
        
    def _load_metadata(self) -> List[Dict]:
        """
        Loads metadata from JSON file
        This gives this class access to the metadata for all episodes including:
        - youtube_url
        - episode  
        - hosts
        - series
        - companion_blog
        - title
        - aired_date
        - transcript_path   
        
        """
        try:
            metadata_path = os.path.join(self.data_dir, 'metadata.json')
            with open(metadata_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading metadata: {e}")
            return []
            
    def _prefilter_metadata(self, query: str) -> tuple[List[Dict], List[str]]:
        # Convert query to lowercase for easier matching
        query = query.lower()
        # Split query into words and remove punctuation for exact word matching
        # this way if someone mentions @heavygweit, or ends a sentence with heavygweit? it will still match
        query_words = set(word.strip('.,?!/@') for word in query.split())
        
        # Start with empty filtered set
        filtered_metadata = []
        mentioned_hosts = []  # We'll return this along with filtered metadata

        """
        FIRST FILTER STEP:
        If any host that has been on our show is mentioned in the query, get all those episodes to return
        """                

        # Flatten name variations for lookup
        name_lookup = {}
        for metadata_name, variations in self.name_variations.items():
            for variant in variations:
                name_lookup[variant.lower()] = metadata_name
        
        # Get all unique hosts from metadata for names not in our variations
        all_hosts = set()
        for episode in self.metadata:
            all_hosts.update(host.lower() for host in episode.get('hosts', []))
        
        # First, check if any variations appear in the query
        for variant in name_lookup:
            if variant in query_words:
                metadata_name = name_lookup[variant]
                if metadata_name not in mentioned_hosts:
                    mentioned_hosts.append(metadata_name)
        
        # Then check actual host names from metadata
        for host in all_hosts:
            if host.lower() in query_words:
                if host not in mentioned_hosts:
                    mentioned_hosts.append(host)
        
        # If hosts are mentioned, add those episodes
        if mentioned_hosts:
            host_episodes = [
                episode for episode in self.metadata
                if any(host.lower() in [h.lower() for h in episode.get('hosts', [])]
                      for host in mentioned_hosts)
            ]
            filtered_metadata.extend(host_episodes)
            logger.debug(f"Step 1 (Hosts): Added {len(host_episodes)} episodes for hosts {mentioned_hosts}")
        else:
            logger.debug("Step 1 (Hosts): No host matches found")
        
        """
        SECOND FILTER STEP:
        If any known series is mentioned in the query, add those episodes to our filtered set
        """
        series_variations = {
            'Special Event': {'special event', 'special'},
            'GM Farcaster': {'gmfarcaster', 'gm farcaster'},
            'Vibe Check': {'vibe check', 'vibecheck'},
            'The Hub': {'hub', 'the hub'},
            'Here for the Art': {'here for the art'},
            'Farcaster 101': {'farcaster 101'},
        }
        
        # Create a set of episodes we already have from host filtering
        filtered_episode_ids = {episode.get('episode') for episode in filtered_metadata}

        
        series_count = 0
        # Check for series mentions using the same word-based approach
        found_series = False
        for series_name, variations in series_variations.items():
            # Split multi-word variations into a set of possible matches
            all_variations = set()
            for variant in variations:
                all_variations.add(variant)
                all_variations.add(variant.replace(' ', ''))
            
            if any(variant in query_words or variant in query.lower() for variant in all_variations):
                found_series = True
                series_episodes = [
                    episode for episode in self.metadata
                    if episode.get('series') == series_name
                    and episode.get('episode') not in filtered_episode_ids
                ]
                filtered_metadata.extend(series_episodes)
                series_count += len(series_episodes)
        
        if found_series:
            logger.debug(f"Step 2 (Series): Added {series_count} new episodes")
        else:
            logger.debug("Step 2 (Series): No series matches found")
        
        """
        THIRD FILTER STEP:
        If any words from the query appear in episode titles, add those episodes to our filtered set
        """
        # Create a set of episodes we already have from previous filtering
        filtered_episode_ids = {episode.get('episode') for episode in filtered_metadata}
        
        # Get all words from titles for matching
        title_words = set()
        for episode in self.metadata:
            if episode.get('title'):
                # Split title into words and remove punctuation
                words = {word.strip('.,?!/').lower() for word in episode.get('title').split()}
                title_words.update(words)
        
        # Remove common words that we don't want to match on
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is',
                     'episode', 'farcaster', 'first', 'last', 'next', 'previous', 'guest', 'guests', 'what', 'you', 
                     'your', 'yours', 'this', 'that', 'there', 'here', 'where', 'when', 'how', 'why', 'all', 'any', 'some', 
                     'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'}
        title_words = title_words - stop_words
        
        # Check for matches between query words and title words
        matching_titles = []
        found_title_match = False  # Initialize the flag
        
        logger.debug(f"Query words after processing: {query_words}")
        logger.debug(f"Title words after processing: {title_words}")
        
        matching_words = []  # Track words that matched
        for word in query_words:
            if word in title_words and word not in stop_words:
                matching_words.append(word)
                logger.debug(f"Found matching word in title: {word}")
                # Find all episodes with this word in the title
                title_episodes = [
                    episode for episode in self.metadata
                    if episode.get('title') 
                    and word in {w.strip('.,?!/').lower() for w in episode.get('title').split()}
                    and episode.get('episode') not in filtered_episode_ids
                ]
                if title_episodes:
                    logger.debug(f"Episodes found for word '{word}':")
                    for ep in title_episodes:
                        logger.debug(f"  - {ep.get('title')}")
                matching_titles.extend(title_episodes)
                filtered_episode_ids.update(episode.get('episode') for episode in title_episodes)
                found_title_match = True  # Set the flag if we found matches
        
        if matching_titles:
            filtered_metadata.extend(matching_titles)
            logger.debug(f"Step 3 (Titles): Added {len(matching_titles)} new episodes")
            logger.debug(f"Words that matched titles: {', '.join(matching_words)}")
        else:
            logger.debug("Step 3 (Titles): No title matches found")
        
        # If no matches at all, return all metadata
        if not mentioned_hosts and not found_series and not found_title_match:
            filtered_metadata = self.metadata
            logger.debug("No matches found in any step - returning all metadata")
        
        # Final manipulation on the filtered metadata to be returned 
        filtered_metadata.sort(key=lambda x: x.get('aired_date', ''))
        
        logger.info(f"METADATA FILTERING FINAL RESULT: Returning {len(filtered_metadata)} total episodes")
        
        """
        FINAL STEP:
        Clean up the metadata to reduce token size
        """
        # Fields to remove from each episode
        fields_to_remove = {
            'companion_blog',
            'transcript_path',
            # Add any other fields that aren't needed
        }
        
        #if not mentioned_hosts and not found_series and not found_title_match:
        #    fields_to_remove.add('youtube_url')
       #    logger.debug("No matches found - removing youtube_url field")
        
        # Clean each episode dictionary
        cleaned_metadata = []
        for episode in filtered_metadata:
            cleaned_episode = {
                k: v for k, v in episode.items()
                if k not in fields_to_remove
            }
            cleaned_metadata.extend([cleaned_episode])

        
        return cleaned_metadata, mentioned_hosts
    
    
    
    def _check_token_count(self, data: str) -> int:
        """Check token count of data"""
        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(data))
    
    def handle_query(self, query: str, user_name: str, conversation_history: str, conversation_summary: str, depth: int) -> str:
        """
        Processes queries that should be able to be answered using metadata about the GM Farcaster Network's video library.
        It gets the metadata and passes it into the prompt for the LLM to use as additional context.    

        Args:
            query (str): The user's query 
            user_name (str): The username to mention in the response
            conversation_history (str): The conversation history if it's a thread
            depth (int): The depth of the conversation, so the bot can warn the user if the chat is getting too long
            
        Returns:
            str: Formatted response from the LLM
        """
        try:
            start_time = time.time()
            logger.debug("STARTING METADATA PATH QUERY PROCESSING...")
            
            # Get filtered metadata and mentioned hosts
            filtered_metadata, mentioned_hosts = self._prefilter_metadata(query)
            metadata_context = json.dumps(filtered_metadata)
            
            # Generate name mappings string
            name_mappings = self._generate_name_mapping_string(query, mentioned_hosts)
            
            # Check token count
            token_count = self._check_token_count(metadata_context)
            logger.debug(f"METADATA TOKEN COUNT: {token_count}")
            
            # Select model based on token count
            #if token_count < 7000:  # Leave some room for the rest of the prompt
            #    model = "gpt-4"
            #    logger.debug("GPT MODEL SELECTED: GPT-4 base for better accuracy")
            #else:
            #    model = "gpt-4-turbo"
            #    logger.debug("GPT MODEL SELECTED: GPT-4 Turbo due to large context size")


            # Set model to GPT-4o
            model = "gpt-4o"
            logger.debug("GPT MODEL FOR METADATA PATH SELECTED: GPT-4o")
            
            # Generate prompt with metadata context
            prompt = get_farcaster_prompt_with_metadata_context(
                context="",
                query=query,
                conversation=conversation_history,
                name=user_name,
                depth=depth,
                metadata_context=metadata_context,
                name_mappings=name_mappings
            )
                   

            # Create messages array starting with conversation history
            messages = conversation_history.copy()            
            # Add the system prompt as the final message
            #TODO: consider changing the role from developer to system? see OpenAI docs
            messages.append({"role": "developer", "content": prompt})
            #Instead of injecting the user's query into the developer prompt which we had done earlier, inject it at the end as the user's query.
            messages.append({"role": "user", "content": query})

            logger.info("Messages being sent to OpenAI: %s", json.dumps(messages, indent=2))

            response = self.openai_client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=300,
                temperature=0.3
            )
            
            logger.debug(f"METADATA PATH RESPONSE RECEIVED IN {time.time() - start_time:.2f} SECONDS USING {model}")
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error processing query in MetadataPath: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            
            return f"Sorry @{user_name}, I encountered an error processing your query."  
    
    def _generate_name_mapping_string(self, query: str, mentioned_hosts: List[str]) -> str:
        """Generate a string explaining name mappings for the LLM"""
        if not mentioned_hosts:
            return ""
        
        query_words = set(word.strip('.,?!/@').lower() for word in query.split())
        mappings = []
        
        for canonical_name in mentioned_hosts:
            # Only process hosts that are in our name_variations dictionary
            if canonical_name in self.name_variations:
                for variant in self.name_variations[canonical_name]:
                    if variant.lower() in query_words:
                        mappings.append(f"{canonical_name}={variant}")
                        break
        
        if mappings:
            return "When answering, use these name mappings: " + ", ".join(mappings)
        return ""
    
