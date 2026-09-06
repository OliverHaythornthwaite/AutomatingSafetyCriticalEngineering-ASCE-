"""Client for the single server-configured OpenAI-compatible endpoint."""

import json
import urllib.error
import urllib.parse
import urllib.request

from app_config import (
    API_CAPABILITIES,
    API_VERSION,
    REVIEW_MAX_OUTPUT_TOKENS,
    REVIEW_MAX_CONTEXT,
    REVIEW_MIN_CONTEXT,
    get_inference_settings,
    replace_inference_settings,
)


class InferenceClientMixin:
    """Send health and review requests to the configured inference endpoint."""

    @staticmethod
    def _configured_provider():
        return InferenceClientMixin._validate_inference_settings(get_inference_settings())

    @staticmethod
    def _validate_inference_settings(settings):
        base_url = str(settings.get("base_url") or "").strip().rstrip("/")
        model = str(settings.get("model") or "").strip()
        api_key = settings.get("api_key")
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return {"error": "The endpoint must be an HTTP(S) URL without embedded credentials, a query, or a fragment."}
        if len(base_url) > 2048:
            return {"error": "The endpoint URL must be 2,048 characters or fewer."}
        if not model:
            return {"error": "A deployment identifier is required before reviews can run."}
        if len(model) > 256:
            return {"error": "The deployment identifier must be 256 characters or fewer."}
        if not isinstance(api_key, str) or len(api_key) > 8192:
            return {"error": "The API key must be a string of 8,192 characters or fewer."}
        try:
            context_limit = int(settings.get("context_limit"))
            request_timeout = float(settings.get("request_timeout"))
            review_timeout = float(settings.get("review_timeout"))
        except (TypeError, ValueError):
            return {"error": "Context capacity and timeout values must be numeric."}
        if not REVIEW_MIN_CONTEXT <= context_limit <= REVIEW_MAX_CONTEXT:
            return {
                "error": (
                    f"Context capacity must be between "
                    f"{REVIEW_MIN_CONTEXT:,} and {REVIEW_MAX_CONTEXT:,} tokens."
                )
            }
        if not 0.1 <= request_timeout <= 300:
            return {"error": "Health-request timeout must be between 0.1 and 300 seconds."}
        if not 1 <= review_timeout <= 7200:
            return {"error": "Review-request timeout must be between 1 and 7,200 seconds."}
        return {
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "context_limit": context_limit,
            "request_timeout": request_timeout,
            "review_timeout": review_timeout,
        }

    def _get_inference_settings(self):
        settings = self._configured_provider()
        if settings.get("error"):
            return {"error": settings["error"]}
        return self._public_inference_settings(settings)

    def _update_inference_settings(self, body):
        if not isinstance(body, dict):
            return {"error": "Inference settings must be supplied as a JSON object."}
        current = get_inference_settings()
        api_key = current.get("api_key", "")
        if body.get("clear_api_key") is True:
            api_key = ""
        elif body.get("api_key") not in (None, ""):
            api_key = body["api_key"]
        candidate = {
            "base_url": body.get("endpoint", current.get("base_url")),
            "model": body.get("deployment_id", current.get("model")),
            "api_key": api_key,
            "context_limit": body.get("context_limit", current.get("context_limit")),
            "request_timeout": body.get("request_timeout", current.get("request_timeout")),
            "review_timeout": body.get("review_timeout", current.get("review_timeout")),
        }
        validated = self._validate_inference_settings(candidate)
        if validated.get("error"):
            return validated
        replace_inference_settings(validated)
        return {"ok": True, **self._public_inference_settings(validated)}

    @staticmethod
    def _public_inference_settings(settings):
        return {
            "endpoint": settings["base_url"],
            "deployment_id": settings["model"],
            "context_limit": settings["context_limit"],
            "request_timeout": settings["request_timeout"],
            "review_timeout": settings["review_timeout"],
            "api_key_configured": bool(settings.get("api_key")),
        }

    def _probe_provider(self):
        provider = self._configured_provider()
        if provider.get("error"):
            return {
                "status": "misconfigured",
                "error": provider["error"],
                "api_version": API_VERSION,
                "capabilities": API_CAPABILITIES,
            }
        response = self._request_provider(provider, "/models", timeout=provider["request_timeout"])
        if isinstance(response, dict) and response.get("error"):
            return {
                "status": "offline",
                "endpoint": provider["base_url"],
                "error": response["error"],
                "api_version": API_VERSION,
                "capabilities": API_CAPABILITIES,
            }
        return {
            "status": "online",
            "endpoint": provider["base_url"],
            "context_limit": provider["context_limit"],
            "api_version": API_VERSION,
            "capabilities": API_CAPABILITIES,
        }

    def _request_provider(self, provider, path, payload=None, timeout=None):
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
            with urllib.request.urlopen(request, timeout=timeout or provider["request_timeout"]) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            return {"error": f"Inference endpoint returned HTTP {exc.code}: {detail or exc.reason}"}
        except urllib.error.URLError as exc:
            return {"error": f"Unable to reach inference endpoint at {provider['base_url']}: {exc}"}
        except TimeoutError as exc:
            return {"error": f"Timed out reaching the inference endpoint: {exc}"}
        except Exception as exc:
            return {"error": str(exc)}

    def _request_model_chat(self, provider, request_payload, timeout):
        options = request_payload.get("options") or {}
        payload = {
            "model": provider["model"],
            "messages": request_payload.get("messages") or [],
            "stream": False,
            "temperature": options.get("temperature", 0),
            "top_p": options.get("top_p", 1),
            "max_tokens": options.get("num_predict", REVIEW_MAX_OUTPUT_TOKENS),
            "response_format": {"type": "json_object"},
        }
        response = self._request_provider(provider, "/chat/completions", payload, timeout=timeout)
        error_text = str(response.get("error") or "").lower() if isinstance(response, dict) else ""
        if error_text and any(term in error_text for term in ("response_format", "unsupported", "unrecognized")):
            payload.pop("response_format", None)
            response = self._request_provider(provider, "/chat/completions", payload, timeout=timeout)
        if not isinstance(response, dict) or response.get("error"):
            return response
        choices = response.get("choices") or []
        first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        return {
            "message": {"content": message.get("content") or ""},
            "done": True,
            "done_reason": first_choice.get("finish_reason") or "unknown",
            "prompt_eval_count": usage.get("prompt_tokens"),
            "eval_count": usage.get("completion_tokens"),
        }

    @staticmethod
    def _extract_context_limit(metadata):
        if not isinstance(metadata, dict):
            return None
        candidates = []
        recognized = {"context_length", "context_window", "max_context_length", "max_model_len", "max_position_embeddings"}
        for raw_key, raw_value in metadata.items():
            key = str(raw_key).strip().lower()
            if isinstance(raw_value, dict):
                nested = InferenceClientMixin._extract_context_limit(raw_value)
                if nested:
                    candidates.append(nested)
            elif key in recognized or key.endswith(".context_length"):
                try:
                    value = int(raw_value)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    candidates.append(value)
        return max(candidates) if candidates else None

    @staticmethod
    def _diagnose_prompt_failure(error_message, model, prompt_length, source_count):
        lowered = str(error_message).lower()
        if "timed out" in lowered or "timeout" in lowered:
            return "The review request timed out. Increase ASCS_MODEL_REVIEW_TIMEOUT or reduce the review input."
        if "connect" in lowered or "refused" in lowered or "unreachable" in lowered:
            return "ASCS Reviewer could not reach the configured inference endpoint."
        if "not found" in lowered or "404" in lowered:
            return "The configured inference service or deployment was not found. Check the inference service settings."
        return f"The review request failed: {error_message}"
