import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent

# Load .env file (API keys stay in .env, never in source code)
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Groq model registry
# Groq shut down llama-3.3-70b-versatile / llama-3.1-8b-instant (16 Aug 2026),
# mixtral-8x7b-32768 and gemma2-9b-it earlier. Requests to those IDs return
# errors, so any old value left in .env is migrated automatically.
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_FALLBACK_MODEL = "openai/gpt-oss-20b"

RETIRED_MODELS = {
    "llama-3.3-70b-versatile": DEFAULT_MODEL,
    "llama-3.1-8b-instant": DEFAULT_FALLBACK_MODEL,
    "llama-3.1-70b-versatile": DEFAULT_MODEL,
    "llama3-70b-8192": DEFAULT_MODEL,
    "llama3-8b-8192": DEFAULT_FALLBACK_MODEL,
    "mixtral-8x7b-32768": DEFAULT_MODEL,
    "gemma2-9b-it": DEFAULT_FALLBACK_MODEL,
    "qwen/qwen3-32b": DEFAULT_MODEL,
    "qwen/qwen3.6-27b": "qwen/qwen3.8-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct": DEFAULT_MODEL,
    "meta-llama/llama-4-maverick-17b-128e-instruct": DEFAULT_MODEL,
    "moonshotai/kimi-k2-instruct-0905": DEFAULT_MODEL,
}


def resolve_model(model_id):
    """Returns (usable_model_id, note). Migrates retired model IDs automatically."""
    model_id = (model_id or "").strip()
    if not model_id:
        return DEFAULT_MODEL, ""
    if model_id in RETIRED_MODELS:
        new_id = RETIRED_MODELS[model_id]
        return new_id, f"Model '{model_id}' has been retired by Groq; using '{new_id}' instead."
    return model_id, ""


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-startup-validator-key-2026")
    BASE_DIR = BASE_DIR
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "startup_validator.db"))
    EXPORTS_DIR = BASE_DIR / "exports"

    # AI & Search configuration (keys come from .env)
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_MODEL, MODEL_NOTE = resolve_model(os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    GROQ_FALLBACK_MODEL, _ = resolve_model(os.getenv("GROQ_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL))
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

    # Kept for backwards compatibility with older .env files. The application no
    # longer fabricates "demo" research: without API keys it reports that the
    # analysis is unavailable instead of inventing numbers.
    DEMO_MODE = False

    # Research limits (protect free-tier quotas)
    MAX_SEARCHES_PER_IDEA = int(os.getenv("MAX_SEARCHES_PER_IDEA", 24))
    HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", 8))
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", 90))
    QUICK_MODE = os.getenv("ANALYSIS_MODE", "standard").strip().lower() == "quick"   # faster, shallower analysis
    # Groq's free tier allows about 8,000 tokens per minute per model (input + requested output) and 200,000 per day.
    # The client keeps requests inside this budget instead of failing. Set to 0 on a paid plan to switch pacing off.
    GROQ_TPM_LIMIT = int(os.getenv("GROQ_TPM_LIMIT", 8000))
    AGENT_RETRY_PAUSE = int(os.getenv("AGENT_RETRY_PAUSE", 10))   # seconds before an agent that failed transiently is retried once
    LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", 2))   # simultaneous Groq calls (free tier has token-per-minute limits)

    # Available Groq models shown in Settings
    AVAILABLE_MODELS = [
        {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B (Recommended)"},
        {"id": "openai/gpt-oss-20b", "name": "GPT-OSS 20B (Fast / low cost)"},
        {"id": "qwen/qwen3.8-27b", "name": "Qwen 3.8 27B"},
    ]

    # Server settings
    PORT = int(os.getenv("PORT", 5000))
    HOST = os.getenv("HOST", "127.0.0.1")
    DEBUG = os.getenv("FLASK_ENV", "development") == "development"

    @classmethod
    def update_runtime_keys(cls, groq_key=None, tavily_key=None, model=None, demo_mode=None):
        """Update runtime API keys and settings dynamically from the Settings UI"""
        if groq_key is not None:
            cls.GROQ_API_KEY = groq_key.strip()
        if tavily_key is not None:
            cls.TAVILY_API_KEY = tavily_key.strip()
        if model is not None and model.strip():
            cls.GROQ_MODEL, cls.MODEL_NOTE = resolve_model(model)
        # demo_mode is accepted for backwards compatibility but ignored.
