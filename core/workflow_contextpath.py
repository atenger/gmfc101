import logging
from typing import Optional
import json
from core.utils import format_timestamp
from prompts.farcaster_prompts import get_farcaster_prompt_with_transcript_context
import os
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set logging level based on environment variable
VERBOSE_LOGGING = os.getenv('VERBOSE_LOGGING', 'false').lower() == 'true'
if VERBOSE_LOGGING:
    logger.setLevel(logging.DEBUG)  # Show everything including debug when verbose




class ContextualPath:
    def __init__(self, openai_client):
        self.openai_client = openai_client
        self.data_dir = os.getenv('DATA_DIR', './data')

    def handle_query(
        self,
        query: str,
        user_name: str,
        conversation_history: str,
        conversation_summary: str,
        pinecone_index,
        depth: int
    ) -> str:
        """
        Handles a query using the contextual path approach with semantic search.
        "Contextual" in this case means "use transcript snippets as context to answer the user's query".
        
        Args:
            query: The user's query text
            user_name: The username of the person asking the question
            conversation_history: Previous conversation context
            pinecone_index: The Pinecone index for semantic search
            depth: The current depth of the conversation
            
        Returns:
            str: The LLM response
        """
        try:
            # Search pinecone for relevant transcript snippets
            additional_context = self.get_additional_context(pinecone_index, query)
            return self.get_llm_response(
                query, 
                user_name, 
                conversation_history, 
                additional_context, 
                depth
            )
        except Exception as e:
            logger.error(f"Error in contextual path: {e}")
            return "Sorry, I couldn't process your request right now."

    def get_llm_response(self, user_query, user_name, conversation_history, additional_context, depth):
        """
        Generates a response using the OpenAI LLM based on user input and context.
        """
        try:         
            
            #We are no longer going to inject the conversation history into the prompt, it's now an array of messages that we'll pass to the LLM
            #This is because we're using the OpenAI API's chat completion feature, which allows us to pass in an array of messages.

            llm_prompt = get_farcaster_prompt_with_transcript_context(
                additional_context, 
                user_query, 
                conversation_history, 
                user_name, 
                depth
            )
               
            
            # Create messages array starting with conversation history            
            messages = conversation_history.copy()            
            # Add the system prompt as the final message, changing the role from user to developer (prev. system)
            messages.append({"role": "developer", "content": llm_prompt})
            #Instead of injecting the user's query into the developer prompt which we had done earlier, inject it at the end as the user's query.
            messages.append({"role": "user", "content": user_query})


            logger.info("Messages being sent to OpenAI: %s", json.dumps(messages, indent=2))
            
            #change model to gpt-4o (april 24, 2025)
            llm_response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=300,
                temperature=0.7
            )
            logger.debug("GPT RESPONSE RECEIVED...")

            return llm_response.choices[0].message.content        

        except Exception as e:
            logger.error(f"Error querying LLM API: {e}")
            return "Sorry, I couldn't process your request right now."

    def get_additional_context(self, pinecone_index, user_query):
        """
        Gets additional context from Pinecone vector search.
        """
        try:
            # Will use semantic search to get small chunks of context from the transcripts that are relevant to the user query
            matches = self.search_transcripts_for_similar_content(pinecone_index, user_query)
            
            rich_contexts = []        
            for match in matches:
                           # Skip if no transcript path available
                if not match['transcript_path']:
                    logger.warning(f"Skipping match for episode {match['episode']} - no transcript path available")
                    continue


                expanded = self.find_expanded_context(
                    transcript_path=match['transcript_path'],
                    search_text=match['text'],
                    context_sentences=15
                )
                
                if expanded:
                    # Convert timestamp to seconds and ensure it's an integer
                    timestamp_seconds = int(expanded['start_time'])
                    
                    # Extract base URL and add timestamp
                    base_url = match['youtube_url'].split('?')[0]  # Remove any existing parameters
                    youtube_url = f"{base_url}?t={timestamp_seconds}"
                    
                    # Fix hosts formatting
                    hosts = match['hosts']
                    if isinstance(hosts, list):
                        hosts_str = ', '.join(hosts)
                    else:
                        hosts_str = str(hosts)  # Handle case where hosts is a string
                    
                    context_entry = (
                        f"<episode>\n"
                        f"  <title>GM Farcaster, {match['episode']}</title>\n"
                        f"  <metadata>\n"
                        f"    Aired Date: {match['aired_date']}\n"
                        f"    Hosts: {hosts_str}\n"
                        f"    Timestamp: {format_timestamp(expanded['start_time'])}\n"
                        f"    YouTube: {youtube_url}\n"
                        f"  </metadata>\n"
                        f"  <transcript>\n"
                        f"    {expanded['context']}\n"
                        f"  </transcript>\n"
                        f"</episode>\n"
                    )
                    rich_contexts.append(context_entry)

            full_context = "\n\n".join(rich_contexts)
            return full_context

        except Exception as e:
            logger.error(f"Error creating embedding: {e}")
            return "Sorry, I couldn't process your request right now."

    def find_expanded_context(self, transcript_path: str, search_text: str, context_sentences: int = 10) -> Optional[dict]:
        """
        Find and expand context around a matched text segment in a transcript.

        Args:
            transcript_path (str): Path to the transcript JSON file
            search_text (str): Text segment to search for in the transcript
            context_sentences (int, optional): Number of sentences to include before and after the matched text. Defaults to 10.

        Returns:
            dict: Dictionary containing:
                - context: Expanded text context including surrounding sentences
                - start_time: Start timestamp of the context in seconds
                - end_time: End timestamp of the context in seconds 
                - matched_text: Original search text that was matched
                - matched_position: Timestamp position where match was found
                
            Returns None if no match is found or if there's an error.
        """
        try:
            # Construct full transcript path using DATA_DIR and transcripts subdirectory
            full_transcript_path = os.path.join(self.data_dir, 'transcripts', transcript_path)
            
            # Load transcript
            with open(full_transcript_path, 'r') as f:
                transcript = json.load(f)
                
            # Get first 10 words from search text for matching
            search_words = search_text.lower().split()[:10]        
            
            # Get word-level data
            alternatives = transcript['results']['channels'][0]['alternatives'][0]
            transcript_words = alternatives['words']
            
            # Find sequence of words using punctuated_word
            matched_position = None
            for i in range(len(transcript_words)):
                current_words = [w['punctuated_word'].lower() for w in transcript_words[i:i+len(search_words)]]
                if current_words == search_words:
                    matched_position = transcript_words[i]['start']                
                    break
                    
            if matched_position is None:
                logger.warning("Could not find matching word sequence")
                return None
                
            # Now find the sentence containing this timestamp
            paragraphs = alternatives['paragraphs']['paragraphs']
            all_sentences = []
            for para in paragraphs:
                all_sentences.extend(para['sentences'])
                
            # Find sentence containing our timestamp
            matched_idx = None
            for idx, sentence in enumerate(all_sentences):
                if sentence['start'] <= matched_position <= sentence['end']:
                    matched_idx = idx                
                    break
                    
            if matched_idx is None:
                logger.warning("Could not find matching sentence")
                return None
                
            # Get context sentences
            start_idx = max(0, matched_idx - context_sentences)
            end_idx = min(len(all_sentences), matched_idx + context_sentences + 1)
            
            context_sentences = all_sentences[start_idx:end_idx]
            
            result = {
                'context': " ".join(s['text'] for s in context_sentences),
                'start_time': context_sentences[0]['start'],
                'end_time': context_sentences[-1]['end'],
                'matched_text': search_text,
                'matched_position': matched_position
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return None


  

    def search_transcripts_for_similar_content(self, pinecone_index, query_text: str):
        """
        Searches for similar content in transcripts using vector search.
        Returns matches with metadata including transcript file paths from metadata.json.
        """
        try:
            # Load metadata.json
            metadata_path = os.path.join(self.data_dir, 'metadata.json')
            with open(metadata_path, 'r') as f:
                episodes_metadata = json.load(f)
            
            logger.debug(f"CREATING EMBEDDING FROM USER QUERY: {query_text[:100]}...")
            response = self.openai_client.embeddings.create(
                model="text-embedding-ada-002",
                input=[query_text]
            )
            query_embedding = response.data[0].embedding
            logger.debug(f"EMBEDDING CREATED, LENGTH: {len(query_embedding)}")
            
            logger.debug("QUERYING PINECONE...")
            search_results = pinecone_index.query(
                vector=query_embedding,
                top_k=3,
                include_metadata=True
            )        

            logger.debug("PROCESSING MATCHES...")
            matches = []
            for match in search_results["matches"]:
                episode = match.get("metadata", {}).get("episode", "No episode")
                # Look up transcript path from metadata.json
                transcript_path = next(
                    (item["transcript_path"] for item in episodes_metadata if item["episode"] == episode),
                    None
                )
                
                matches.append({
                    "text": match.get("metadata", {}).get("transcript", "No text found"),
                    "score": match.get("score", 0.0),
                    "title": match.get("metadata", {}).get("title", "No title"),
                    "episode": episode,
                    "series": match.get("metadata", {}).get("series", "No series"),
                    "companion_blog": match.get("metadata", {}).get("companion_blog", "No companion blog"),
                    "hosts": match.get("metadata", {}).get("hosts", "No hosts"),
                    "aired_date": match.get("metadata", {}).get("aired_date", "Aired date not available"),
                    "youtube_url": match.get("metadata", {}).get("youtube_url", "No youtube url"),
                    "transcript_path": transcript_path
                })
            
            logger.debug("MATCHES FOUND:")
            for match in matches:
                logger.debug(f"\nMatch Details:")
                logger.debug(f"Score: {match['score']}")
                logger.debug(f"Series: {match['series']}")
                logger.debug(f"Episode: {match['episode']} - {match['title']}")                                                
            return matches

        except Exception as e:
            logger.error(f"Error in transcript search: {e}")
            return []
