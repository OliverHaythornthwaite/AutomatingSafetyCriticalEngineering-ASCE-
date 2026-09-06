"""Portable application configuration and process-local state."""

import os
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
STYLES_FILE = ROOT / "styles.css"
SCRIPT_FILE = ROOT / "app.js"
SKILLS_DIRECTORY = ROOT / "skills"
BROWSER_DIRECTORY = ROOT / "browser"

STATIC_FILES = {
    "/": INDEX_FILE,
    "/index.html": INDEX_FILE,
    "/styles.css": STYLES_FILE,
    "/app.js": SCRIPT_FILE,
    "/browser/config.js": BROWSER_DIRECTORY / "config.js",
    "/browser/documents.js": BROWSER_DIRECTORY / "documents.js",
    "/browser/rendering.js": BROWSER_DIRECTORY / "rendering.js",
    "/browser/reviews.js": BROWSER_DIRECTORY / "reviews.js",
}

APP_HOST = os.environ.get("ASCS_REVIEWER_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("ASCS_REVIEWER_PORT", "8000"))

MODEL_ENDPOINT_URL = os.environ.get("ASCS_MODEL_ENDPOINT", "http://127.0.0.1:8001/v1").rstrip("/")
MODEL_ID = os.environ.get("ASCS_MODEL_ID", "review-model")
MODEL_API_KEY = os.environ.get("ASCS_MODEL_API_KEY", "")
MODEL_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("ASCS_MODEL_REQUEST_TIMEOUT", "12"))
MODEL_REVIEW_TIMEOUT_SECONDS = float(os.environ.get("ASCS_MODEL_REVIEW_TIMEOUT", "900"))
MODEL_CONTEXT_LIMIT = int(os.environ.get("ASCS_MODEL_CONTEXT_LIMIT", "32768"))
REVIEW_MIN_CONTEXT = 8192 # Todo: Configure according to API
REVIEW_MAX_CONTEXT = 131072  # Todo: Configure according to API
REVIEW_MAX_OUTPUT_TOKENS = int(os.environ.get("ASCS_REVIEW_MAX_OUTPUT_TOKENS", "8192"))
REVIEW_TEMPERATURE = float(os.environ.get("ASCS_REVIEW_TEMPERATURE", "0"))
REVIEW_TOP_P = float(os.environ.get("ASCS_REVIEW_TOP_P", "0.9"))

APPROX_CHARS_PER_TOKEN = 4
RAG_MAX_CHUNKS = 10_000
RAG_MAX_CONTENT_CHARS = 20_000_000
RAG_LOCK = threading.Lock()
RAG_STORE = {"name": "", "chunks": []}

INFERENCE_SETTINGS_LOCK = threading.RLock()
INFERENCE_SETTINGS = {
    "base_url": MODEL_ENDPOINT_URL,
    "model": MODEL_ID,
    "api_key": MODEL_API_KEY,
    "context_limit": MODEL_CONTEXT_LIMIT,
    "request_timeout": MODEL_REQUEST_TIMEOUT_SECONDS,
    "review_timeout": MODEL_REVIEW_TIMEOUT_SECONDS,
}


def get_inference_settings():
    """Return an atomic snapshot of the process-local inference settings."""
    with INFERENCE_SETTINGS_LOCK:
        return dict(INFERENCE_SETTINGS)


def replace_inference_settings(settings):
    """Replace the process-local inference settings after caller validation."""
    with INFERENCE_SETTINGS_LOCK:
        INFERENCE_SETTINGS.clear()
        INFERENCE_SETTINGS.update(settings)

API_VERSION = "2.0-portable"
API_CAPABILITIES = [
    "editable-inference-endpoint-v1",
    "rag-store-v1",
    "rag-document-lifecycle-v1",
    "indexed-reference-workflow-v1",
    "staged-retrieval-v1",
    "chunk-token-count-v1",
    "scade-parser-v1",
]

ARTEFACT_ORDER = {"SRATS": 0, "SR": 0, "HLR": 1, "LLR": 2, "LLRV": 3}
