import base64
import binascii
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

from skill_store import SCHEMA_VERSION, SkillStore, SkillValidationError

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
STYLES_FILE = ROOT / "styles.css"
SCRIPT_FILE = ROOT / "app.js"
SKILLS_DIRECTORY = ROOT / "skills"
SKILL_STORE = SkillStore(SKILLS_DIRECTORY).load()
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
WORD_EXTENSIONS = {".docx", ".docm", ".dotx", ".dotm"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls"}
SCADE_XML_EXTENSIONS = {".xscade", ".etp", ".sgfx", ".pgfx", ".ogfx", ".dgfx", ".sdfx", ".rgfx"}
SCADE_TEXT_EXTENSIONS = {".scade", ".sss", ".in", ".sns", ".out", ".obs"}
RAG_MAX_CHUNKS = 10000
RAG_MAX_CONTENT_CHARS = 20000000
RAG_MAX_VECTOR_DIMENSIONS = 8192
RAG_LOCK = threading.Lock()
MODEL_CONTEXT_CACHE_LOCK = threading.Lock()
MODEL_CONTEXT_CACHE = {}
RAG_STORE = {
    "name": "",
    "embedding_model": "",
    "dimensions": 0,
    "chunks": [],
}
API_VERSION = "1.5"
API_CAPABILITIES = ["context-window-v1", "model-context-discovery-v1", "hosted-model-v1", "model-benchmark-v1", "rag-store-v1", "scade-parser-v1"]
BENCHMARK_VERSION = "1.0"
BENCHMARK_EXPECTED_FINDINGS = {
    ("LLR-B01", "BENCH-R1"): "Undefined zero-divisor behaviour",
    ("LLR-B02", "BENCH-R2"): "Unmeasurable timing requirement",
    ("LLR-B03", "BENCH-R3"): "Undefined invalid-input safe state",
    ("LLR-B04", "BENCH-R4"): "Missing parent traceability",
}
BENCHMARK_CONTROL_IDS = {"LLR-B05", "LLR-B06"}
ARTEFACT_ORDER = {"SRATS": 0, "SR": 0, "HLR": 1, "LLR": 2, "LLRV": 3}
REQUIREMENT_ID_PATTERN = re.compile(
    r"\b(?:"
    r"DCDS-[A-Z0-9]+-(?:SRATS|SR|HLR|LLR|LLRV)-\d+[A-Z]?"
    r"|(?:SRATS|SRAT|SR|SYS|SRS|HLR|LLR|LLRV|REQ|REQT|SWREQ|SWR)[-_ ]?\d+(?:[.\-_]\d+)*[A-Z]?"
    r"|[A-Z]{2,8}-\d{2,5}(?:[.\-_][A-Z0-9]+)*"
    r")\b",
    re.IGNORECASE,
)


class ASCSReviewerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in {"/", "/index.html"}:
            self._serve_file(INDEX_FILE)
            return

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

        if path == "/styles.css":
            self._serve_file(STYLES_FILE)
            return

        if path == "/app.js":
            self._serve_file(SCRIPT_FILE)
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

        self._send_json({"error": "Not found"}, status=404)

    def _probe_ollama(self):
        response = self._request_ollama("/api/tags")
        if isinstance(response, dict) and response.get("error"):
            return {
                "status": "offline",
                "ollama_base_url": OLLAMA_BASE_URL,
                "error": response["error"],
                "api_version": API_VERSION,
                "capabilities": API_CAPABILITIES,
            }
        return {
            "status": "online",
            "ollama_base_url": OLLAMA_BASE_URL,
            "model_count": len(response.get("models", []) or []),
            "api_version": API_VERSION,
            "capabilities": API_CAPABILITIES,
        }

    def _start_model(self, body):
        model_name = self._extract_model_name(body)
        if not model_name:
            return {"error": "Please provide a model name."}
        try:
            context_window = self._resolve_review_context_window(body, body.get("model_context_limit"))
        except ValueError as exc:
            return {"error": str(exc), "model": model_name}
        response = self._request_ollama("/api/ps")
        if isinstance(response, dict) and response.get("error"):
            return {"error": response["error"], "model": model_name}

        running_names = self._extract_model_names(response)
        if model_name in running_names:
            readiness = self._probe_model_response(model_name, context_window)
            if readiness["ready"]:
                return {"ok": True, "model": model_name, "status": "ready", "context_window": context_window, "note": readiness["reason"], **readiness}
            return {"ok": False, "model": model_name, "status": "not-ready", "error": readiness["reason"], **readiness}

        warmup_response = self._load_model(model_name, context_window)
        if isinstance(warmup_response, dict) and warmup_response.get("error"):
            return {"ok": False, "model": model_name, "status": "start-failed", "error": warmup_response["error"]}

        readiness = self._probe_model_response(model_name, context_window)
        if readiness["ready"]:
            return {"ok": True, "model": model_name, "status": "ready", "context_window": context_window, "note": readiness["reason"], **readiness}

        refreshed_response = self._request_ollama("/api/ps")
        if isinstance(refreshed_response, dict) and refreshed_response.get("error"):
            return {"ok": False, "model": model_name, "status": "start-failed", "error": refreshed_response["error"]}

        refreshed_names = self._extract_model_names(refreshed_response)
        if model_name in refreshed_names:
            return {"ok": False, "model": model_name, "status": "not-ready", "error": readiness["reason"], **readiness}

        return {"ok": False, "model": model_name, "status": "pending", "error": "Ollama is still loading the model. Try Check ready again shortly."}

    def _stop_model(self, body):
        model_name = self._extract_model_name(body)
        if not model_name:
            return {"error": "Please provide a model name."}
        response = self._request_ollama("/api/ps")
        if isinstance(response, dict) and response.get("error"):
            return {"error": response["error"], "model": model_name}

        running_names = self._extract_model_names(response)
        if model_name not in running_names:
            return {"ok": True, "model": model_name, "status": "not-running", "note": "The model is already not running, so it is shown as offline."}

        unload_response = self._unload_model(model_name)
        if isinstance(unload_response, dict) and unload_response.get("error"):
            return {"ok": False, "model": model_name, "status": "stop-failed", "error": unload_response["error"]}

        if self._wait_for_running_state(model_name, should_be_running=False):
            return {"ok": True, "model": model_name, "status": "stopped", "note": "The model was unloaded from memory."}

        return {"ok": True, "model": model_name, "status": "stopping", "note": "The unload request was accepted, but Ollama still reports the model in memory. Refresh again shortly."}

    def _check_model_ready(self, body):
        model_name = self._extract_model_name(body)
        if not model_name:
            return {"error": "Please provide a model name."}
        try:
            context_window = self._resolve_review_context_window(body, body.get("model_context_limit"))
        except ValueError as exc:
            return {"error": str(exc), "model": model_name}
        installed_response = self._request_ollama("/api/tags")
        if isinstance(installed_response, dict) and installed_response.get("error"):
            return {"ok": False, "model": model_name, "status": "offline", "error": installed_response["error"]}

        installed_names = self._extract_model_names(installed_response)
        if model_name not in installed_names:
            return {"ok": False, "model": model_name, "status": "missing", "error": f"The selected model {model_name} is not installed locally. Pull it first with: ollama pull {model_name}."}

        load_response = self._load_model(model_name, context_window)
        if isinstance(load_response, dict) and load_response.get("error"):
            return {"ok": False, "model": model_name, "status": "load-failed", "error": load_response["error"]}

        readiness = self._probe_model_response(model_name, context_window)
        if readiness["ready"]:
            return {"ok": True, "model": model_name, "status": "ready", "context_window": context_window, "note": readiness["reason"], **readiness}

        return {"ok": False, "model": model_name, "status": "not-ready", "error": readiness["reason"], **readiness}

    def _resolve_model_provider(self, body, fallback_model=""):
        raw_provider = body.get("model_provider") if isinstance(body, dict) and isinstance(body.get("model_provider"), dict) else {}
        mode = str(raw_provider.get("mode") or "ollama").strip().lower()
        model_name = str(raw_provider.get("model") or fallback_model or "").strip()
        raw_context_limit = raw_provider.get("context_limit")
        try:
            context_limit = int(raw_context_limit) if raw_context_limit not in (None, "") else None
        except (TypeError, ValueError):
            return {"error": "Model context limit must be a whole number of tokens."}
        if context_limit is not None and context_limit < OLLAMA_REVIEW_MIN_NUM_CTX:
            return {"error": f"Model context limit must be at least {OLLAMA_REVIEW_MIN_NUM_CTX:,} tokens."}
        if mode == "ollama":
            return {"mode": "ollama", "model": model_name, "context_limit": context_limit}
        if mode != "hosted":
            return {"error": "Model provider mode must be 'ollama' or 'hosted'."}

        base_url = str(raw_provider.get("base_url") or "").strip().rstrip("/")
        api_key = str(raw_provider.get("api_key") or "").strip()
        if not base_url:
            return {"error": "Provide the hosted model server URL."}
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return {"error": "Hosted model server URLs must use HTTP or HTTPS and cannot contain credentials, a query, or a fragment."}
        if not parsed.path or parsed.path == "/":
            base_url += "/v1"
        if not model_name:
            return {"error": "Provide the hosted model identifier."}
        return {"mode": "hosted", "model": model_name, "base_url": base_url, "api_key": api_key, "context_limit": context_limit}

    def _check_hosted_model_server(self, body):
        provider = self._resolve_model_provider(body, self._extract_model_name(body))
        if provider.get("error"):
            return provider
        if provider["mode"] != "hosted":
            return {"error": "Hosted server configuration is required."}
        started = time.monotonic()
        response = self._request_hosted_server(provider, "/models", timeout=REQUEST_TIMEOUT_SECONDS)
        elapsed = round(time.monotonic() - started, 3)
        if not isinstance(response, dict):
            return {"error": "Hosted model server returned an invalid model catalogue.", "status": "offline", "latency_seconds": elapsed}
        if response.get("error"):
            return {"error": response["error"], "status": "offline", "latency_seconds": elapsed}
        models = response.get("data") if isinstance(response.get("data"), list) else []
        model_ids = [str(item.get("id")) for item in models if isinstance(item, dict) and item.get("id")]
        selected_model = next(
            (item for item in models if isinstance(item, dict) and str(item.get("id") or "") == provider["model"]),
            None,
        )
        maximum_context = self._extract_context_limit(selected_model)
        return {
            "ok": True,
            "status": "online",
            "base_url": provider["base_url"],
            "model": provider["model"],
            "model_available": not model_ids or provider["model"] in model_ids,
            "max_context_length": maximum_context,
            "available_models": model_ids[:100],
            "latency_seconds": elapsed,
        }

    def _request_hosted_server(self, provider, path, payload=None, timeout=None):
        url = f"{provider['base_url'].rstrip('/')}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if provider.get("api_key"):
            headers["Authorization"] = f"Bearer {provider['api_key']}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
            with urllib.request.urlopen(request, timeout=timeout or REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
            except Exception:
                detail = ""
            return {"error": f"Hosted model server returned HTTP {exc.code}: {detail or exc.reason}"}
        except urllib.error.URLError as exc:
            return {"error": f"Unable to reach hosted model server at {provider['base_url']}: {exc}"}
        except TimeoutError as exc:
            return {"error": f"Timed out reaching hosted model server: {exc}"}
        except Exception as exc:
            return {"error": str(exc)}

    def _request_model_chat(self, provider, ollama_payload, timeout):
        if provider["mode"] == "ollama":
            return self._request_ollama("/api/chat", ollama_payload, timeout=timeout)

        options = ollama_payload.get("options") or {}
        hosted_payload = {
            "model": provider["model"],
            "messages": ollama_payload.get("messages") or [],
            "stream": False,
            "temperature": options.get("temperature", 0),
            "top_p": options.get("top_p", 1),
            "max_tokens": options.get("num_predict", OLLAMA_REVIEW_NUM_PREDICT),
            "response_format": {"type": "json_object"},
        }
        if "seed" in options:
            hosted_payload["seed"] = options["seed"]
        response = self._request_hosted_server(provider, "/chat/completions", hosted_payload, timeout=timeout)
        error_text = str(response.get("error") or "").lower() if isinstance(response, dict) else ""
        if error_text and any(term in error_text for term in ("response_format", "seed", "unsupported", "unrecognized")):
            hosted_payload.pop("response_format", None)
            hosted_payload.pop("seed", None)
            response = self._request_hosted_server(provider, "/chat/completions", hosted_payload, timeout=timeout)
        if not isinstance(response, dict) or response.get("error"):
            return response
        choices = response.get("choices") or []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        return {
            "message": {"content": content or ""},
            "done": True,
            "done_reason": choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else "unknown",
            "prompt_eval_count": usage.get("prompt_tokens"),
            "eval_count": usage.get("completion_tokens"),
        }

    def _run_model_benchmark(self, body):
        model_name = self._extract_model_name(body)
        provider = self._resolve_model_provider(body, model_name)
        if provider.get("error"):
            return provider
        model_name = provider.get("model") or model_name
        if not model_name:
            return {"error": "Please provide a model name."}
        try:
            context_window = self._resolve_review_context_window(body, provider.get("context_limit"))
        except ValueError as exc:
            return {"error": str(exc), "model": model_name, "provider_mode": provider["mode"]}

        warmup_started = time.monotonic()
        start_result = self._start_model({"model": model_name, "context_window": context_window}) if provider["mode"] == "ollama" else {"ok": True, "status": "hosted"}
        warmup_seconds = round(time.monotonic() - warmup_started, 3)
        if not start_result.get("ok"):
            return {
                "error": start_result.get("error") or start_result.get("reason") or "The model could not be prepared for benchmarking.",
                "model": model_name,
                "benchmark_version": BENCHMARK_VERSION,
                "provider_mode": provider["mode"],
            }

        prompt = self._build_benchmark_prompt()
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "Act as a deterministic safety-critical requirements reviewer. Return only the requested JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "top_p": 1,
                "seed": 42,
                "num_ctx": context_window,
                "num_predict": 2048,
            },
            "keep_alive": MODEL_KEEP_ALIVE,
        }

        review_started = time.monotonic()
        response = self._request_model_chat(provider, payload, timeout=OLLAMA_BENCHMARK_TIMEOUT_SECONDS)
        review_seconds = round(time.monotonic() - review_started, 3)
        if isinstance(response, dict) and response.get("error"):
            return {
                "error": f"Benchmark review failed: {response['error']}",
                "model": model_name,
                "benchmark_version": BENCHMARK_VERSION,
                "provider_mode": provider["mode"],
                "warmup_seconds": warmup_seconds,
                "review_seconds": review_seconds,
            }

        benchmark_output, parse_error = self._parse_benchmark_output(response)
        score = self._score_benchmark_output(benchmark_output)
        return {
            "ok": True,
            "model": model_name,
            "benchmark_version": BENCHMARK_VERSION,
            "provider_mode": provider["mode"],
            "context_window": context_window,
            "score": score["score"],
            "metrics": score,
            "warmup_seconds": warmup_seconds,
            "review_seconds": review_seconds,
            "parse_error": parse_error,
            "model_output": benchmark_output,
            "experiment": {
                "seeded_finding_count": len(BENCHMARK_EXPECTED_FINDINGS),
                "clean_control_count": len(BENCHMARK_CONTROL_IDS),
                "temperature": 0,
                "seed": 42,
            },
        }

    def _build_benchmark_prompt(self):
        return (
            f"ASCS repeatable model benchmark version {BENCHMARK_VERSION}.\n\n"
            "Review the six simulated low-level requirements only against the four benchmark rules. "
            "Report one finding for each violated rule. Do not invent rules or findings outside this scope. "
            "A requirement with no violation must appear in pass_ids.\n\n"
            "BENCHMARK RULES:\n"
            "BENCH-R1 — If a calculation divisor can be zero, the requirement shall define deterministic zero-divisor behaviour.\n"
            "BENCH-R2 — Response-time requirements shall state a numeric upper bound and triggering event.\n"
            "BENCH-R3 — Invalid safety-related input handling shall identify the deterministic safe output or state.\n"
            "BENCH-R4 — Every low-level requirement shall identify its parent high-level requirement.\n\n"
            "SIMULATED TARGET:\n"
            "LLR-B01 | Parent: HLR-101 | Inputs: delta in [-1000,1000], duration_ms in [0,10000]. "
            "The software shall set rate = delta / duration_ms.\n"
            "LLR-B02 | Parent: HLR-102 | When overspeed becomes TRUE, the software shall quickly set warning_active to TRUE.\n"
            "LLR-B03 | Parent: HLR-103 | When sensor_valid is FALSE, the software shall handle the sensor value appropriately.\n"
            "LLR-B04 | When reset_request becomes TRUE, the software shall set command_count to 0 in the same cycle.\n"
            "LLR-B05 | Parent: HLR-105 | When enable becomes FALSE, the software shall set actuator_command to 0 within 20 ms.\n"
            "LLR-B06 | Parent: HLR-106 | Before accepting the first command after startup, the software shall set controller_state to IDLE.\n\n"
            "Return only this JSON shape:\n"
            "{\n"
            "  \"findings\": [{\"requirement_id\": \"LLR-B01\", \"rule_id\": \"BENCH-R1\", \"issue\": \"short explanation\"}],\n"
            "  \"pass_ids\": [\"LLR-B05\", \"LLR-B06\"]\n"
            "}"
        )

    def _parse_benchmark_output(self, response):
        content = ""
        if isinstance(response, dict):
            message = response.get("message")
            if isinstance(message, dict):
                content = message.get("content") or ""
            content = content or response.get("response") or ""
        content = str(content).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {"findings": [], "pass_ids": []}, "The model did not return valid benchmark JSON."
        if not isinstance(parsed, dict):
            return {"findings": [], "pass_ids": []}, "The benchmark response was not a JSON object."
        findings = parsed.get("findings") if isinstance(parsed.get("findings"), list) else []
        pass_ids = parsed.get("pass_ids") if isinstance(parsed.get("pass_ids"), list) else []
        return {"findings": findings, "pass_ids": pass_ids}, ""

    def _score_benchmark_output(self, output):
        reported = set()
        finding_control_ids = set()
        for finding in output.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            requirement_id = str(finding.get("requirement_id") or "").strip().upper()
            rule_id = str(finding.get("rule_id") or "").strip().upper()
            if requirement_id and rule_id:
                reported.add((requirement_id, rule_id))
                if requirement_id in BENCHMARK_CONTROL_IDS:
                    finding_control_ids.add(requirement_id)

        expected = set(BENCHMARK_EXPECTED_FINDINGS)
        true_positives = reported & expected
        false_positives = reported - expected
        missed = expected - reported
        precision = len(true_positives) / len(reported) if reported else 0.0
        recall = len(true_positives) / len(expected) if expected else 1.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0

        passed_ids = {str(value).strip().upper() for value in output.get("pass_ids") or []}
        correct_controls = (passed_ids & BENCHMARK_CONTROL_IDS) - finding_control_ids
        control_accuracy = len(correct_controls) / len(BENCHMARK_CONTROL_IDS)
        final_score = round((f1 * 85) + (control_accuracy * 15), 1)

        def finding_detail(key):
            return {
                "requirement_id": key[0],
                "rule_id": key[1],
                "label": BENCHMARK_EXPECTED_FINDINGS.get(key, "Unexpected finding"),
            }

        return {
            "score": final_score,
            "precision_percent": round(precision * 100, 1),
            "recall_percent": round(recall * 100, 1),
            "f1_percent": round(f1 * 100, 1),
            "control_accuracy_percent": round(control_accuracy * 100, 1),
            "true_positive_count": len(true_positives),
            "false_positive_count": len(false_positives),
            "missed_count": len(missed),
            "missed_findings": [finding_detail(key) for key in sorted(missed)],
            "unexpected_findings": [finding_detail(key) for key in sorted(false_positives)],
        }

    def _get_model_status(self):
        installed_response = self._request_ollama("/api/tags")
        running_response = self._request_ollama("/api/ps")

        installed_models = []
        if isinstance(installed_response, dict):
            installed_models = installed_response.get("models", []) or []

        running_models = {}
        if isinstance(running_response, dict):
            for model in running_response.get("models", []) or []:
                name = model.get("name") or model.get("model")
                if name:
                    running_models[name] = model

        result = []
        for model in installed_models:
            name = model.get("name") or model.get("model") or "unknown"
            details = model.get("details") or {}
            running_model = running_models.get(name) or {}
            maximum_context = self._get_ollama_model_context_limit(name, model.get("digest"))
            result.append(
                {
                    "name": name,
                    "status": "online" if name in running_models else "offline",
                    "size": model.get("size"),
                    "modified_at": model.get("modified_at"),
                    "digest": model.get("digest"),
                    "format": details.get("format"),
                    "family": details.get("family"),
                    "parameter_size": details.get("parameter_size"),
                    "quantization_level": details.get("quantization_level"),
                    "context_length": running_model.get("context_length"),
                    "max_context_length": maximum_context,
                    "size_vram": running_model.get("size_vram"),
                    "expires_at": running_model.get("expires_at"),
                }
            )

        if not result and isinstance(running_response, dict):
            for model in running_response.get("models", []) or []:
                name = model.get("name") or model.get("model") or "unknown"
                result.append({"name": name, "status": "online"})

        return {"models": result}

    def _get_ollama_model_context_limit(self, model_name, digest=None):
        cache_key = (str(model_name), str(digest or ""))
        with MODEL_CONTEXT_CACHE_LOCK:
            if cache_key in MODEL_CONTEXT_CACHE:
                return MODEL_CONTEXT_CACHE[cache_key]
        response = self._request_ollama(
            "/api/show",
            {"model": model_name},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        context_limit = self._extract_context_limit(response.get("model_info")) if isinstance(response, dict) else None
        if context_limit:
            with MODEL_CONTEXT_CACHE_LOCK:
                MODEL_CONTEXT_CACHE[cache_key] = context_limit
        return context_limit

    def _extract_context_limit(self, metadata):
        if not isinstance(metadata, dict):
            return None
        candidates = []
        recognized_keys = {"context_length", "context_window", "max_context_length", "max_model_len", "max_position_embeddings"}
        for raw_key, raw_value in metadata.items():
            key = str(raw_key).strip().lower()
            if isinstance(raw_value, dict):
                nested = self._extract_context_limit(raw_value)
                if nested:
                    candidates.append(nested)
                continue
            if key in recognized_keys or key.endswith(".context_length"):
                try:
                    value = int(raw_value)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    candidates.append(value)
        return max(candidates) if candidates else None

    def _get_rag_status(self):
        with RAG_LOCK:
            chunks = list(RAG_STORE["chunks"])
            sources = {chunk.get("source") or "knowledge" for chunk in chunks}
            vector_chunks = sum(1 for chunk in chunks if chunk.get("embedding"))
            return {
                "loaded": bool(chunks),
                "name": RAG_STORE["name"],
                "chunk_count": len(chunks),
                "source_count": len(sources),
                "vector_chunk_count": vector_chunks,
                "dimensions": RAG_STORE["dimensions"],
                "embedding_model": RAG_STORE["embedding_model"],
                "retrieval_mode": "hybrid dense vector + TF-IDF" if vector_chunks else "local TF-IDF vector",
            }

    def _clear_rag_content(self):
        global RAG_STORE
        with RAG_LOCK:
            RAG_STORE = {"name": "", "embedding_model": "", "dimensions": 0, "chunks": []}
        return {"ok": True, **self._get_rag_status()}

    def _load_rag_content(self, body):
        if not isinstance(body, dict):
            return {"error": "RAG content must be supplied as a JSON object."}

        append = bool(body.get("append"))
        if isinstance(body.get("store"), dict):
            result = self._normalize_vector_store(body["store"], body.get("name") or "Loaded vector store")
        elif isinstance(body.get("documents"), list):
            documents, errors = self._extract_uploaded_documents(body["documents"], "knowledge")
            if not documents:
                detail = f" {' '.join(errors[:3])}" if errors else ""
                return {"error": f"No readable knowledge documents were provided.{detail}"}
            result = self._build_rag_entries_from_documents(documents, body.get("name") or "Knowledge documents")
        else:
            return {"error": "Provide either a portable vector store or knowledge documents."}

        if result.get("error"):
            return result

        global RAG_STORE
        with RAG_LOCK:
            if append and RAG_STORE["dimensions"] and result["dimensions"] and RAG_STORE["dimensions"] != result["dimensions"]:
                return {"error": "Cannot append vector stores with different embedding dimensions."}
            if append and RAG_STORE["embedding_model"] and result["embedding_model"] and RAG_STORE["embedding_model"] != result["embedding_model"]:
                return {"error": "Cannot append vector stores created by different embedding models."}
            existing_chunks = list(RAG_STORE["chunks"]) if append else []
            combined_chunks = existing_chunks + result["chunks"]
            if len(combined_chunks) > RAG_MAX_CHUNKS:
                return {"error": f"The RAG store exceeds the {RAG_MAX_CHUNKS:,}-chunk safety limit."}
            if sum(len(chunk["content"]) for chunk in combined_chunks) > RAG_MAX_CONTENT_CHARS:
                return {"error": "The RAG store exceeds the 20,000,000-character safety limit."}
            RAG_STORE = {
                "name": result["name"] if not append or not RAG_STORE["name"] else RAG_STORE["name"],
                "embedding_model": result["embedding_model"] or (RAG_STORE["embedding_model"] if append else ""),
                "dimensions": result["dimensions"] or (RAG_STORE["dimensions"] if append else 0),
                "chunks": combined_chunks,
            }
        return {"ok": True, **self._get_rag_status()}

    def _normalize_vector_store(self, store, default_name):
        raw_chunks = store.get("chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            return {"error": "The vector store must contain a non-empty 'chunks' array."}
        if len(raw_chunks) > RAG_MAX_CHUNKS:
            return {"error": f"The vector store exceeds the {RAG_MAX_CHUNKS:,}-chunk safety limit."}

        embedding_model = str(store.get("embedding_model") or "").strip()
        declared_dimensions = store.get("dimensions") or 0
        try:
            declared_dimensions = int(declared_dimensions)
        except (TypeError, ValueError):
            return {"error": "Vector-store dimensions must be an integer."}
        if declared_dimensions < 0 or declared_dimensions > RAG_MAX_VECTOR_DIMENSIONS:
            return {"error": f"Vector dimensions must be between 1 and {RAG_MAX_VECTOR_DIMENSIONS}."}

        normalized = []
        detected_dimensions = 0
        total_characters = 0
        for index, chunk in enumerate(raw_chunks, start=1):
            if not isinstance(chunk, dict):
                return {"error": f"Vector-store chunk {index} must be a JSON object."}
            content = str(chunk.get("content") or chunk.get("text") or "").strip()
            if not content:
                continue
            total_characters += len(content)
            if total_characters > RAG_MAX_CONTENT_CHARS:
                return {"error": "The vector store exceeds the 20,000,000-character safety limit."}

            raw_embedding = chunk.get("embedding", chunk.get("vector"))
            embedding = []
            if raw_embedding is not None:
                if not isinstance(raw_embedding, list) or not raw_embedding:
                    return {"error": f"Vector-store chunk {index} has an invalid embedding."}
                try:
                    embedding = [float(value) for value in raw_embedding]
                except (TypeError, ValueError):
                    return {"error": f"Vector-store chunk {index} contains a non-numeric embedding value."}
                if not all(math.isfinite(value) for value in embedding):
                    return {"error": f"Vector-store chunk {index} contains a non-finite embedding value."}
                if len(embedding) > RAG_MAX_VECTOR_DIMENSIONS:
                    return {"error": f"Vector-store chunk {index} exceeds {RAG_MAX_VECTOR_DIMENSIONS} dimensions."}
                detected_dimensions = detected_dimensions or len(embedding)
                if len(embedding) != detected_dimensions:
                    return {"error": "All vector-store embeddings must have the same dimensions."}

            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            source = str(chunk.get("source") or metadata.get("source") or metadata.get("document") or default_name).strip()
            chunk_id = str(chunk.get("id") or metadata.get("id") or f"chunk-{index}").strip()
            normalized.append({"id": chunk_id, "source": source, "content": content, "embedding": embedding})

        if not normalized:
            return {"error": "The vector store did not contain readable chunk content."}
        if declared_dimensions and detected_dimensions and declared_dimensions != detected_dimensions:
            return {"error": "Declared vector dimensions do not match the chunk embeddings."}
        dimensions = detected_dimensions or declared_dimensions
        if dimensions and not embedding_model:
            embedding_model = str(store.get("model") or "").strip()
        return {
            "name": str(store.get("name") or default_name).strip(),
            "embedding_model": embedding_model,
            "dimensions": dimensions,
            "chunks": normalized,
        }

    def _build_rag_entries_from_documents(self, documents, name):
        chunks = self._chunk_documents(documents, "KNOWLEDGE")
        entries = []
        for index, content in enumerate(chunks, start=1):
            source_match = re.match(r"\[KNOWLEDGE:\s*([^|\]]+)", content)
            source = source_match.group(1).strip() if source_match else name
            entries.append({"id": f"knowledge-{index}", "source": source, "content": content, "embedding": []})
        return {"name": str(name), "embedding_model": "", "dimensions": 0, "chunks": entries}

    def _build_reviewer_response(self, body):
        if not isinstance(body, dict):
            return {"error": "The review request was not received as valid JSON. Please try again from the application."}

        try:
            prompt_configuration = self._resolve_prompt_configuration(body)
        except SkillValidationError as exc:
            return {"error": str(exc)}
        skills_prompt = prompt_configuration["skills_prompt"]
        review_goal = prompt_configuration["review_goal"]
        document_text = (body.get("document_text") or "").strip()
        requested_model = str(body.get("model") or "llama3.2").strip()
        provider = self._resolve_model_provider(body, requested_model)
        if provider.get("error"):
            return {"error": provider["error"], "review": "", "retrieved_chunks": []}
        model = provider.get("model") or requested_model
        try:
            context_window = self._resolve_review_context_window(body, provider.get("context_limit"))
        except ValueError as exc:
            return {"error": str(exc), "review": "", "retrieved_chunks": [], "model": model, "provider_mode": provider["mode"]}
        documents = body.get("documents") or []
        d0178c_context = (body.get("d0178c_context") or "").strip()
        reference_document_entries = body.get("reference_documents") or []
        rag_options = body.get("rag") if isinstance(body.get("rag"), dict) else {}
        rag_enabled = rag_options.get("enabled", True) is not False
        try:
            retrieval_limit = max(4, min(40, int(rag_options.get("max_chunks") or 24)))
        except (TypeError, ValueError):
            retrieval_limit = 24

        if documents:
            target_documents, document_errors = self._extract_uploaded_documents(documents, "document")
            if not target_documents:
                detail = f" {' '.join(document_errors[:3])}" if document_errors else ""
                return {"error": f"No readable document content was provided.{detail}"}
        elif document_text:
            target_documents = [{"name": "pasted-document", "content": document_text}]
        else:
            return {"error": "Please provide documentation text or files to review."}

        reference_documents = self._collect_reference_documents(d0178c_context, reference_document_entries)
        rag_status = self._get_rag_status()
        source_count = len(target_documents) + len(reference_documents) + (rag_status["source_count"] if rag_enabled else 0)

        if provider["mode"] == "ollama":
            readiness = self._check_model_readiness(model)
            if not readiness["ready"]:
                return {
                    "error": readiness["reason"],
                    "review": "",
                    "retrieved_chunks": [],
                    "model": model,
                    "provider_mode": provider["mode"],
                    "context_window": context_window,
                    "source_count": source_count,
                }

        target_chunks = self._chunk_documents(target_documents, "TARGET")
        reference_chunks = self._chunk_documents(reference_documents, "REFERENCE")
        target_context_text = self._build_complete_target_context(target_chunks)
        retrieval_query = " ".join([skills_prompt, review_goal, target_context_text])
        retrieved_reference = self._retrieve_relevant_chunks(
            reference_chunks, skills_prompt, review_goal, target_context_text, limit=retrieval_limit
        )
        retrieved_rag = self._retrieve_rag_chunks(retrieval_query, retrieval_limit) if rag_enabled else []
        retrieval_candidates = self._interleave_chunks(retrieved_reference, retrieved_rag)
        retrieval_budget = self._calculate_retrieval_budget(
            len(target_context_text), len(skills_prompt) + len(review_goal), context_window
        )
        selected_reference = self._select_chunks_with_budget(retrieval_candidates, retrieval_limit, retrieval_budget)
        reference_context_text = "\n\n".join(selected_reference) if selected_reference else "No reference material was provided."
        retrieval_summary = {
            "enabled": rag_enabled,
            "context_window_tokens": context_window,
            "available_chunks": len(reference_chunks) + (rag_status["chunk_count"] if rag_enabled else 0),
            "selected_chunks": len(selected_reference),
            "context_budget_characters": retrieval_budget,
            "loaded_store": rag_status["name"] if rag_enabled else "",
            "retrieval_mode": rag_status["retrieval_mode"] if rag_enabled and rag_status["loaded"] else "local TF-IDF vector",
            "vector_chunks": rag_status["vector_chunk_count"] if rag_enabled else 0,
        }

        user_prompt = self._build_review_prompt(prompt_configuration["prompt_configuration"], target_context_text, reference_context_text)
        prompt_length = len(user_prompt)

        ollama_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": prompt_configuration["prompt_configuration"]["reviewer_role"],
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "stream": False,
            "format": "json",
            "options": self._build_review_model_options(prompt_length, context_window),
            "keep_alive": MODEL_KEEP_ALIVE,
        }

        response = self._request_model_chat(provider, ollama_payload, timeout=OLLAMA_REVIEW_TIMEOUT_SECONDS)
        if isinstance(response, dict) and response.get("error"):
            diagnostic_reason = (
                self._diagnose_prompt_failure(response["error"], model, prompt_length, source_count)
                if provider["mode"] == "ollama"
                else f"Hosted review request failed for {model}: {response['error']}"
            )
            return {
                "error": diagnostic_reason,
                "review": "",
                "retrieved_chunks": target_chunks[:6] + selected_reference[:6],
                "model": model,
                "provider_mode": provider["mode"],
                "context_window": context_window,
                "source_count": source_count,
                "retrieval": retrieval_summary,
            }

        review_text, extraction_error = self._extract_review_text(response)
        if extraction_error:
            return {
                "error": extraction_error,
                "review": "",
                "retrieved_chunks": target_chunks[:6] + selected_reference[:6],
                "model": model,
                "provider_mode": provider["mode"],
                "context_window": context_window,
                "source_count": source_count,
                "retrieval": retrieval_summary,
            }
        review_result = self._parse_review_result(review_text)
        return {
            "review": review_result.get("summary") or review_text.strip(),
            "review_result": review_result,
            "retrieved_chunks": target_chunks[:6] + selected_reference[:6],
            "model": model,
            "provider_mode": provider["mode"],
            "context_window": context_window,
            "source_count": source_count,
            "retrieval": retrieval_summary,
            "prompt_mode": prompt_configuration["prompt_mode"],
            "skill_name": prompt_configuration.get("skill_name"),
        }

    def _resolve_prompt_configuration(self, body):
        prompt_mode = str(body.get("prompt_mode") or "skill").strip().lower()
        if prompt_mode == "skill":
            composed = SKILL_STORE.compose(body.get("skill_id") or "general-review", body.get("skill_answers"))
            return {**composed, "prompt_mode": "skill"}
        if prompt_mode != "custom":
            raise SkillValidationError("Prompt mode must be 'skill' or 'custom'.")

        custom = body.get("custom_prompt")
        if not isinstance(custom, dict):
            raise SkillValidationError("Custom prompt fields must be supplied as a JSON object.")
        allowed_fields = {
            "reviewer_role",
            "objective",
            "review_method",
            "additional_checks",
        }
        unknown_fields = sorted(set(custom) - allowed_fields)
        if unknown_fields:
            raise SkillValidationError(f"Unknown custom prompt field(s): {', '.join(unknown_fields)}")

        values = {}
        for field in allowed_fields:
            value = custom.get(field, "")
            if not isinstance(value, str):
                raise SkillValidationError(f"Custom field {field!r} must be text.")
            values[field] = value.strip()
        if not values["reviewer_role"]:
            raise SkillValidationError("Reviewer role is required in custom mode.")
        if not values["objective"]:
            raise SkillValidationError("Review objective is required in custom mode.")

        configured_instructions = []
        labels = (
            ("review_method", "Review method"),
            ("additional_checks", "Additional checks"),
        )
        configured_instructions.extend(f"{label}: {values[field]}" for field, label in labels if values[field])
        review_sections = [
            {
                "title": "Scope and applicable obligations",
                "instruction": "Review scope, applicability, assumptions, dependencies, governing plans, standards, requirements, instructions, and declared compliance obligations.",
            },
            {
                "title": "Completeness, correctness and clarity",
                "instruction": "Review every applicable statement for completeness, correctness, necessity, clarity, atomicity, unambiguity, consistency, and feasible implementation.",
            },
            {
                "title": "Safety and failure behaviour",
                "instruction": "Review hazards, safety objectives, assumptions, allocations, modes, interfaces, invalid inputs, degraded behaviour, recovery, and safe failure response.",
            },
            {
                "title": "Lifecycle, governance and control",
                "instruction": "Review responsibilities, independence, activities, inputs, outputs, entry and exit criteria, approvals, configuration control, changes, deviations, anomalies, and retained records.",
            },
            {
                "title": "Traceability and consistency",
                "instruction": "Review forward and reverse traceability, cross-document consistency, derived content, orphan content, duplication, conflicts, and complete allocation.",
            },
            {
                "title": "Verification and objective evidence",
                "instruction": "Review measurable acceptance criteria, verification methods, normal and robustness coverage, repeatability, objective evidence, tools, environments, and closure status.",
            },
            {
                "title": "Presentation and controlled use",
                "instruction": "Review structure, identifiers, terminology, cross-references, tables, readability, spelling, grammar, revision status, and suitability for controlled engineering use.",
            },
        ]
        if values["additional_checks"]:
            review_sections.append(
                {
                    "title": "User-supplied additional checks",
                    "instruction": values["additional_checks"],
                }
            )
        prompt_configuration = {
            "reviewer_role": values["reviewer_role"],
            "objective": values["objective"],
            "instructions": configured_instructions,
            "review_sections": review_sections,
        }
        return {
            "prompt_mode": "custom",
            "skill_id": None,
            "skill_name": "Custom review",
            "skills_prompt": "\n".join([values["reviewer_role"], values["objective"], *configured_instructions]),
            "review_goal": values["objective"],
            "prompt_configuration": prompt_configuration,
        }

    def _build_traceability_response(self, body):
        if not isinstance(body, dict):
            return {"error": "The traceability request was not received as valid JSON."}

        document_text = (body.get("document_text") or "").strip()
        documents = body.get("documents") or []
        d0178c_context = (body.get("d0178c_context") or "").strip()
        reference_document_entries = body.get("reference_documents") or []

        if documents:
            target_documents, document_errors = self._extract_uploaded_documents(documents, "document")
            if not target_documents:
                detail = f" {' '.join(document_errors[:3])}" if document_errors else ""
                return {"error": f"No readable target document content was provided.{detail}"}
        elif document_text:
            target_documents = [{"name": "pasted-document", "content": document_text}]
        else:
            return {"error": "Please provide target documentation before running traceability analysis."}

        reference_documents = self._collect_reference_documents(d0178c_context, reference_document_entries)
        artefacts = []
        for index, document in enumerate(target_documents, start=1):
            artefacts.append(self._build_traceability_artefact(document, "target", f"target-{index}"))
        for index, document in enumerate(reference_documents, start=1):
            if document.get("name") == "DO-178C-context":
                continue
            artefacts.append(self._build_traceability_artefact(document, "associated", f"associated-{index}"))

        all_requirements = []
        for artefact in artefacts:
            all_requirements.extend(artefact["requirements"])

        relationships = self._build_traceability_relationships(all_requirements)
        diagnostics = self._build_traceability_diagnostics(all_requirements, relationships)
        return {
            "summary": {
                "artefact_count": len(artefacts),
                "requirement_count": len(all_requirements),
                "linked_requirement_count": diagnostics["linked_requirement_count"],
                "complete_requirement_count": diagnostics["complete_requirement_count"],
                "coverage_percent": diagnostics["coverage_percent"],
                "gap_count": len(diagnostics["gaps"]),
                "unresolved_reference_count": len(relationships["unresolved_mentions"]),
                "ambiguous_reference_count": len(relationships["ambiguous_references"]),
                "duplicate_id_count": len(relationships["duplicate_ids"]),
            },
            "artefacts": artefacts,
            "forward": relationships["forward"],
            "reverse": relationships["reverse"],
            "unresolved_mentions": relationships["unresolved_mentions"],
            "ambiguous_references": relationships["ambiguous_references"],
            "duplicate_ids": relationships["duplicate_ids"],
            "coverage_by_type": diagnostics["coverage_by_type"],
            "gaps": diagnostics["gaps"],
            "integrity_issues": diagnostics["integrity_issues"],
            "matrix": diagnostics["matrix"],
        }

    def _build_traceability_artefact(self, document, role, artefact_uid=None):
        name = document.get("name") or "document"
        artefact_uid = artefact_uid or f"{role}-1"
        artefact_type = self._infer_artefact_type(name, document.get("content") or "")
        requirements = self._extract_requirements_from_document(document, role, artefact_type, artefact_uid)
        return {
            "uid": artefact_uid,
            "name": name,
            "role": role,
            "artefact_type": artefact_type,
            "requirements": requirements,
        }

    def _infer_artefact_type(self, name, content):
        name_text = (name or "").upper()
        for artefact_type in ("LLRV", "SRATS", "HLR", "LLR", "SR"):
            if re.search(rf"\b{artefact_type}\b|[-_]{artefact_type}[-_]", name_text):
                return artefact_type
        content_text = (content or "")[:2000].upper()
        for artefact_type in ("LLRV", "SRATS", "HLR", "LLR", "SR"):
            if re.search(rf"\b{artefact_type}\b|[-_]{artefact_type}[-_]", content_text):
                return artefact_type
        return "OTHER"

    def _extract_requirements_from_document(self, document, role, artefact_type, artefact_uid):
        name = document.get("name") or "document"
        content = (document.get("content") or "").strip()
        if not content:
            return []

        blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
        if len(blocks) <= 1:
            blocks = [line.strip() for line in content.splitlines() if line.strip()]

        requirements = []
        occurrence_counts = {}
        for block_index, block in enumerate(blocks, start=1):
            requirement_id = self._select_defined_requirement_id(block)
            if not requirement_id:
                continue
            normalized_id = self._normalize_requirement_id(requirement_id)
            occurrence_counts[normalized_id] = occurrence_counts.get(normalized_id, 0) + 1
            occurrence = occurrence_counts[normalized_id]
            requirements.append(
                {
                    "id": requirement_id,
                    "normalized_id": normalized_id,
                    "uid": f"{artefact_uid}::{normalized_id}::{occurrence}",
                    "content": self._compact_requirement_content(block),
                    "mentions": self._find_requirement_mentions(block, requirement_id),
                    "document": name,
                    "role": role,
                    "artefact_type": self._infer_requirement_type(requirement_id, artefact_type),
                    "occurrence": occurrence,
                    "source_block": block_index,
                }
            )
        return requirements

    def _select_defined_requirement_id(self, block):
        candidates = self._find_requirement_ids(block)
        if not candidates:
            return None

        compact = re.sub(r"\s+", " ", (block or "").strip())
        for candidate in candidates:
            escaped = re.escape(candidate)
            if re.match(rf"^{escaped}(?![A-Z0-9])", compact, re.IGNORECASE):
                return candidate
            if re.match(rf"^(?:requirement id|requirement|req id|id)\s*[:=-]?\s*{escaped}(?![A-Z0-9])", compact, re.IGNORECASE):
                return candidate
            if re.match(rf"^Row\s+[^:]+:.*?=\s*{escaped}(?![A-Z0-9])", compact, re.IGNORECASE):
                return candidate
        return None

    def _find_requirement_ids(self, text):
        seen = set()
        result = []
        for match in REQUIREMENT_ID_PATTERN.finditer(text or ""):
            requirement_id = self._normalize_requirement_id(match.group(0))
            key = requirement_id
            if key not in seen:
                seen.add(key)
                result.append(requirement_id)
        return result

    def _normalize_requirement_id(self, requirement_id):
        return re.sub(r"[\s_]+", "-", str(requirement_id or "").strip()).upper()

    def _infer_requirement_type(self, requirement_id, fallback="OTHER"):
        normalized = self._normalize_requirement_id(requirement_id)
        for artefact_type in ("LLRV", "SRATS", "HLR", "LLR"):
            if re.search(rf"(?:^|-){artefact_type}(?:-|$)", normalized):
                return artefact_type
        if re.search(r"(?:^|-)(?:SRAT|SR)(?:-|$)", normalized):
            return "SR"
        return fallback

    def _compact_requirement_content(self, text, limit=650):
        content = re.sub(r"\s+", " ", (text or "").strip())
        if len(content) <= limit:
            return content
        return content[: limit - 3].rstrip() + "..."

    def _find_requirement_mentions(self, content, own_id):
        own_key = self._normalize_requirement_id(own_id)
        return [requirement_id for requirement_id in self._find_requirement_ids(content) if requirement_id != own_key]

    def _build_traceability_relationships(self, requirements):
        by_id = {}
        for requirement in requirements:
            by_id.setdefault(requirement["normalized_id"], []).append(requirement)

        duplicate_ids = [
            {
                "id": normalized_id,
                "occurrences": [
                    {
                        "uid": requirement["uid"],
                        "document": requirement["document"],
                        "source_block": requirement["source_block"],
                        "content": requirement["content"],
                    }
                    for requirement in matches
                ],
            }
            for normalized_id, matches in sorted(by_id.items())
            if len(matches) > 1
        ]
        forward = []
        reverse = []
        unresolved_mentions = []
        ambiguous_references = []
        seen_pairs = set()

        for requirement in requirements:
            source_order = ARTEFACT_ORDER.get(requirement["artefact_type"], 99)
            for mentioned_id in requirement.get("mentions", []):
                normalized_mention = self._normalize_requirement_id(mentioned_id)
                targets = by_id.get(normalized_mention, [])
                if not targets:
                    unresolved_mentions.append(
                        {
                            "source_uid": requirement["uid"],
                            "source_id": requirement["id"],
                            "source_document": requirement["document"],
                            "mentioned_id": normalized_mention,
                        }
                    )
                    continue
                if len(targets) > 1:
                    ambiguous_references.append(
                        {
                            "source_uid": requirement["uid"],
                            "source_id": requirement["id"],
                            "source_document": requirement["document"],
                            "mentioned_id": normalized_mention,
                            "candidate_uids": [target["uid"] for target in targets],
                        }
                    )
                    continue

                target = targets[0]
                target_order = ARTEFACT_ORDER.get(target["artefact_type"], 99)
                if source_order < target_order:
                    upstream = requirement
                    downstream = target
                elif target_order < source_order:
                    upstream = target
                    downstream = requirement
                else:
                    upstream = requirement
                    downstream = target

                relationship_kind = (
                    "same-level"
                    if source_order == target_order
                    else "adjacent"
                    if abs(source_order - target_order) == 1
                    else "cross-level"
                )
                pair_key = (
                    tuple(sorted((upstream["uid"], downstream["uid"])))
                    if relationship_kind == "same-level"
                    else (upstream["uid"], downstream["uid"])
                )
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                link = {
                    "source_uid": upstream["uid"],
                    "source_id": upstream["id"],
                    "source_document": upstream["document"],
                    "source_type": upstream["artefact_type"],
                    "target_uid": downstream["uid"],
                    "target_id": downstream["id"],
                    "target_document": downstream["document"],
                    "target_type": downstream["artefact_type"],
                    "relationship_kind": relationship_kind,
                }
                forward.append(link)
                reverse.append(
                    {
                        "source_uid": downstream["uid"],
                        "source_id": downstream["id"],
                        "source_document": downstream["document"],
                        "source_type": downstream["artefact_type"],
                        "target_uid": upstream["uid"],
                        "target_id": upstream["id"],
                        "target_document": upstream["document"],
                        "target_type": upstream["artefact_type"],
                        "relationship_kind": relationship_kind,
                    }
                )

        forward.sort(key=lambda item: (ARTEFACT_ORDER.get(item["source_type"], 99), item["source_id"], item["target_id"]))
        reverse.sort(key=lambda item: (ARTEFACT_ORDER.get(item["source_type"], 99), item["source_id"], item["target_id"]), reverse=True)
        return {
            "forward": forward,
            "reverse": reverse,
            "unresolved_mentions": unresolved_mentions,
            "ambiguous_references": ambiguous_references,
            "duplicate_ids": duplicate_ids,
        }

    def _build_traceability_diagnostics(self, requirements, relationships):
        forward = relationships["forward"]
        incoming = {requirement["uid"]: [] for requirement in requirements}
        outgoing = {requirement["uid"]: [] for requirement in requirements}
        lateral = {requirement["uid"]: [] for requirement in requirements}
        for link in forward:
            if link["relationship_kind"] == "same-level":
                lateral[link["source_uid"]].append(link)
                lateral[link["target_uid"]].append(link)
            else:
                outgoing[link["source_uid"]].append(link)
                incoming[link["target_uid"]].append(link)

        active_orders = sorted(
            {
                ARTEFACT_ORDER[requirement["artefact_type"]]
                for requirement in requirements
                if requirement["artefact_type"] in ARTEFACT_ORDER
            }
        )
        duplicate_uids = {
            occurrence["uid"]
            for duplicate in relationships["duplicate_ids"]
            for occurrence in duplicate["occurrences"]
        }
        gaps = []
        linked_requirement_count = 0
        complete_requirement_count = 0

        for requirement in requirements:
            uid = requirement["uid"]
            artefact_order = ARTEFACT_ORDER.get(requirement["artefact_type"])
            has_upstream = bool(incoming[uid])
            has_downstream = bool(outgoing[uid])
            has_lateral = bool(lateral[uid])
            is_linked = has_upstream or has_downstream or has_lateral
            if is_linked and uid not in duplicate_uids:
                linked_requirement_count += 1

            expects_upstream = artefact_order is not None and any(order < artefact_order for order in active_orders)
            expects_downstream = artefact_order is not None and any(order > artefact_order for order in active_orders)
            missing_directions = []
            if expects_upstream and not has_upstream:
                missing_directions.append("upstream")
                gaps.append(self._traceability_gap(requirement, "missing-upstream", "No link to an available upstream lifecycle level."))
            if expects_downstream and not has_downstream:
                missing_directions.append("downstream")
                gaps.append(self._traceability_gap(requirement, "missing-downstream", "No link to an available downstream lifecycle level."))

            if uid in duplicate_uids:
                trace_status = "duplicate"
            elif not is_linked:
                trace_status = "unlinked"
            elif missing_directions:
                trace_status = "partial"
            else:
                trace_status = "complete"
                complete_requirement_count += 1

            requirement["trace_status"] = trace_status
            requirement["upstream_link_count"] = len(incoming[uid])
            requirement["downstream_link_count"] = len(outgoing[uid])
            requirement["lateral_link_count"] = len(lateral[uid])

        coverage_by_type = []
        for artefact_type in sorted({item["artefact_type"] for item in requirements}, key=lambda item: ARTEFACT_ORDER.get(item, 99)):
            typed_requirements = [item for item in requirements if item["artefact_type"] == artefact_type]
            linked = [item for item in typed_requirements if item["trace_status"] not in {"unlinked", "duplicate"}]
            complete = [item for item in typed_requirements if item["trace_status"] == "complete"]
            coverage_by_type.append(
                {
                    "artefact_type": artefact_type,
                    "requirement_count": len(typed_requirements),
                    "linked_count": len(linked),
                    "complete_count": len(complete),
                    "coverage_percent": self._percentage(len(linked), len(typed_requirements)),
                }
            )

        integrity_issues = []
        integrity_issues.extend(
            {
                "severity": "error",
                "kind": "duplicate-id",
                "message": f"{item['id']} is defined {len(item['occurrences'])} times.",
            }
            for item in relationships["duplicate_ids"]
        )
        integrity_issues.extend(
            {
                "severity": "error",
                "kind": "unresolved-reference",
                "message": f"{item['source_id']} references missing {item['mentioned_id']}.",
            }
            for item in relationships["unresolved_mentions"]
        )
        integrity_issues.extend(
            {
                "severity": "error",
                "kind": "ambiguous-reference",
                "message": f"{item['source_id']} references duplicate {item['mentioned_id']}.",
            }
            for item in relationships["ambiguous_references"]
        )
        integrity_issues.extend(
            {
                "severity": "warning",
                "kind": "cross-level-link",
                "message": f"{link['source_id']} links directly to {link['target_id']}, skipping a lifecycle level.",
            }
            for link in forward
            if link["relationship_kind"] == "cross-level"
        )
        integrity_issues.extend(
            {
                "severity": "warning",
                "kind": "unlinked-requirement",
                "message": f"{requirement['id']} in {requirement['document']} has no resolved trace links.",
            }
            for requirement in requirements
            if requirement["trace_status"] == "unlinked"
        )

        matrix = [
            {
                "source": link["source_id"],
                "source_type": link["source_type"],
                "source_document": link["source_document"],
                "target": link["target_id"],
                "target_type": link["target_type"],
                "target_document": link["target_document"],
                "relationship_kind": link["relationship_kind"],
            }
            for link in forward
        ]
        requirement_count = len(requirements)
        return {
            "linked_requirement_count": linked_requirement_count,
            "complete_requirement_count": complete_requirement_count,
            "coverage_percent": self._percentage(linked_requirement_count, requirement_count),
            "coverage_by_type": coverage_by_type,
            "gaps": gaps,
            "integrity_issues": integrity_issues,
            "matrix": matrix,
        }

    def _traceability_gap(self, requirement, kind, message):
        return {
            "severity": "warning",
            "kind": kind,
            "requirement_uid": requirement["uid"],
            "requirement_id": requirement["id"],
            "artefact_type": requirement["artefact_type"],
            "document": requirement["document"],
            "message": message,
        }

    def _percentage(self, numerator, denominator):
        return round((numerator / denominator) * 100, 1) if denominator else 0.0

    def _check_model_readiness(self, model):
        installed_response = self._request_ollama("/api/tags")
        running_response = self._request_ollama("/api/ps")

        if isinstance(installed_response, dict) and installed_response.get("error"):
            return {"ready": False, "reason": f"Ollama returned an error while checking installed models: {installed_response['error']}"}

        installed_names = set()
        if isinstance(installed_response, dict):
            for entry in installed_response.get("models", []) or []:
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("model")
                    if name:
                        installed_names.add(name)

        if model not in installed_names:
            return {"ready": False, "reason": f"The selected model {model} is not installed locally. Pull it first with: ollama pull {model}."}

        running_names = set()
        if isinstance(running_response, dict):
            for entry in running_response.get("models", []) or []:
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("model")
                    if name:
                        running_names.add(name)

        if model not in running_names:
            return {"ready": False, "reason": f"The selected model {model} is installed but not currently running. Start it from the application or wait a moment for Ollama to load it before reviewing."}

        readiness = self._probe_model_response(model)
        if not readiness["ready"]:
            return {"ready": False, "reason": readiness["reason"]}

        return {"ready": True, "reason": readiness["reason"]}

    def _build_review_prompt(self, prompt_configuration, target_context_text, reference_context_text):
        reviewer_role = prompt_configuration["reviewer_role"]
        objective = prompt_configuration["objective"]
        instructions = prompt_configuration.get("instructions") or []
        review_sections = prompt_configuration["review_sections"]
        section_contract = [
            {
                "title": section["title"],
                "content": (
                    f"{section['instruction']} Perform every applicable check in this section. For each distinct "
                    "issue, provide Location, Rule violated, Rule evidence, Issue, Evidence, and Target fix. "
                    "If every check passes, state that explicitly; identify non-applicable checks and why."
                ),
            }
            for section in review_sections
        ]
        output_contract = {
            "summary": "Short overall assessment",
            "sections": section_contract,
            "atomic_comments": [
                {
                    "id": "A1",
                    "location": "TARGET document, section and paragraph/row label",
                    "violated_rule": "REFERENCE rule identifier/title, or Not found in provided reference material",
                    "rule_evidence": "Short paraphrase of the governing obligation",
                    "issue": "Short target-document issue description",
                    "comment": "Atomic comment to resolve in the TARGET document",
                    "suggested_resolution": "Actionable change to the TARGET document",
                }
            ],
        }
        configured_instructions = "\n".join(f"- {instruction}" for instruction in instructions)

        return (
            f"Reviewer role:\n{reviewer_role}\n\n"
            "Review only the supplied TARGET document(s). Read the complete TARGET in document order and "
            "use the highest available review effort. Treat REFERENCE material only as standards, guidance, "
            "or comparison evidence; do not critique or propose changes to REFERENCE documents.\n\n"
            f"Review objective:\n{objective}\n\n"
            f"Configured instructions:\n{configured_instructions or '- Apply the review objective directly.'}\n\n"
            "Complete-checklist rules:\n"
            "- Execute every configured review section with equal diligence; no section is optional or secondary.\n"
            "- Check every applicable target statement against every applicable supplied plan, standard, requirement, and instruction.\n"
            "- Do not sample, omit lower-severity checks, or stop after finding significant issues.\n"
            "- Treat user-supplied context as additive; it must never narrow or replace the complete checklist.\n"
            "- Record a clear pass or justified not-applicable result when a section produces no finding.\n\n"
            "Evidence rules:\n"
            "- Report a finding only when it applies to the TARGET and is supported by target evidence.\n"
            "- Give the exact TARGET document, section, and paragraph/row label. Never invent page numbers.\n"
            "- Identify the governing REFERENCE rule when available and explain its obligation separately.\n"
            "- If no governing rule is supplied, write 'Not found in provided reference material'.\n"
            "- For interface findings, first compare the target against any supplied interface definition.\n"
            "- Keep each issue atomic and repeat it in atomic_comments.\n\n"
            f"Complete TARGET content:\n{target_context_text}\n\n"
            f"REFERENCE material:\n{reference_context_text}\n\n"
            "Return only valid JSON matching this configured contract:\n"
            f"{json.dumps(output_contract, ensure_ascii=False, indent=2)}"
        )

    def _parse_review_result(self, review_text):
        if not review_text:
            return {"summary": "No review returned.", "sections": [], "atomic_comments": []}

        text = review_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {
                "summary": text,
                "sections": [{"title": "Review", "content": text}],
                "atomic_comments": [],
            }

        if not isinstance(parsed, dict):
            return {"summary": str(parsed), "sections": [], "atomic_comments": []}

        sections = parsed.get("sections") or []
        if not isinstance(sections, list):
            sections = []

        atomic_comments = parsed.get("atomic_comments") or []
        if not isinstance(atomic_comments, list):
            atomic_comments = []

        normalized_sections = [
            {
                "title": section.get("title") or "Review",
                "content": self._remove_page_references_from_locations(section.get("content") or ""),
            }
            for section in sections
            if isinstance(section, dict)
        ]
        normalized_comments = [
            {
                "id": comment.get("id") or f"A{index + 1}",
                "location": self._normalize_location_label(comment.get("location") or ""),
                "violated_rule": self._normalize_rule_label(
                    comment.get("violated_rule")
                    or comment.get("rule_violated")
                    or comment.get("applicable_rule")
                    or comment.get("rule")
                    or ""
                ),
                "rule_evidence": comment.get("rule_evidence") or comment.get("rule_reference") or "",
                "issue": comment.get("issue") or "Issue",
                "comment": comment.get("comment") or "",
                "suggested_resolution": comment.get("suggested_resolution") or "",
            }
            for index, comment in enumerate(atomic_comments)
            if isinstance(comment, dict)
        ]
        normalized_comments = self._ensure_atomic_comments_cover_section_issues(normalized_sections, normalized_comments)

        return {
            "summary": parsed.get("summary") or "Review completed.",
            "sections": normalized_sections,
            "atomic_comments": normalized_comments,
        }

    def _extract_review_text(self, response):
        if not isinstance(response, dict):
            return "", "Ollama returned an unexpected review response."

        message = response.get("message") or {}
        content = message.get("content") or ""
        if content.strip():
            return content, ""

        thinking = message.get("thinking") or response.get("thinking") or ""
        if thinking.strip():
            done_reason = response.get("done_reason") or "unknown"
            return (
                "",
                "The selected model responded only with internal reasoning and did not produce the final JSON review. "
                f"Ollama ended with reason '{done_reason}'. Increase OLLAMA_REVIEW_NUM_PREDICT, use a faster/non-reasoning model, or reduce the complete review batch size.",
            )

        return "", "The selected model returned an empty review response."

    def _ensure_atomic_comments_cover_section_issues(self, sections, atomic_comments):
        comments = list(atomic_comments)
        seen_keys = {
            self._comment_key(comment.get("location", ""), comment.get("issue", ""))
            for comment in comments
        }

        for section in sections:
            for issue in self._extract_section_issue_blocks(section.get("content") or ""):
                key = self._comment_key(issue["location"], issue["issue"])
                if key in seen_keys:
                    continue
                comments.append(
                    {
                        "id": f"A{len(comments) + 1}",
                        "location": issue["location"],
                        "violated_rule": issue["violated_rule"],
                        "rule_evidence": issue["rule_evidence"],
                        "issue": issue["issue"],
                        "comment": issue["comment"],
                        "suggested_resolution": issue["suggested_resolution"],
                    }
                )
                seen_keys.add(key)
        return comments

    def _extract_section_issue_blocks(self, content):
        issue_blocks = []
        matches = list(re.finditer(r"(?im)^\s*(?:(?:[-*]|\d+[\).])\s*)?Location:\s*", content))
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[start:end].strip()
            if not block:
                continue
            issue_blocks.append(self._parse_section_issue_block(block))
        return issue_blocks

    def _parse_section_issue_block(self, block):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        first_line = lines[0] if lines else block
        location_text = ""
        issue_text = first_line
        match = re.match(r"(?i)(?:(?:[-*]|\d+[\).])\s*)?Location:\s*(.+?)(?:\s+-\s+|\s+--\s+|\s+Issue:\s+)(.+)$", first_line)
        if match:
            location_text = match.group(1).strip()
            issue_text = match.group(2).strip()
        else:
            location_match = re.match(r"(?i)(?:(?:[-*]|\d+[\).])\s*)?Location:\s*(.+)$", first_line)
            if location_match:
                location_text = location_match.group(1).strip()

        rule_lines = [
            re.sub(r"(?i)^(rule violated|violated rule|applicable rule|rule):\s*", "", line).strip()
            for line in lines[1:]
            if re.match(r"(?i)rule violated:|violated rule:|applicable rule:|rule:", line)
        ]
        rule_evidence_lines = [
            re.sub(r"(?i)^(rule evidence|reference evidence|rule text):\s*", "", line).strip()
            for line in lines[1:]
            if re.match(r"(?i)rule evidence:|reference evidence:|rule text:", line)
        ]
        issue_lines = [
            re.sub(r"(?i)^issue:\s*", "", line).strip()
            for line in lines[1:]
            if re.match(r"(?i)issue:", line)
        ]
        evidence_lines = [
            line for line in lines[1:]
            if not re.match(r"(?i)target fix:|suggested resolution:|rule violated:|violated rule:|applicable rule:|rule:|rule evidence:|reference evidence:|rule text:|issue:", line)
        ]
        fix_lines = [
            re.sub(r"(?i)^(target fix|suggested resolution):\s*", "", line).strip()
            for line in lines[1:]
            if re.match(r"(?i)target fix:|suggested resolution:", line)
        ]

        return {
            "location": self._normalize_location_label(location_text),
            "violated_rule": self._normalize_rule_label(" ".join(rule_lines)),
            "rule_evidence": " ".join(rule_evidence_lines).strip(),
            "issue": " ".join(issue_lines).strip() or issue_text,
            "comment": " ".join(evidence_lines).strip() or block,
            "suggested_resolution": " ".join(fix_lines).strip() or "Update the target document to resolve this issue.",
        }

    def _comment_key(self, location, issue):
        key = f"{location} {issue}".lower()
        return re.sub(r"\s+", " ", key).strip()

    def _remove_page_references_from_locations(self, content):
        lines = []
        for line in (content or "").splitlines():
            match = re.match(r"^(\s*(?:(?:[-*]|\d+[\).])\s*)?Location:\s*)(.*)$", line, re.IGNORECASE)
            if match:
                lines.append(match.group(1) + self._normalize_location_label(match.group(2)))
            else:
                lines.append(line)
        return "\n".join(lines)

    def _normalize_location_label(self, location):
        text = re.sub(r"\s+", " ", (location or "").strip())
        if not text:
            return ""
        text = self._replace_repeated_document_section(text)
        text = re.sub(r"(?i)\bpage\s+(?:not available in source|\d+(?:\s*\([^)]*\))?)\s*,?\s*", "", text)
        text = re.sub(r"(?i)\|\s*page\s+(?:not available in source|\d+(?:\s*\([^)]*\))?)\s*\|?", "|", text)
        text = re.sub(r"\s*\|\s*", " | ", text)
        text = re.sub(r"^\|\s*|\s*\|$", "", text)
        text = re.sub(r"\s+,", ",", text)
        return text.strip(" ,-")

    def _replace_repeated_document_section(self, text):
        document_match = re.match(r"(?i)^\s*(?:TARGET|REFERENCE)?\s*:?\s*(?:document\s+)?([^|,]+?)(?:\s*\|\s*|,\s*)section\s+", text)
        if not document_match:
            return text
        document_name = document_match.group(1).strip().lower()

        def replace_match(match):
            repeated_name = match.group(1).strip().lower()
            if repeated_name == document_name:
                return "section not resolved"
            return match.group(0)

        return re.sub(r"(?i)section\s+Document\s+([^|,]+)", replace_match, text, count=1)

    def _normalize_rule_label(self, rule):
        text = self._normalize_location_label(rule)
        if not text:
            return "Not found in provided reference material"
        return text

    def _diagnose_prompt_failure(self, error_message, model, prompt_length, source_count):
        lowered = error_message.lower()
        if "timed out" in lowered or "timeout" in lowered:
            if prompt_length > 22000:
                return f"The prompt likely exceeded the response budget for a complete-document review. The documentation is large ({source_count} source document(s)); try a model with a larger context window or split the material into smaller complete review batches."
            return f"The prompt timed out while Ollama was generating a response for {model}. The model may still be loading, or the request may be too heavy for the current setup."
        if "unable to reach" in lowered or "connection" in lowered:
            return f"ASCS Reviewer could not reach Ollama at {OLLAMA_BASE_URL}. Check the Ollama service and ensure it is listening on the expected port."
        if "not found" in lowered:
            return f"The selected model {model} was not found locally. Pull it first with: ollama pull {model}."
        return f"The review request failed: {error_message}"

    def _collect_reference_documents(self, d0178c_context, reference_document_entries=None):
        documents = []
        if d0178c_context.strip():
            documents.append({"name": "DO-178C-context", "content": d0178c_context.strip()})

        uploaded_documents, _ = self._extract_uploaded_documents(reference_document_entries or [], "reference")
        documents.extend(uploaded_documents)

        return documents

    def _extract_uploaded_documents(self, entries, default_name):
        documents = []
        errors = []
        if not isinstance(entries, list):
            return documents, errors

        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            document, error = self._extract_uploaded_document(entry, f"{default_name}-{index + 1}")
            if document:
                documents.append(document)
            elif error:
                errors.append(error)
        return documents, errors

    def _extract_uploaded_document(self, entry, default_name):
        name = (entry.get("name") or default_name).strip() or default_name
        encoded_content = entry.get("data_base64") or ""
        if encoded_content:
            try:
                raw_content = base64.b64decode(encoded_content, validate=True)
            except (binascii.Error, ValueError):
                return None, f"{name} could not be decoded."
            content = self._extract_document_bytes(name, raw_content)
            if content:
                return {"name": name, "content": content}, ""
            return None, f"{name} could not be read as a supported document."

        content = (entry.get("content") or "").strip()
        if content:
            suffix = Path(name).suffix.lower()
            if suffix in WORD_EXTENSIONS | EXCEL_EXTENSIONS:
                return None, f"{name} is an Office document, but the upload did not include binary content. Re-add the file and try again."
            return {"name": name, "content": content}, ""

        return None, f"{name} did not contain readable text."

    def _extract_document_bytes(self, name, raw_content):
        suffix = Path(name).suffix.lower()
        if suffix in WORD_EXTENSIONS:
            return self._extract_docx_text(raw_content)
        if suffix in EXCEL_EXTENSIONS:
            return self._extract_xlsx_text(raw_content)
        if suffix in LEGACY_OFFICE_EXTENSIONS:
            return self._extract_legacy_doc_text(raw_content)
        if suffix in SCADE_XML_EXTENSIONS:
            return self._extract_scade_xml_text(name, raw_content)
        if suffix in SCADE_TEXT_EXTENSIONS:
            return self._extract_scade_text(name, raw_content)

        return self._decode_text_bytes(raw_content)

    def _decode_text_bytes(self, raw_content):
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
            try:
                return raw_content.decode(encoding).strip()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return ""

    def _extract_scade_text(self, name, raw_content):
        content = self._decode_text_bytes(raw_content)
        if not content:
            return ""
        suffix = Path(name).suffix.lower().lstrip(".").upper()
        return f"[SCADE {suffix} document: {name}]\n{content}"

    def _extract_scade_xml_text(self, name, raw_content):
        try:
            root = ET.fromstring(raw_content)
        except (ET.ParseError, ValueError):
            content = self._decode_text_bytes(raw_content)
            if not content:
                return ""
            suffix = Path(name).suffix.lower().lstrip(".").upper()
            return f"[SCADE {suffix} document: {name}]\n{content}"

        suffix = Path(name).suffix.lower().lstrip(".").upper()
        lines = [f"[SCADE {suffix} structured model: {name}]"]

        def local_name(value):
            return value.rsplit("}", 1)[-1] if "}" in value else value

        def visit(element, depth=0):
            attributes = []
            for key, value in element.attrib.items():
                normalized = " ".join(str(value).split())
                attributes.append(f"{local_name(key)}={json.dumps(normalized, ensure_ascii=False)}")
            text = " ".join((element.text or "").split())
            details = " " + " ".join(attributes) if attributes else ""
            if text:
                details += f" text={json.dumps(text, ensure_ascii=False)}"
            lines.append(f"{'  ' * depth}{local_name(element.tag)}{details}")
            for child in element:
                visit(child, depth + 1)

        visit(root)
        return "\n".join(lines)

    def _extract_docx_text(self, raw_content):
        xml_names = []
        text_parts = []
        try:
            with zipfile.ZipFile(BytesIO(raw_content)) as archive:
                for name in archive.namelist():
                    if name == "word/document.xml" or re.match(r"word/(header|footer|footnotes|endnotes|comments)\d*\.xml$", name):
                        xml_names.append(name)
                for name in sorted(xml_names):
                    text = self._extract_word_xml_text(archive.read(name))
                    if text:
                        text_parts.append(text)
        except (OSError, zipfile.BadZipFile, KeyError):
            return ""
        return "\n\n".join(text_parts).strip()

    def _extract_word_xml_text(self, xml_content):
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return ""

        parts = []
        for element in root.iter():
            local_name = element.tag.rsplit("}", 1)[-1]
            if local_name == "t" and element.text:
                parts.append(element.text)
            elif local_name == "tab":
                parts.append("\t")
            elif local_name == "lastRenderedPageBreak":
                parts.append("\f")
            elif local_name == "br" and any(key.rsplit("}", 1)[-1] == "type" and value == "page" for key, value in element.attrib.items()):
                parts.append("\f")
            elif local_name in {"br", "cr", "p"}:
                parts.append("\n")

        text = "".join(parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"[ \t]*\f[ \t]*", "\f", text)
        text = re.sub(r"\n*\f\n*", "\f", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_xlsx_text(self, raw_content):
        try:
            with zipfile.ZipFile(BytesIO(raw_content)) as archive:
                shared_strings = self._read_xlsx_shared_strings(archive)
                sheet_names = self._read_xlsx_sheet_names(archive)
                sheet_paths = sorted(
                    name
                    for name in archive.namelist()
                    if re.match(r"xl/worksheets/sheet\d+\.xml$", name)
                )

                sheet_texts = []
                for index, sheet_path in enumerate(sheet_paths, start=1):
                    sheet_name = sheet_names.get(sheet_path) or f"Sheet {index}"
                    sheet_text = self._extract_xlsx_sheet_text(archive.read(sheet_path), shared_strings, sheet_name)
                    if sheet_text:
                        sheet_texts.append(sheet_text)
        except (OSError, zipfile.BadZipFile, KeyError):
            return ""

        return "\n\n".join(sheet_texts).strip()

    def _read_xlsx_shared_strings(self, archive):
        if "xl/sharedStrings.xml" not in archive.namelist():
            return []

        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        except ET.ParseError:
            return []

        strings = []
        for item in root:
            parts = []
            for element in item.iter():
                if element.tag.rsplit("}", 1)[-1] == "t" and element.text:
                    parts.append(element.text)
            strings.append("".join(parts))
        return strings

    def _read_xlsx_sheet_names(self, archive):
        if "xl/workbook.xml" not in archive.namelist():
            return {}

        relationship_targets = {}
        if "xl/_rels/workbook.xml.rels" in archive.namelist():
            try:
                relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                for rel in relationships:
                    rel_id = rel.attrib.get("Id")
                    target = rel.attrib.get("Target", "")
                    if rel_id and target:
                        clean_target = target.lstrip("/")
                        relationship_targets[rel_id] = clean_target if clean_target.startswith("xl/") else f"xl/{clean_target}"
            except ET.ParseError:
                relationship_targets = {}

        sheet_names = {}
        try:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        except ET.ParseError:
            return sheet_names

        for sheet in workbook.iter():
            if sheet.tag.rsplit("}", 1)[-1] != "sheet":
                continue
            name = sheet.attrib.get("name")
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = relationship_targets.get(rel_id or "")
            if name and target:
                sheet_names[target] = name
        return sheet_names

    def _extract_xlsx_sheet_text(self, xml_content, shared_strings, sheet_name):
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return ""

        lines = [f"Worksheet: {sheet_name}"]
        for row in root.iter():
            if row.tag.rsplit("}", 1)[-1] != "row":
                continue
            row_number = row.attrib.get("r") or ""
            values = []
            for cell in row:
                if cell.tag.rsplit("}", 1)[-1] != "c":
                    continue
                cell_ref = cell.attrib.get("r") or ""
                value = self._extract_xlsx_cell_value(cell, shared_strings)
                if value:
                    label = cell_ref or f"row {row_number}"
                    values.append(f"{label}={value}")
            if values:
                row_label = f"Row {row_number}" if row_number else "Row"
                lines.append(f"{row_label}: " + "; ".join(values))

        return "\n".join(lines).strip() if len(lines) > 1 else ""

    def _extract_xlsx_cell_value(self, cell, shared_strings):
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            parts = []
            for element in cell.iter():
                if element.tag.rsplit("}", 1)[-1] == "t" and element.text:
                    parts.append(element.text)
            return "".join(parts).strip()

        raw_value = ""
        for child in cell:
            local_name = child.tag.rsplit("}", 1)[-1]
            if local_name == "v" and child.text is not None:
                raw_value = child.text
                break
            if local_name == "f" and child.text is not None and not raw_value:
                raw_value = f"formula:{child.text}"

        if cell_type == "s" and raw_value:
            try:
                index = int(raw_value)
                return shared_strings[index].strip() if 0 <= index < len(shared_strings) else raw_value.strip()
            except ValueError:
                return raw_value.strip()
        if cell_type == "b":
            return "TRUE" if raw_value == "1" else "FALSE" if raw_value == "0" else raw_value.strip()
        return raw_value.strip()

    def _extract_legacy_doc_text(self, raw_content):
        decoded_candidates = []
        for encoding in ("utf-16-le", "latin-1"):
            try:
                decoded_candidates.append(raw_content.decode(encoding, errors="ignore"))
            except LookupError:
                continue

        best_text = ""
        for decoded in decoded_candidates:
            fragments = re.findall(r"[A-Za-z0-9][\w\s.,;:!?/()'\"%+\-\[\]{}]{20,}", decoded)
            text = "\n".join(fragment.strip() for fragment in fragments if fragment.strip())
            if len(text) > len(best_text):
                best_text = text
        return best_text.strip()

    def _chunk_documents(self, documents, role_label="SOURCE"):
        chunks = []
        for document in documents:
            name = document.get("name") or "document"
            content = (document.get("content") or "").strip()
            if not content:
                continue
            current_section = ""
            explicit_pages = re.split(r"\f+", content)
            paragraph_counter = 0

            for page_content in explicit_pages:
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page_content) if p.strip()]
                if not paragraphs and page_content.strip():
                    paragraphs = [page_content.strip()]

                for paragraph in paragraphs:
                    paragraph_counter += 1
                    if self._looks_like_section_heading(paragraph):
                        current_section = paragraph

                    section_label = current_section or "not resolved"
                    detail_label = self._location_detail_label(paragraph, paragraph_counter)
                    location = f"{role_label}: {name} | section {section_label} | {detail_label}"
                    if len(paragraph) > 1800:
                        sub_paragraphs = re.split(r"(?<=[.;:])\s+", paragraph)
                        for sub_paragraph in sub_paragraphs:
                            if sub_paragraph.strip():
                                chunks.append(f"[{location}] {sub_paragraph.strip()}")
                    else:
                        chunks.append(f"[{location}] {paragraph}")
        return chunks

    def _looks_like_section_heading(self, paragraph):
        text = re.sub(r"\s+", " ", paragraph.strip())
        if not text or len(text) > 120 or "\n" in paragraph.strip():
            return False
        if re.match(r"^Row\s+\d+:", text, re.IGNORECASE):
            return False
        if re.match(r"^(Worksheet|Sheet|Table|Section|Chapter|Appendix|Requirement|Requirements|Verification|Traceability|Scope|Purpose|Introduction|Conclusion|Summary):\s+\S+", text, re.IGNORECASE):
            return True
        if re.match(r"^([0-9]+(\.[0-9]+)*|[A-Z])[\).:\- ]+\S+", text):
            return True
        words = text.split()
        if len(words) <= 8 and not re.search(r"[.;!?]$", text) and any(char.isupper() for char in text):
            return True
        return False

    def _location_detail_label(self, paragraph, paragraph_counter):
        row_match = re.match(r"^Row\s+([A-Za-z0-9_.-]+):", paragraph.strip(), re.IGNORECASE)
        if row_match:
            return f"row {row_match.group(1)}"
        return f"paragraph {paragraph_counter}"

    def _build_complete_target_context(self, target_chunks):
        if not target_chunks:
            return "No target document content was available."
        return "\n\n".join(target_chunks)

    def _resolve_review_context_window(self, body, model_context_limit=None):
        raw_value = body.get("context_window") if isinstance(body, dict) else None
        if raw_value in (None, ""):
            requested_context = max(OLLAMA_REVIEW_MIN_NUM_CTX, min(OLLAMA_REVIEW_MAX_NUM_CTX, OLLAMA_REVIEW_DEFAULT_NUM_CTX))
        else:
            try:
                requested_context = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Context window must be a whole number of tokens.") from exc
            if requested_context < OLLAMA_REVIEW_MIN_NUM_CTX or requested_context > OLLAMA_REVIEW_MAX_NUM_CTX:
                raise ValueError(
                    f"Context window must be between {OLLAMA_REVIEW_MIN_NUM_CTX:,} and {OLLAMA_REVIEW_MAX_NUM_CTX:,} tokens."
                )
        try:
            maximum_context = int(model_context_limit) if model_context_limit not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise ValueError("Model context limit must be a whole number of tokens.") from exc
        if maximum_context and requested_context > maximum_context:
            raise ValueError(
                f"The selected model supports at most {maximum_context:,} context tokens; choose a smaller context window."
            )
        return requested_context

    def _build_review_model_options(self, prompt_length=0, context_window=None):
        requested_context = context_window or self._estimate_review_context_tokens(prompt_length)
        return {
            "temperature": OLLAMA_REVIEW_TEMPERATURE,
            "top_p": OLLAMA_REVIEW_TOP_P,
            "repeat_penalty": OLLAMA_REVIEW_REPEAT_PENALTY,
            "num_ctx": requested_context,
            "num_predict": OLLAMA_REVIEW_NUM_PREDICT,
        }

    def _estimate_review_context_tokens(self, prompt_length):
        prompt_tokens = max(1, int(prompt_length / APPROX_CHARS_PER_TOKEN))
        needed_tokens = prompt_tokens + OLLAMA_REVIEW_NUM_PREDICT + 1024
        rounded_tokens = ((needed_tokens + 2047) // 2048) * 2048
        return max(OLLAMA_REVIEW_MIN_NUM_CTX, min(OLLAMA_REVIEW_MAX_NUM_CTX, rounded_tokens))

    def _retrieve_relevant_chunks(self, chunks, skills_prompt, review_goal, comparison_text="", limit=8):
        query = " ".join([skills_prompt, review_goal, comparison_text])
        scored = self._score_retrieval_chunks(chunks, query)
        ranked = [chunk for _, _, chunk in scored]
        return ranked[:limit] if ranked else chunks[: min(3, limit)]

    def _score_retrieval_chunks(self, chunks, query):
        if not chunks:
            return []
        stop_words = {
            "the", "and", "for", "that", "with", "this", "from", "into", "only", "every", "each",
            "then", "than", "when", "where", "which", "while", "have", "has", "had", "are", "was",
            "were", "will", "would", "should", "could", "document", "documents", "target", "reference",
            "review", "reviewer", "content", "section", "complete", "supplied", "applicable",
        }

        def tokens(value):
            return [
                token.lower()
                for token in re.findall(r"[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*", value or "")
                if len(token) >= 3 and token.lower() not in stop_words
            ]

        query_counts = Counter(tokens(query))
        document_counts = [Counter(tokens(chunk)) for chunk in chunks]
        if not query_counts:
            return [(0.0, index, chunk) for index, chunk in enumerate(chunks)]

        document_frequency = Counter()
        for counts in document_counts:
            document_frequency.update(counts.keys())
        document_total = len(chunks)
        idf = {
            term: math.log((document_total + 1) / (document_frequency.get(term, 0) + 1)) + 1
            for term in query_counts
        }
        query_vector = {term: count * idf[term] for term, count in query_counts.items()}
        query_norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0

        scored = []
        for index, (chunk, counts) in enumerate(zip(chunks, document_counts)):
            dot_product = 0.0
            document_norm_squared = 0.0
            for term, count in counts.items():
                weight = count * idf.get(term, 0.0)
                if weight:
                    document_norm_squared += weight * weight
                    dot_product += weight * query_vector.get(term, 0.0)
            score = dot_product / (query_norm * math.sqrt(document_norm_squared)) if document_norm_squared else 0.0
            if re.search(r"\b(rule|shall|must|required|objective|standard|compliance|criterion|criteria)\b", chunk, re.IGNORECASE):
                score += 0.12
            if re.search(r"\b[A-Z]{2,10}[-_ ]?\d+(?:[.\-_]\d+)*[A-Z]?\b", chunk):
                score += 0.12
            scored.append((score, index, chunk))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored

    def _retrieve_rag_chunks(self, query, limit=24):
        with RAG_LOCK:
            store = {
                "embedding_model": RAG_STORE["embedding_model"],
                "dimensions": RAG_STORE["dimensions"],
                "chunks": [dict(chunk) for chunk in RAG_STORE["chunks"]],
            }
        if not store["chunks"]:
            return []

        formatted = [
            f"[RAG: {chunk['source']} | chunk {chunk['id']}] {chunk['content']}"
            for chunk in store["chunks"]
        ]
        scored = self._score_retrieval_chunks(formatted, query)
        score_by_index = {index: score for score, index, _ in scored}
        has_dense_vectors = any(chunk.get("embedding") for chunk in store["chunks"])
        query_embedding = self._request_rag_query_embedding(
            query, store["embedding_model"], store["dimensions"]
        ) if has_dense_vectors else []
        if query_embedding:
            for index, chunk in enumerate(store["chunks"]):
                embedding = chunk.get("embedding") or []
                if len(embedding) == len(query_embedding):
                    score_by_index[index] = score_by_index.get(index, 0.0) + max(
                        0.0, self._cosine_similarity(query_embedding, embedding)
                    ) * 2.0

        ranked_indices = sorted(range(len(formatted)), key=lambda index: (-score_by_index.get(index, 0.0), index))
        return [formatted[index] for index in ranked_indices[:limit]]

    def _request_rag_query_embedding(self, query, embedding_model, dimensions):
        if not embedding_model or not dimensions:
            return []
        response = self._request_ollama(
            "/api/embed",
            {"model": embedding_model, "input": query[:24000]},
            timeout=OLLAMA_READY_TIMEOUT_SECONDS,
        )
        if not isinstance(response, dict) or response.get("error"):
            return []
        embeddings = response.get("embeddings") or []
        vector = embeddings[0] if embeddings and isinstance(embeddings[0], list) else []
        if len(vector) != dimensions:
            return []
        try:
            normalized = [float(value) for value in vector]
            return normalized if all(math.isfinite(value) for value in normalized) else []
        except (TypeError, ValueError):
            return []

    def _cosine_similarity(self, left, right):
        dot_product = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot_product / (left_norm * right_norm)

    def _interleave_chunks(self, primary, secondary):
        interleaved = []
        for index in range(max(len(primary), len(secondary))):
            if index < len(primary):
                interleaved.append(primary[index])
            if index < len(secondary):
                interleaved.append(secondary[index])
        return interleaved

    def _calculate_retrieval_budget(self, target_characters, instruction_characters, context_window=None):
        effective_context_window = context_window or OLLAMA_REVIEW_DEFAULT_NUM_CTX
        maximum_input_tokens = max(1024, effective_context_window - OLLAMA_REVIEW_NUM_PREDICT - 2048)
        maximum_input_characters = maximum_input_tokens * APPROX_CHARS_PER_TOKEN
        prompt_overhead = instruction_characters + 14000
        return max(4000, maximum_input_characters - target_characters - prompt_overhead)

    def _select_chunks_with_budget(self, chunks, limit, character_budget):
        selected = []
        used_characters = 0
        for chunk in chunks:
            if len(selected) >= limit:
                break
            separator_size = 2 if selected else 0
            if selected and used_characters + separator_size + len(chunk) > character_budget:
                continue
            selected.append(chunk)
            used_characters += separator_size + len(chunk)
        return selected

    def _extract_model_name(self, body):
        if isinstance(body, dict):
            model_name = body.get("model")
            if isinstance(model_name, dict):
                model_name = model_name.get("name") or model_name.get("model")
            elif not isinstance(model_name, str):
                model_name = str(model_name or "")
        else:
            model_name = str(body or "")

        return (model_name or "").strip()

    def _extract_model_names(self, response):
        names = set()
        if not isinstance(response, dict):
            return names

        for model in response.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            name = model.get("name") or model.get("model")
            if name:
                names.add(name)
        return names

    def _load_model(self, model_name, context_window=OLLAMA_REVIEW_DEFAULT_NUM_CTX):
        return self._request_ollama(
            "/api/generate",
            {
                "model": model_name,
                "prompt": "",
                "stream": False,
                "keep_alive": MODEL_KEEP_ALIVE,
                "options": {"num_ctx": context_window},
            },
            timeout=OLLAMA_LOAD_TIMEOUT_SECONDS,
        )

    def _unload_model(self, model_name):
        return self._request_ollama(
            "/api/generate",
            {"model": model_name, "prompt": "", "stream": False, "keep_alive": 0},
            timeout=OLLAMA_STOP_TIMEOUT_SECONDS,
        )

    def _probe_model_response(self, model_name, context_window=OLLAMA_REVIEW_DEFAULT_NUM_CTX):
        start_time = time.time()
        response = self._request_ollama(
            "/api/generate",
            {
                "model": model_name,
                "prompt": "Reply with OK.",
                "stream": False,
                "keep_alive": MODEL_KEEP_ALIVE,
                "options": {"num_ctx": context_window, "num_predict": 3, "temperature": 0},
            },
            timeout=OLLAMA_READY_TIMEOUT_SECONDS,
        )
        elapsed_seconds = round(time.time() - start_time, 2)

        if isinstance(response, dict) and response.get("error"):
            return {
                "ready": False,
                "reason": f"The model is loaded but did not answer the readiness probe within {OLLAMA_READY_TIMEOUT_SECONDS:g}s: {response['error']}",
                "latency_seconds": elapsed_seconds,
            }

        if isinstance(response, dict) and response.get("done"):
            return {
                "ready": True,
                "reason": f"The model answered a short readiness probe in {elapsed_seconds}s.",
                "latency_seconds": elapsed_seconds,
            }

        return {
            "ready": False,
            "reason": "Ollama returned an unexpected readiness response.",
            "latency_seconds": elapsed_seconds,
        }

    def _wait_for_running_state(self, model_name, should_be_running, attempts=6, delay_seconds=0.5):
        for _ in range(attempts):
            response = self._request_ollama("/api/ps")
            running_names = self._extract_model_names(response)
            if (model_name in running_names) == should_be_running:
                return True
            time.sleep(delay_seconds)
        return False

    def _request_ollama(self, path, payload=None, timeout=None):
        url = f"{OLLAMA_BASE_URL}{path}"
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
            with urllib.request.urlopen(request, timeout=timeout or REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return {"error": f"Unable to reach Ollama at {OLLAMA_BASE_URL}: {exc}"}
        except TimeoutError as exc:
            return {"error": f"Timed out reaching Ollama at {OLLAMA_BASE_URL}: {exc}"}
        except Exception as exc:  # pragma: no cover - defensive fallback
            return {"error": str(exc)}

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
