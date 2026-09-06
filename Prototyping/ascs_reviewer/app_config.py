"""Central application configuration and process-local shared state."""

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
    "/browser/providers.js": BROWSER_DIRECTORY / "providers.js",
    "/browser/rendering.js": BROWSER_DIRECTORY / "rendering.js",
    "/browser/reviews.js": BROWSER_DIRECTORY / "reviews.js",
}

APP_HOST = os.environ.get("ASCS_REVIEWER_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("ASCS_REVIEWER_PORT", "8000"))

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_REQUEST_TIMEOUT", "12"))
OLLAMA_LOAD_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_LOAD_TIMEOUT", "120"))
OLLAMA_READY_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_READY_TIMEOUT", "45"))
OLLAMA_REVIEW_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_REVIEW_TIMEOUT", "900"))
OLLAMA_BENCHMARK_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_BENCHMARK_TIMEOUT", "180"))
OLLAMA_STOP_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_STOP_TIMEOUT", "30"))
MODEL_KEEP_ALIVE = os.environ.get("OLLAMA_MODEL_KEEP_ALIVE", "10m")
OLLAMA_REVIEW_MIN_NUM_CTX = int(os.environ.get("OLLAMA_REVIEW_MIN_NUM_CTX", "8192"))
OLLAMA_REVIEW_DEFAULT_NUM_CTX = int(os.environ.get("OLLAMA_REVIEW_DEFAULT_NUM_CTX", "32768"))
OLLAMA_REVIEW_MAX_NUM_CTX = int(os.environ.get("OLLAMA_REVIEW_MAX_NUM_CTX", "131072"))
OLLAMA_REVIEW_NUM_PREDICT = int(os.environ.get("OLLAMA_REVIEW_NUM_PREDICT", "8192"))
OLLAMA_REVIEW_TEMPERATURE = float(os.environ.get("OLLAMA_REVIEW_TEMPERATURE", "0"))
OLLAMA_REVIEW_TOP_P = float(os.environ.get("OLLAMA_REVIEW_TOP_P", "0.9"))
OLLAMA_REVIEW_REPEAT_PENALTY = float(os.environ.get("OLLAMA_REVIEW_REPEAT_PENALTY", "1.05"))

APPROX_CHARS_PER_TOKEN = 4
RAG_MAX_CHUNKS = 10_000
RAG_MAX_CONTENT_CHARS = 20_000_000
RAG_MAX_VECTOR_DIMENSIONS = 8_192

RAG_LOCK = threading.Lock()
RAG_STORE = {
    "name": "",
    "embedding_model": "",
    "dimensions": 0,
    "chunks": [],
}
MODEL_CONTEXT_CACHE_LOCK = threading.Lock()
MODEL_CONTEXT_CACHE = {}

API_VERSION = "1.9"
API_CAPABILITIES = [
    "context-window-v1",
    "model-context-discovery-v1",
    "hosted-model-v1",
    "model-benchmark-v1",
    "rag-store-v1",
    "rag-document-lifecycle-v1",
    "indexed-reference-workflow-v1",
    "staged-retrieval-v1",
    "chunk-token-count-v1",
    "scade-parser-v1",
    "reasoning-effort-levels-v1",
]

BENCHMARK_VERSION = "1.0"
BENCHMARK_EXPECTED_FINDINGS = {
    ("LLR-B01", "BENCH-R1"): "Undefined zero-divisor behaviour",
    ("LLR-B02", "BENCH-R2"): "Unmeasurable timing requirement",
    ("LLR-B03", "BENCH-R3"): "Undefined invalid-input safe state",
    ("LLR-B04", "BENCH-R4"): "Missing parent traceability",
}
BENCHMARK_CONTROL_IDS = {"LLR-B05", "LLR-B06"}

ARTEFACT_ORDER = {"SRATS": 0, "SR": 0, "HLR": 1, "LLR": 2, "LLRV": 3}
