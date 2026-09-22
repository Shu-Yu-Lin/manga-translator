import os
from dotenv import load_dotenv
load_dotenv()

# ollama, with OpenAI API compatibility
CUSTOM_OPENAI_API_KEY = os.getenv('CUSTOM_OPENAI_API_KEY', 'ollama') # Unsed for ollama, but maybe useful for other LLM tools.
CUSTOM_OPENAI_API_BASE = os.getenv('CUSTOM_OPENAI_API_BASE', 'http://localhost:11434/v1') # Use OLLAMA_HOST env to change binding IP and Port.
CUSTOM_OPENAI_MODEL = os.getenv('CUSTOM_OPENAI_MODEL', '') # e.g "qwen2.5:7b". Make sure to pull and run it before use.
CUSTOM_OPENAI_MODEL_CONF = os.getenv('CUSTOM_OPENAI_MODEL_CONF', '') # e.g "qwen2".
