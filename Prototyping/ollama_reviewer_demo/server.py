import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_REQUEST_TIMEOUT", "12"))


class OllamaDemoHandler(BaseHTTPRequestHandler):
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

        self._serve_file(ROOT / path.lstrip("/"), not_found=True)

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

        if path.startswith("/api/models/start"):
            body = self._read_json_body()
            self._send_json(self._start_model(body))
            return

        if path.startswith("/api/models/stop"):
            body = self._read_json_body()
            self._send_json(self._stop_model(body))
            return

        self._send_json({"error": "Not found"}, status=404)

    def _probe_ollama(self):
        response = self._request_ollama("/api/tags")
        if isinstance(response, dict) and response.get("error"):
            return {"status": "offline", "ollama_base_url": OLLAMA_BASE_URL, "error": response["error"]}
        return {"status": "online", "ollama_base_url": OLLAMA_BASE_URL, "model_count": len(response.get("models", []) or [])}

    def _start_model(self, body):
        model_name = self._extract_model_name(body)
        if not model_name:
            return {"error": "Please provide a model name."}

        response = self._request_ollama("/api/ps")
        if isinstance(response, dict) and response.get("error"):
            return {"error": response["error"], "model": model_name}

        running_names = self._extract_model_names(response)
        if model_name in running_names:
            return {"ok": True, "model": model_name, "status": "already-running", "note": "The model is already running."}

        warmup_response = self._request_ollama("/api/generate", {"model": model_name, "prompt": "ping", "stream": False})
        if isinstance(warmup_response, dict) and warmup_response.get("error"):
            return {"ok": False, "model": model_name, "status": "start-failed", "error": warmup_response["error"]}

        refreshed_response = self._request_ollama("/api/ps")
        if isinstance(refreshed_response, dict) and refreshed_response.get("error"):
            return {"ok": False, "model": model_name, "status": "start-failed", "error": refreshed_response["error"]}

        refreshed_names = self._extract_model_names(refreshed_response)
        if model_name in refreshed_names:
            return {"ok": True, "model": model_name, "status": "running", "note": "The model is now running and should appear in the list shortly."}

        return {"ok": True, "model": model_name, "status": "pending", "note": "Ollama is still loading the model. The portal will keep checking until the running state appears."}

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

        return {"ok": True, "model": model_name, "status": "stopped", "note": "The model has been requested to stop. Refresh the model list shortly."}

    def _get_model_status(self):
        installed_response = self._request_ollama("/api/tags")
        running_response = self._request_ollama("/api/ps")

        installed_models = []
        if isinstance(installed_response, dict):
            installed_models = installed_response.get("models", []) or []

        running_names = self._extract_model_names(running_response)

        result = []
        for model in installed_models:
            name = model.get("name") or model.get("model") or "unknown"
            details = model.get("details") or {}
            result.append(
                {
                    "name": name,
                    "status": "online" if name in running_names else "offline",
                    "size": model.get("size"),
                    "modified_at": model.get("modified_at"),
                    "digest": model.get("digest"),
                    "family": details.get("family"),
                }
            )

        if not result and isinstance(running_response, dict):
            for model in running_response.get("models", []) or []:
                name = model.get("name") or model.get("model") or "unknown"
                result.append({"name": name, "status": "online"})

        return {"models": result}

    def _build_reviewer_response(self, body):
        if not isinstance(body, dict):
            return {"error": "The review request was not received as valid JSON. Please try again from the portal."}

        skills_prompt = (body.get("skills_prompt") or "").strip()
        review_goal = (body.get("review_goal") or "Review the documentation for clarity, risks, and missing controls.").strip()
        document_text = (body.get("document_text") or "").strip()
        model = (body.get("model") or "llama3.2").strip()
        documents = body.get("documents") or []
        d0178c_context = (body.get("d0178c_context") or "").strip()
        reference_locations = body.get("reference_locations") or []

        if documents:
            source_documents = []
            for entry in documents:
                if isinstance(entry, dict):
                    content = (entry.get("content") or "").strip()
                    if content:
                        source_documents.append({"name": entry.get("name") or "document", "content": content})
            if not source_documents:
                return {"error": "No readable document content was provided."}
        elif document_text:
            source_documents = [{"name": "pasted-document", "content": document_text}]
        else:
            return {"error": "Please provide documentation text or files to review."}

        reference_documents = self._collect_reference_documents(d0178c_context, reference_locations)
        if reference_documents:
            source_documents.extend(reference_documents)

        readiness = self._check_model_readiness(model)
        if not readiness["ready"]:
            return {
                "error": readiness["reason"],
                "review": "",
                "retrieved_chunks": [],
                "model": model,
                "source_count": len(source_documents),
            }

        chunks = self._chunk_documents(source_documents)
        retrieved = self._retrieve_relevant_chunks(chunks, skills_prompt, review_goal)
        context_text = "\n\n".join(retrieved[:6]) if retrieved else "No additional context available."

        prompt_length = len(skills_prompt) + len(review_goal) + len(context_text) + len(document_text) + len(d0178c_context)
        user_prompt = self._build_review_prompt(skills_prompt, review_goal, context_text, d0178c_context, document_text)

        ollama_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an experienced engineering reviewer. Be precise, practical, evidence-based, and apply common-sense engineering judgment to the full artefact and its context.",
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "stream": False,
            "format": "json",
        }

        response = self._request_ollama("/api/chat", ollama_payload)
        if isinstance(response, dict) and response.get("error"):
            diagnostic_reason = self._diagnose_prompt_failure(response["error"], model, prompt_length, len(source_documents))
            return {
                "error": diagnostic_reason,
                "review": "",
                "retrieved_chunks": retrieved[:6],
                "model": model,
                "source_count": len(source_documents),
            }

        review_text = response.get("message", {}).get("content", "") if isinstance(response, dict) else ""
        review_result = self._parse_review_result(review_text)
        return {
            "review": review_result.get("summary") or review_text.strip(),
            "review_result": review_result,
            "retrieved_chunks": retrieved[:6],
            "model": model,
            "source_count": len(source_documents),
        }

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
            return {"ready": False, "reason": f"The selected model {model} is installed but not currently running. Start it from the portal or wait a moment for Ollama to load it before reviewing."}

        return {"ready": True, "reason": ""}

    def _build_review_prompt(self, skills_prompt, review_goal, context_text, d0178c_context, document_text):
        return (
            "You are reviewing the full artefact for a safety-critical engineering workflow, not just the literal text in the documentation. "
            "Apply practical engineering judgment and common sense. Review the content for completeness, consistency, clarity, risks, omissions, and suitability for use. "
            "Always include a visual check, a spelling and grammar check (not overly pedantic), a process review, and a traceability review if relevant. "
            "If a review area is not applicable, say so briefly rather than inventing an answer.\n\n"
            f"Skills prompt:\n{skills_prompt or 'Review for clarity, traceability, hazards, and omissions.'}\n\n"
            f"Review goal:\n{review_goal}\n\n"
            f"DO-178C and reference standards context:\n{d0178c_context or 'No additional DO-178C context was provided.'}\n\n"
            f"Retrieved context:\n{context_text}\n\n"
            f"Primary document text:\n{document_text or 'No primary document text was provided.'}\n\n"
            "Return a JSON object with the following shape and no extra commentary:\n"
            "{\n"
            "  \"summary\": \"Short overall assessment\",\n"
            "  \"sections\": [\n"
            "    {\"title\": \"Visual review\", \"content\": \"...\"},\n"
            "    {\"title\": \"Spelling and grammar\", \"content\": \"...\"},\n"
            "    {\"title\": \"Process review\", \"content\": \"...\"},\n"
            "    {\"title\": \"Traceability review\", \"content\": \"...\"},\n"
            "    {\"title\": \"Additional observations\", \"content\": \"...\"}\n"
            "  ],\n"
            "  \"atomic_comments\": [\n"
            "    {\"id\": \"A1\", \"issue\": \"Short issue description\", \"comment\": \"Atomic comment to resolve the issue\", \"suggested_resolution\": \"How to fix it\"}\n"
            "  ]\n"
            "}"
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

        return {
            "summary": parsed.get("summary") or "Review completed.",
            "sections": [
                {
                    "title": section.get("title") or "Review",
                    "content": section.get("content") or "",
                }
                for section in sections
                if isinstance(section, dict)
            ],
            "atomic_comments": [
                {
                    "id": comment.get("id") or f"A{index + 1}",
                    "issue": comment.get("issue") or "Issue",
                    "comment": comment.get("comment") or "",
                    "suggested_resolution": comment.get("suggested_resolution") or "",
                }
                for index, comment in enumerate(atomic_comments)
                if isinstance(comment, dict)
            ],
        }

    def _diagnose_prompt_failure(self, error_message, model, prompt_length, source_count):
        lowered = error_message.lower()
        if "timed out" in lowered or "timeout" in lowered:
            if prompt_length > 22000:
                return f"The prompt likely exceeded the response budget. The documentation is large ({source_count} source chunk(s)); try a shorter excerpt or a smaller model."
            return f"The prompt timed out while Ollama was generating a response for {model}. The model may still be loading, or the request may be too heavy for the current setup."
        if "unable to reach" in lowered or "connection" in lowered:
            return f"The portal could not reach Ollama at {OLLAMA_BASE_URL}. Check the Ollama service and ensure it is listening on the expected port."
        if "not found" in lowered:
            return f"The selected model {model} was not found locally. Pull it first with: ollama pull {model}."
        return f"The review request failed: {error_message}"

    def _collect_reference_documents(self, d0178c_context, reference_locations):
        documents = []
        if d0178c_context.strip():
            documents.append({"name": "DO-178C-context", "content": d0178c_context.strip()})

        if isinstance(reference_locations, str):
            locations = [reference_locations]
        else:
            locations = [item for item in (reference_locations or []) if isinstance(item, str)]

        for raw_location in locations:
            location = raw_location.strip()
            if not location:
                continue
            path = Path(location).expanduser()
            if not path.exists():
                continue

            candidates = [path] if path.is_file() else sorted([item for item in path.rglob("*") if item.is_file()]) if path.is_dir() else []
            for candidate in candidates:
                if not self._is_supported_text_path(candidate):
                    continue
                content = self._read_text_file(candidate)
                if content:
                    documents.append({"name": str(candidate), "content": content})

        return documents

    def _is_supported_text_path(self, path):
        suffix = path.suffix.lower()
        return suffix in {".txt", ".md", ".rtf", ".json", ".csv", ".log", ".yaml", ".yml", ".xml", ".html", ".htm", ".toml", ".ini", ".cfg", ".conf", ".py", ".c", ".h", ".cpp", ".hpp", ".js", ".ts", ".java", ".cs", ".sql", ".rst", ".txt"} or suffix == ""

    def _read_text_file(self, path):
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            except OSError:
                return ""
        return ""

    def _chunk_documents(self, documents):
        chunks = []
        for document in documents:
            name = document.get("name") or "document"
            content = (document.get("content") or "").strip()
            if not content:
                continue
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
            if not paragraphs:
                paragraphs = [content]
            for paragraph in paragraphs:
                if len(paragraph) > 1800:
                    sub_paragraphs = re.split(r"(?<=[.;:])\s+", paragraph)
                    for sub_paragraph in sub_paragraphs:
                        if sub_paragraph.strip():
                            chunks.append(f"[{name}] {sub_paragraph.strip()}")
                else:
                    chunks.append(f"[{name}] {paragraph}")
        return chunks

    def _retrieve_relevant_chunks(self, chunks, skills_prompt, review_goal):
        query = " ".join([skills_prompt, review_goal]).lower()
        query_terms = set(re.findall(r"[a-zA-Z0-9_]+", query))
        scored = []
        for chunk in chunks:
            chunk_lower = chunk.lower()
            score = 0
            for term in query_terms:
                if len(term) < 3:
                    continue
                score += chunk_lower.count(term)
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        ranked = [chunk for _, chunk in scored if chunk]
        return ranked[:6] if ranked else chunks[:3]

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

    def _request_ollama(self, path, payload=None):
        url = f"{OLLAMA_BASE_URL}{path}"
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
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
    server = ThreadingHTTPServer(("127.0.0.1", 8000), OllamaDemoHandler)
    print("Ollama reviewer demo running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
