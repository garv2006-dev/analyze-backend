import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory paths
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

# Load environment variables from backend/.env
ENV_FILE = BACKEND_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)

# Server Configuration
PORT = int(os.getenv("PORT", 5000))
ENV = os.getenv("NODE_ENV", "development")
BACKEND_URL = os.getenv("BACKEND_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")

# MongoDB Database Configuration
DB_NAME = os.getenv("DB_NAME", "graph_analysis_db")

# Connection URL
# Default fallback to the user's MongoDB Atlas cluster URL if not set in env
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL or not (DATABASE_URL.startswith("mongodb://") or DATABASE_URL.startswith("mongodb+srv://")):
    DATABASE_URL = f"mongodb+srv://garv_v:garv_mongo@cluster0.yanhksc.mongodb.net/{DB_NAME}?retryWrites=true&w=majority"
else:
    # If a custom database URL is provided, ensure any placeholder <database_name> is substituted
    if "<database_name >" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("<database_name >", DB_NAME)
    elif "<database_name>" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("<database_name>", DB_NAME)

# AI Vision Credentials
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# If GEMINI_API_KEY is provided, prioritize it
if GEMINI_API_KEY:
    OPENAI_API_KEY = GEMINI_API_KEY

# Check if OpenAI is running in offline simulation mode
IS_MOCK_MODE = (
    not OPENAI_API_KEY
    or OPENAI_API_KEY == "mock-api-key-for-local-runs"
    or OPENAI_API_KEY.startswith("sk-proj-****")
    or OPENAI_API_KEY.startswith("sk-or-****")
    or OPENAI_API_KEY.startswith("AIzaSy****")
)

# Detect key types
IS_OPENROUTER = OPENAI_API_KEY.startswith("sk-or-")
IS_GEMINI = OPENAI_API_KEY.startswith("AIzaSy")

# Configure AI model and endpoint base URL dynamically
if IS_GEMINI:
    AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    OPENROUTER_REFERER = None
    OPENROUTER_TITLE = None
elif IS_OPENROUTER:
    AI_MODEL = os.getenv("AI_MODEL", "openai/gpt-4o")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    # OpenRouter specific headers
    OPENROUTER_REFERER = os.getenv("OPENROUTER_REFERER", "http://localhost:3000")
    OPENROUTER_TITLE = os.getenv("OPENROUTER_TITLE", "AI Graph Analyzer")
else:
    AI_MODEL = os.getenv("AI_MODEL", "gpt-4o")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENROUTER_REFERER = None
    OPENROUTER_TITLE = None


# Browser Automation Settings
TARGET_URL = os.getenv("TARGET_URL", "https://groww.in/charts/indices/nifty")
TARGET_SELECTOR = os.getenv("TARGET_SELECTOR", "body")
RENDER_DELAY_MS = int(os.getenv("RENDER_DELAY_MS", 2000))

# Screenshots folder structure
SCREENSHOTS_DIR = BACKEND_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Cloudinary Configuration
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

IS_CLOUDINARY_ENABLED = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

