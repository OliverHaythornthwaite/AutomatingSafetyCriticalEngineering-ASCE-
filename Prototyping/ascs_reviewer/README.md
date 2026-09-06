# ASCS Reviewer — portable edition

ASCS Reviewer is a dependency-light web application for structured review and
traceability analysis of safety-critical engineering artefacts. The application
uses only Python's standard library and browser-native HTML, CSS, and JavaScript.

The inference service starts from administrator-defined environment variables.
Its endpoint details can then be adjusted from the browser for the lifetime of
the server process; this is configuration rather than a model catalogue or
selection workflow.

## Requirements

- Python 3.10 or later.
- An OpenAI-compatible `/v1/chat/completions` endpoint.
- A modern browser.

No Python packages, JavaScript packages, build tools, or platform-specific desktop
components are required.

## Linux

Configure the inference service and start the application:

```sh
cd Prototyping/ascs_reviewer
export ASCS_MODEL_ENDPOINT="http://127.0.0.1:8001/v1"
export ASCS_MODEL_ID="review-model"
export ASCS_MODEL_API_KEY=""
sh run.sh
```

Open <http://127.0.0.1:8000>. The launcher resolves its own directory, so it works
when called from elsewhere and does not depend on Windows path conventions.

## Windows

```powershell
cd Prototyping\ascs_reviewer
$env:ASCS_MODEL_ENDPOINT = "http://127.0.0.1:8001/v1"
$env:ASCS_MODEL_ID = "review-model"
.\run.ps1
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ASCS_REVIEWER_HOST` | `127.0.0.1` | Web server bind address |
| `ASCS_REVIEWER_PORT` | `8000` | Web server port |
| `ASCS_MODEL_ENDPOINT` | `http://127.0.0.1:8001/v1` | Startup OpenAI-compatible endpoint |
| `ASCS_MODEL_ID` | `review-model` | Startup deployment identifier |
| `ASCS_MODEL_API_KEY` | empty | Optional bearer token, retained only in the server process |
| `ASCS_MODEL_REQUEST_TIMEOUT` | `12` | Health-request timeout in seconds |
| `ASCS_MODEL_REVIEW_TIMEOUT` | `900` | Review-request timeout in seconds |
| `ASCS_MODEL_CONTEXT_LIMIT` | `32768` | Configured context capacity |
| `ASCS_REVIEW_MAX_OUTPUT_TOKENS` | `8192` | Maximum generated review tokens |
| `ASCS_REVIEW_TEMPERATURE` | `0` | Review sampling temperature |
| `ASCS_REVIEW_TOP_P` | `0.9` | Review nucleus-sampling threshold |

The **Inference service** panel can update the endpoint, deployment identifier,
context capacity, timeouts, and API key at runtime. These changes are process-local
and revert to the environment-variable defaults after a server restart. API keys
are never returned by the settings API or stored in browser configuration. Leave
the key field blank to retain the current key, or select the removal option to
clear it.

Use HTTPS whenever the inference endpoint is outside the local machine. Because
the settings API can redirect server requests, expose this application only to
trusted users. To expose the web UI to other machines, set
`ASCS_REVIEWER_HOST=0.0.0.0` only on a trusted network; this application does not
provide TLS or user authentication.

## Capabilities

- Guided JSON review skills and custom review instructions.
- Direct text entry and supported document upload.
- Local TF-IDF indexing of reference documents without an embedding service.
- Deterministic local traceability analysis.
- Structured findings with text and JSON export.

Modern Word, Excel, SCADE, plain-text, markup, and configuration formats are
handled with standard-library parsers. Legacy Office extraction remains
best-effort.

## Review skills

Guided reviews are UTF-8 JSON files in `skills/`. Validate them with:

```sh
python3 skill_store.py skills
```

The supported input types are `text`, `textarea`, `select`, and `multiselect`.
The server strictly validates skill schemas without third-party packages.

## Test

On Linux:

```sh
python3 -m unittest discover -s tests -v
sh -n run.sh
```

On Windows, use `python` in place of `python3`.

See [`MAINTAINABILITY.md`](MAINTAINABILITY.md) for module ownership and portability
constraints.
