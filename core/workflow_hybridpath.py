import logging
from typing import Optional, List, Dict
import json
import os
import tiktoken
from core.utils import format_timestamp
from prompts.hybrid_prompts import EPISODE_IDENTIFICATION_PROMPT
from prompts.hybrid_prompts import get_farcaster_prompt_with_full_transcript_context


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set logging level based on environment variable
VERBOSE_LOGGING = os.getenv('VERBOSE_LOGGING', 'false').lower() == 'true'
if VERBOSE_LOGGING:
    logger.setLevel(logging.DEBUG)

class HybridPath:
    def __init__(self, openai_client):
        """
        Initialize the HybridPath handler.
        
        Args:
            openai_client: OpenAI client instance for API calls
        """
        self.openai_client = openai_client
        self.data_dir = os.getenv('DATA_DIR', './data')
        self.metadata = self._load_metadata()
        
        # Define name mappings as a class attribute
        # TODO: Move this to a separate file and load it from there, because it's used in metadata path as well. 
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
        Loads and pre-filters metadata from JSON file containing episode information.
        Only keeps essential fields to reduce token size.
        
        Returns:
            List[Dict]: List of filtered episode metadata dictionaries
        """
        try:
            logger.debug("Starting metadata loading process...")
            
            metadata_path = os.path.join(self.data_dir, 'metadata.json')
            with open(metadata_path, 'r') as f:
                raw_metadata = json.load(f)
                logger.debug(f"Successfully loaded raw metadata with {len(raw_metadata)} episodes")
                
            
            # Fields to keep for episode identification
            essential_fields = {
                'episode',
                'title',
                'series',
                'hosts',
                'aired_date'
            }
            
            
            # Clean and filter metadata
            filtered_metadata = []
            for i, episode in enumerate(raw_metadata):
                filtered_episode = {
                    k: v for k, v in episode.items()
                    if k in essential_fields
                }
                filtered_metadata.extend([filtered_episode])
                            
            # Sort by aired date for easier temporal reference handling
            filtered_metadata.sort(key=lambda x: x.get('aired_date', ''))
      
            return filtered_metadata
            
        except FileNotFoundError as e:
            logger.error(f"Metadata file not found: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding metadata JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error loading metadata: {e}")            
            return []

    def _check_token_count(self, data: str) -> int:
        """Check token count of data"""
        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(data))

    def handle_query(
        self,
        query: str,
        user_name: str,
        conversation_history: str,
        conversation_summary: str,
        depth: int
    ) -> str:
        """
        Main handler for hybrid path queries. This method will:
        1. Identify the most relevant episode from the query
        2. Get the full transcript for that episode
        3. Generate a response using the LLM with the transcript context
        
        Args:
            query: The user's query text
            user_name: The username of the person asking the question
            conversation_history: Previous conversation context
            conversation_summary: Summary of the conversation
            depth: The current depth of the conversation
            
        Returns:
            str: The LLM response
        """
        try:

            # Identify the most relevant episode from the query by using the LLM
            relevant_episodes = self._identify_relevant_episodes(query=query)
            
            # Get the full transcript for the identified episode(s)
            transcript_context = self._get_transcript_context(relevant_episodes)
            
            # Log transcript context length and token count            
            token_count = self._check_token_count(transcript_context)
            logger.debug(f"Transcript context token count: {token_count} | length: {len(transcript_context)}")
            
            
            return self._generate_llm_response(
                query,
                user_name,
                conversation_history,
                transcript_context,
                depth,
                name_mappings=""
            )
            
        except Exception as e:
            logger.error(f"Error in hybrid path: {e}")
            return f"Sorry @{user_name}, I encountered an error processing your query."

    def _prefilter_metadata(self, query: str) -> tuple[List[Dict], List[str]]:
        """
        Pre-filters metadata based on query content using advanced matching logic.
        
        Args:
            query: The user's query text
            
        Returns:
            tuple[List[Dict], List[str]]: Tuple containing filtered metadata and mentioned hosts
        """
        # Convert query to lowercase for easier matching
        query = query.lower()
        # Split query into words and remove punctuation for exact word matching
        # this way if someone mentions @heavygweit, or ends a sentence with heavygweit? it will still match
        query_words = set(word.strip('.,?!/@') for word in query.split())
        
        # Start with empty filtered set
        filtered_metadata = []
        mentioned_hosts = []

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

        matching_words = []  # Track words that matched
        for word in query_words:
            if word in title_words and word not in stop_words:
                matching_words.append(word)
                # Find all episodes with this word in the title
                title_episodes = [
                    episode for episode in self.metadata
                    if episode.get('title') 
                    and word in {w.strip('.,?!/').lower() for w in episode.get('title').split()}
                    and episode.get('episode') not in filtered_episode_ids
                ]
                matching_titles.extend(title_episodes)
                filtered_episode_ids.update(episode.get('episode') for episode in title_episodes)
                found_title_match = True  # Set the flag if we found matches
        
        if matching_titles:
            filtered_metadata.extend(matching_titles)
            logger.debug(f"Step 3 (Titles): Added {len(matching_titles)} new episodes")
            logger.debug(f"Step 3 (Titles): Words that matched titles: {', '.join(matching_words)}")
        else:
            logger.debug("Step 3 (Titles): No title matches found")

        """
        FILTER STEPS COMPLETE
        """
        
        # If no matches at all, return all metadata
        if not mentioned_hosts and not found_series and not found_title_match:
            filtered_metadata = self.metadata
            logger.debug("No matches found in any step - returning all metadata")
        
        # Final manipulation on the filtered metadata to be returned 
        filtered_metadata.sort(key=lambda x: x.get('aired_date', ''))
        
        logger.info(f"METADATA FILTERING FINAL RESULT: Returning {len(filtered_metadata)} total episodes")
        
        return filtered_metadata, mentioned_hosts

    def _identify_relevant_episodes(self, query: str) -> List[str]:
        """
        Uses an LLM to identify the episode which is most relevant to the user's query.
        
        Args:
            query: The user's query text
            
        Returns:
            List[str]: List of relevant episode IDs
        """
        try:
            
             # First, pre-filter the metadata based on the query and get the mentioned hosts
            filtered_metadata, mentioned_hosts = self._prefilter_metadata(query)
            logger.debug(f"Pre-filtered metadata contains {len(filtered_metadata)} episodes")
                        
            
            metadata_context = json.dumps(filtered_metadata)           
            
            name_mappings = self._generate_name_mapping_string(query, mentioned_hosts)
            
            # Check token count            
            token_count = self._check_token_count(metadata_context)
            logger.debug(f"METADATA TOKEN COUNT: {token_count}")
            
            # Select model based on token count
            if token_count < 7000:  # Leave room for the rest of the prompt
                model = "gpt-4"
                logger.debug("GPT MODEL SELECTED: GPT-4 base for better accuracy")
            else:
                model = "gpt-4-turbo"
                logger.debug("GPT MODEL SELECTED: GPT-4 Turbo due to large context size")
            
                       
            try:
                prompt = EPISODE_IDENTIFICATION_PROMPT.format(
                    query=query,
                    metadata=metadata_context,
                    name_mappings=name_mappings
                )
                               
                logger.info(f"EPISODE IDENTIFICATION PROMPT: {prompt}")
            except Exception as e:
                logger.error(f"Error formatting prompt: {e}")
                
                raise
            
            # Get LLM response
            logger.debug("Sending request to OpenAI API...")
            try:
                response = self.openai_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt}
                    ],
                    temperature=0
                )
                
            except Exception as e:
                logger.error(f"Error calling OpenAI API: {e}")
                raise
            
            # Get the raw response content
            response_content = response.choices[0].message.content.strip()
            logger.debug(f"LLM RESPONSE: {response_content}")
            
            # Parse the response
            try:
                
                response_dict = json.loads(response_content)
                
                
                if not isinstance(response_dict, dict):
                    logger.error(f"Response is not a dictionary: {response_dict}")
                    return []
                    
                episode_ids = response_dict.get('episode_ids', [])
                logger.debug(f"EXTRACTED EPISODE IDS: {episode_ids}")
                
                if not isinstance(episode_ids, list):
                    logger.error(f"episode_ids is not a list: {episode_ids}")
                    return []
                    
                
                return episode_ids
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing LLM response as JSON: {e}")
                logger.error(f"Response content: {response_content}")
                return []
                
        except Exception as e:
            logger.error(f"Error in episode identification: {e}")            
            return []
        

    def _get_transcript_context(self, episodes: List[str]) -> str:
        """
        Retrieves and processes the full transcript(s) for the identified episodes.
        Includes relevant metadata before the transcript text.
        
        Args:
            episodes: List of episode IDs, example: ['ep212', 'ep189', 'ep38']
            
        Returns:
            str: Processed transcript context with metadata, ready for the LLM
        """
        try:
            # Return empty string if no episodes
            if not episodes:
                logger.debug("No episodes provided to get transcript context")
                return ""

            # Get first episode ID
            episode_id = episodes[0]
            logger.debug(f"Getting transcript for episode {episode_id}")

            # Load metadata to find transcript path
            metadata_path = os.path.join(self.data_dir, 'metadata.json')
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)

            # Find matching episode metadata
            episode_metadata = None
            for ep in metadata:
                if ep.get('episode') == episode_id:
                    episode_metadata = ep
                    break

            if not episode_metadata:
                logger.error(f"Could not find metadata for episode {episode_id}")
                return ""

            # Get transcript path
            transcript_path = episode_metadata.get('transcript_path')
            if not transcript_path:
                logger.error(f"No transcript path found for episode {episode_id}")
                return ""

            # Construct full transcript path using DATA_DIR and transcripts subdirectory
            full_transcript_path = os.path.join(self.data_dir, 'transcripts', transcript_path)

            # Load transcript
            with open(full_transcript_path, 'r') as f:
                transcript_data = json.load(f)

            # Extract transcript text from the new structure
            try:
                transcript_text = transcript_data['results']['channels'][0]['alternatives'][0]['transcript']
                
                # Create formatted metadata section
                metadata_section = (
                    "EPISODE METADATA:\n"
                    f"Series: {episode_metadata.get('series', 'N/A')}\n"
                    f"Episode: {episode_metadata.get('episode', 'N/A')}\n"
                    f"Title: {episode_metadata.get('title', 'N/A')}\n"
                    f"Hosts: {', '.join(episode_metadata.get('hosts', ['N/A']))}\n"
                    f"Aired Date: {episode_metadata.get('aired_date', 'N/A')}\n"
                    f"YouTube URL: {episode_metadata.get('youtube_url', 'N/A')}\n"
                    "\nTRANSCRIPT:\n"
                )
                
                # Combine metadata and transcript
                full_context = f"{metadata_section}{transcript_text.strip()}"
                
                logger.debug(f"Successfully extracted transcript and metadata for episode {episode_id}")
                #logger.debug(f"FULL CONTEXT: {full_context}")
                return full_context
                
            except (KeyError, IndexError) as e:
                logger.error(f"Error extracting transcript text, unexpected structure: {e}")
                return ""

        except Exception as e:
            logger.error(f"Error getting transcript context: {e}")
            return ""
        



    def _generate_llm_response(
        self,
        query: str,
        user_name: str,
        conversation_history: str,
        transcript_context: str,
        depth: int,
        name_mappings: str
    ) -> str:
        """
        Generates a response using the OpenAI LLM based on the transcript context.
        
        Args:
            query: The user's query text
            user_name: The username of the person asking the question
            conversation_history: Previous conversation context
            transcript_context: Processed transcript context
            depth: The current depth of the conversation
            
        Returns:
            str: The LLM response
        """
        try:
                       

            # Get prompt from hybrid_prompts.py
            llm_prompt = get_farcaster_prompt_with_full_transcript_context(
                full_transcript_context=transcript_context,
                query=query,
                name=user_name,
                depth=depth,
                name_mappings=name_mappings
            )
            logger.debug("Generated prompt for LLM")


            # Create messages array starting with conversation history  
            messages = conversation_history.copy()
            #messages = []
            # Add the system prompt as the final message, changing the role from user to developer (prev. system)
            messages.append({"role": "developer", "content": llm_prompt})
            #add user's query as the final message
            messages.append({"role": "user", "content": query})

            logger.info("MESSAGES BEING SENT TO LLM: %s", json.dumps(messages, indent=2))

            # Call OpenAI API
            #change model to gpt-4o and max tokens to 300 (april 24, 2025)
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.7,
                max_tokens=300
            )
            logger.debug("Received response from OpenAI API")

            # Extract response text
            response_text = response.choices[0].message.content.strip()
            logger.debug(f"LLM RESPONSE: {response_text}")

            return response_text

        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            return "I apologize, but I encountered an error while processing your request. Please try again."

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
            return "Please note the following name mappings: " + ", ".join(mappings)
        return ""