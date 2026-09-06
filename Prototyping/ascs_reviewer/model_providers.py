"""Ollama and OpenAI-compatible model-provider behavior."""

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from app_config import (
    API_CAPABILITIES,
    API_VERSION,
    BENCHMARK_CONTROL_IDS,
    BENCHMARK_EXPECTED_FINDINGS,
    BENCHMARK_VERSION,
    MODEL_CONTEXT_CACHE,
    MODEL_CONTEXT_CACHE_LOCK,
    MODEL_KEEP_ALIVE,
    OLLAMA_BASE_URL,
    OLLAMA_BENCHMARK_TIMEOUT_SECONDS,
    OLLAMA_LOAD_TIMEOUT_SECONDS,
    OLLAMA_READY_TIMEOUT_SECONDS,
    OLLAMA_REVIEW_DEFAULT_NUM_CTX,
    OLLAMA_REVIEW_MIN_NUM_CTX,
    OLLAMA_REVIEW_NUM_PREDICT,
    OLLAMA_STOP_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
)


class ModelProviderMixin:
    """Provide model discovery, lifecycle, benchmark, and HTTP adapters."""

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
        reasoning_effort = ollama_payload.get("reasoning_effort")
        if provider["mode"] == "ollama":
            native_payload = dict(ollama_payload)
            native_payload.pop("reasoning_effort", None)
            if reasoning_effort:
                native_payload["think"] = False if reasoning_effort == "none" else reasoning_effort
            response = self._request_ollama("/api/chat", native_payload, timeout=timeout)
            if reasoning_effort and self._reasoning_control_rejected(response):
                fallback_payload = dict(native_payload)
                fallback_payload.pop("think", None)
                response = self._request_ollama("/api/chat", fallback_payload, timeout=timeout)
            return response

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
        if reasoning_effort:
            hosted_payload["reasoning_effort"] = reasoning_effort
        response = self._request_hosted_server(provider, "/chat/completions", hosted_payload, timeout=timeout)
        error_text = str(response.get("error") or "").lower() if isinstance(response, dict) else ""
        if error_text and any(term in error_text for term in ("response_format", "seed", "reasoning", "unsupported", "unrecognized")):
            hosted_payload.pop("response_format", None)
            hosted_payload.pop("seed", None)
            hosted_payload.pop("reasoning_effort", None)
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

    @staticmethod
    def _reasoning_control_rejected(response):
        if not isinstance(response, dict) or not response.get("error"):
            return False
        error_text = str(response["error"]).lower()
        return any(term in error_text for term in ("think", "reasoning", "unsupported", "unrecognized", "unknown field"))

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
