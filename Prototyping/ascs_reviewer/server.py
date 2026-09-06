import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app_config import (
    # Compatibility exports retained for existing integrations and tests.
    API_CAPABILITIES,
    API_VERSION,
    APP_HOST,
    APP_PORT,
    BENCHMARK_CONTROL_IDS,
    BENCHMARK_EXPECTED_FINDINGS,
    MODEL_CONTEXT_CACHE,
    MODEL_CONTEXT_CACHE_LOCK,
    OLLAMA_BASE_URL,
    OLLAMA_BENCHMARK_TIMEOUT_SECONDS,
    STATIC_FILES,
)
from document_processing import (
    DocumentProcessingMixin,
    EXCEL_EXTENSIONS,
    LEGACY_OFFICE_EXTENSIONS,
    SCADE_TEXT_EXTENSIONS,
    SCADE_XML_EXTENSIONS,
    WORD_EXTENSIONS,
)
from model_providers import ModelProviderMixin
from retrieval import RetrievalMixin
from review_results import ReviewResultMixin
from review_service import ReviewServiceMixin, SKILL_STORE
from traceability import TraceabilityMixin
from skill_store import SCHEMA_VERSION, SkillValidationError

class ASCSReviewerHandler(ReviewServiceMixin, ReviewResultMixin, RetrievalMixin, TraceabilityMixin, ModelProviderMixin, DocumentProcessingMixin, BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/models":
            self._send_json(self._get_model_status())
            return

        if path == "/api/health":
            self._send_json(self._probe_ollama())
            return

        if path == "/api/skills":
            self._send_json({"schema_version": SCHEMA_VERSION, "skills": SKILL_STORE.list_skills()})
            return

        if path == "/api/rag/status":
            self._send_json(self._get_rag_status())
            return

        static_file = STATIC_FILES.get(path)
        if static_file:
            self._serve_file(static_file)
            return

        self._send_text("Not found", status=404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/chat":
            body = self._read_json_body()
            self._send_json(self._request_ollama("/api/chat", body))
            return

        if path == "/api/reviewer/review":
            body = self._read_json_body()
            self._send_json(self._build_reviewer_response(body))
            return

        if path == "/api/traceability/analyze":
            body = self._read_json_body()
            self._send_json(self._build_traceability_response(body))
            return

        if path == "/api/models/start":
            body = self._read_json_body()
            self._send_json(self._start_model(body))
            return

        if path == "/api/models/stop":
            body = self._read_json_body()
            self._send_json(self._stop_model(body))
            return

        if path == "/api/models/ready":
            body = self._read_json_body()
            self._send_json(self._check_model_ready(body))
            return

        if path == "/api/models/benchmark":
            body = self._read_json_body()
            self._send_json(self._run_model_benchmark(body))
            return

        if path == "/api/hosted/health":
            body = self._read_json_body()
            self._send_json(self._check_hosted_model_server(body))
            return

        if path == "/api/rag/load":
            body = self._read_json_body()
            self._send_json(self._load_rag_content(body))
            return

        if path == "/api/rag/clear":
            self._send_json(self._clear_rag_content())
            return

        if path == "/api/rag/remove":
            body = self._read_json_body()
            self._send_json(self._remove_rag_documents(body))
            return

        self._send_json({"error": "Not found"}, status=404)

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _serve_file(self, path, not_found=False):
        if not path.exists() or path.is_dir():
            self._send_text("Not found", status=404 if not_found else 500)
            return

        suffix = path.suffix.lower()
        content_type_map = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        content_type = content_type_map.get(suffix, "application/octet-stream")

        try:
            content = path.read_bytes()
        except OSError:
            self._send_text("File could not be read", status=500)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, content, status=200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), ASCSReviewerHandler)
    display_host = "127.0.0.1" if APP_HOST in {"0.0.0.0", "::"} else APP_HOST
    print(f"ASCS Reviewer running at http://{display_host}:{APP_PORT}")
    print(f"Using Ollama at {OLLAMA_BASE_URL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ASCS Reviewer.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
