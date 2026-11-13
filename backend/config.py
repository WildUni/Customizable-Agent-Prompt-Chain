import os

from dotenv import load_dotenv

load_dotenv()

# ---------- non-secret settings (defaults live here) ----------
# These can still be overridden by an environment variable of the same name,
# e.g. `USE_FAKE_LLM=true uv run fastapi dev`.

LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b")
USE_FAKE_LLM = os.getenv("USE_FAKE_LLM", "false").lower() == "true"

# ---------- environment-specific settings (from .env) ----------

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # None = the OpenAI default URL
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")    # secret: no default
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
