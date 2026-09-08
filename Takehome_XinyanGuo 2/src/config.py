"""Configuration, loaded from environment (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

# brave | tavily | duckduckgo
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "brave").lower()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

MAX_STEPS = int(os.getenv("MAX_STEPS", "12"))

# Minimum seconds between model calls. The free tier is ~5 requests/minute per
# model, so pacing proactively is cheaper than being rate-limited and retrying.
MIN_REQUEST_INTERVAL = float(os.getenv("MIN_REQUEST_INTERVAL", "13"))
MAX_FETCH_CHARS = 12_000

# Short-term memory: how many of the most recent tool results stay in the
# context verbatim. Older ones are replaced by a stub that points at the trace.
MAX_LIVE_TOOL_RESULTS = int(os.getenv("MAX_LIVE_TOOL_RESULTS", "6"))
REQUEST_TIMEOUT = 20
