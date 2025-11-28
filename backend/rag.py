import os
# import chromadb
import google.generativeai as genai
# from chromadb.utils import embedding_functions
import logging
from .database import collection

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize ChromaDB
# chroma_client = chromadb.PersistentClient(path="./chroma_db")
# collection = chroma_client.get_or_create_collection(name="video_knowledge")

# Configure Gemini
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    
    # Debug: List available models
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                logger.info(f"Available model: {m.name}")
    except Exception as e:
        logger.error(f"Failed to list models: {e}")

    # Try to find a valid model
    # Based on available models from logs: gemini-2.0-flash
    model = genai.GenerativeModel('gemini-2.0-flash')
else:
    logger.warning("GOOGLE_API_KEY not found. RAG will use mock responses.")
    model = None

def index_transcript(video_id, transcript):
    """Indexes the transcript into ChromaDB."""
    try:
        # Split transcript into chunks (naive splitting by line for now)
        lines = transcript.strip().split('\n')
        documents = []
        metadatas = []
        ids = []

        for i, line in enumerate(lines):
            if not line.strip():
                continue
            
            # Parse timestamp and text
            # Format: [123.45s -> 140.70s] Text content
            try:
                timestamp_part, text = line.split('] ', 1)
                start_str = timestamp_part.strip('[')
                start_time = float(start_str.split('s ->')[0])
            except ValueError:
                continue

            documents.append(text)
            metadatas.append({"video_id": str(video_id), "start_time": start_time})
            ids.append(f"{video_id}_{i}")

        if documents:
            collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"Indexed {len(documents)} segments for video {video_id}")
            return True
    except Exception as e:
        logger.error(f"Indexing failed for video {video_id}: {e}")
        return False

def ask_question(video, question):
    """
    Asks a question about the video using Gemini Multimodal.
    """
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return {"error": "API Key missing"}
            
        genai.configure(api_key=api_key)
        
        # Check if we have the Gemini file name
        if not video.gemini_file_name:
             return {"error": "Video not processed by Gemini yet."}

        # Get the file reference
        try:
            video_file = genai.get_file(video.gemini_file_name)
        except Exception as e:
             logger.error(f"Could not retrieve file from Gemini: {e}")
             return {"error": "Video file expired or not found in Gemini."}

        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Construct the prompt
        content_parts = [video_file]
        if video.transcript:
             content_parts.append(f"Transcript: {video.transcript}")
        content_parts.append(f"Question: {question}")

        from .utils import generate_with_retry
        # Higher retries for Q&A as it's user facing
        response = generate_with_retry(model, content_parts, retries=3, initial_delay=2)
        
        answer_text = response.text
        timestamps = [] # We'd need to parse them from the answer
        
        return {
            "text": answer_text,
            "timestamps": timestamps
        }

    except Exception as e:
        logger.error(f"Q&A failed: {e}")
        return {"error": str(e)}

def generate_quiz(video):
    """
    Generates a 5-question quiz based on the video content.
    Returns a JSON object with questions and answers.
    """
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return {"error": "API Key missing"}
            
        genai.configure(api_key=api_key)
        
        # Check if we have the Gemini file name
        if not video.gemini_file_name:
             return {"error": "Video not processed by Gemini yet."}

        # Get the file reference
        try:
            video_file = genai.get_file(video.gemini_file_name)
        except Exception as e:
             logger.error(f"Could not retrieve file from Gemini: {e}")
             return {"error": "Video file expired or not found in Gemini."}

        model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"response_mime_type": "application/json"})
        
        prompt = """
        Generate a quiz with 5 multiple-choice questions based on this video.
        Output strictly in this JSON format:
        {
            "questions": [
                {
                    "id": 1,
                    "question": "Question text here?",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correct_answer": 0  // Index of the correct option (0-3)
                }
            ]
        }
        """
        
        content_parts = [video_file, prompt]
        if video.transcript:
             content_parts.append(f"Transcript context: {video.transcript}")

        from .utils import generate_with_retry
        response = generate_with_retry(model, content_parts)
        
        import json
        return json.loads(response.text)

    except Exception as e:
        logger.error(f"Quiz generation failed: {e}")
        return {"error": str(e)}
