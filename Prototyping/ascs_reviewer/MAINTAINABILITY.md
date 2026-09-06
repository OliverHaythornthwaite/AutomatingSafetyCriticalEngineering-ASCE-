# Maintainability and minimal-edition plan

## Current architecture

ASCS Reviewer intentionally has no third-party runtime packages. It uses Python's
standard library for the HTTP server and document processing, and browser-native
HTML, CSS, and JavaScript for the client. External model access is provided by
Ollama or an OpenAI-compatible HTTP endpoint.

The application is split along capability boundaries while its public HTTP API
remains stable:

| Area | Owner | Responsibility |
| --- | --- | --- |
| HTTP entry point | `server.py` | Routes, request/response handling, and composition |
| Runtime configuration | `app_config.py` | Environment settings, static allowlist, and process-local stores |
| Document ingestion | `document_processing.py` | Upload decoding, format extraction, and provenance-aware chunking |
| Model access | `model_providers.py` | Ollama and hosted-provider requests, lifecycle, and benchmarks |
| Retrieval | `retrieval.py` | Reference indexing, scoring, embeddings, and token budgets |
| Traceability | `traceability.py` | Requirement discovery, relationships, and diagnostics |
| Review orchestration | `review_service.py` | Prompt configuration and end-to-end review coordination |
| Result normalization | `review_results.py` | Structured parsing, fallback formatting, and atomic-comment repair |
| Guided review definitions | `skill_store.py` and `skills/` | Skill validation and prompt composition |
| Browser entry point | `app.js` | DOM coordination, feature workflows, and event registration |
| Browser capabilities | `browser/*.js` | Configuration, documents, providers, review normalization, and rendering helpers |

The completed extraction sequence was:

1. `model_providers.py` for Ollama and OpenAI-compatible requests.
2. `traceability.py` for requirement discovery, relationships, and diagnostics.
3. `retrieval.py` for chunk scoring, vector-store state, and token budgeting.
4. `review_results.py` for structured-response parsing and repair.
5. `review_service.py` for orchestration, leaving `server.py` as the transport layer.
6. Native browser modules for configuration, providers, documents, reviews, and rendering.

The handler composes capability mixins so its existing method surface and every
HTTP payload remain compatible. Browser modules are served from an explicit
allowlist and require no bundler or package installation.

## Minimal edition

Develop the reduced edition on branch `variant/minimal-dependencies`, created from
a reviewed commit containing the maintainability boundaries. Do not use a
long-lived copy of the directory on `main`; a branch makes the intentional feature
differences reviewable.

### Product boundary

Retain:

- Python 3.10+ standard-library server and browser-native client.
- A single OpenAI-compatible chat endpoint configured at runtime.
- Guided JSON review skills and custom prompts.
- Plain-text entry and UTF-8 text-file upload.
- Structured review display and JSON/text export.
- Local-only binding by default.

Remove from the minimal branch:

- Ollama installation, model lifecycle, context discovery, and benchmark controls.
- Indexed references, embeddings, RAG, and retrieval settings.
- Traceability analysis.
- Binary Office, legacy Office, and SCADE extraction.
- Features, API routes, styles, and configuration keys used only by those areas.

This leaves no Python package installation step and only one external runtime
dependency: an already-running OpenAI-compatible model endpoint. If local inference
is mandatory, keep Ollama chat access but still remove its lifecycle and benchmark
management; record that choice in the branch README before implementation.

### Branch sequence

1. Finish and commit the behavior-preserving module extractions on `main`.
2. Create the variant with `git switch -c variant/minimal-dependencies`.
3. Add characterization tests for the retained review request and response flow.
4. Remove one excluded capability at a time, including its server route and UI.
5. Replace the README with minimal-edition setup, supported formats, and limitations.
6. Run unit tests and a smoke test against a stub OpenAI-compatible endpoint.
7. Keep shared fixes as small commits that can be cherry-picked between branches;
   do not routinely merge either branch wholesale into the other.

### Acceptance criteria

- Fresh startup requires only `python server.py`; no package manager is used.
- The page loads with no network requests until the user starts a review.
- A text review can be completed and exported using one configured model endpoint.
- Missing or unreachable endpoints produce a clear, bounded error.
- Removed API routes return 404 and removed configuration is not persisted.
- Tests cover startup, skill loading, request validation, provider failure, successful
  review parsing, and export-compatible output.
- Documentation clearly distinguishes the full and minimal editions.

## Change rules

- Keep transport code free of review, retrieval, and parsing algorithms.
- Prefer pure functions for parsing and scoring; keep mutable stores behind a small
  explicit interface.
- Preserve stable API payload fields unless an API version is deliberately raised.
- Add a regression test before changing behavior discovered during extraction.
- Avoid adding a framework merely to reduce file length; module boundaries and
  explicit contracts are the objective.
