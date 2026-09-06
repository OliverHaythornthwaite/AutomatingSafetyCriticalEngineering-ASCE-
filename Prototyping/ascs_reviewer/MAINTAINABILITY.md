# Portable-edition architecture

## Constraints

- Python standard library and browser-native web APIs only.
- Linux and Windows launchers must resolve paths relative to themselves.
- Environment variables supply inference defaults; validated browser changes are
  held only in process memory and must not become a provider catalogue.
- The browser must not offer provider or deployment selection lists.
- Reference retrieval remains local TF-IDF and must not depend on an embedding
  service.
- Static assets are served only through the explicit allowlist in `app_config.py`.

## Module ownership

| Area | Owner |
| --- | --- |
| HTTP transport and route composition | `server.py` |
| Environment configuration and shared state | `app_config.py` |
| Runtime inference settings and endpoint client | `inference_client.py` |
| Document decoding and chunk provenance | `document_processing.py` |
| Local reference retrieval | `retrieval.py` |
| Traceability analysis | `traceability.py` |
| Review orchestration | `review_service.py` |
| Review response normalization | `review_results.py` |
| Skill validation and composition | `skill_store.py` |
| Browser coordination | `app.js` and `browser/` |

## Change rules

- Keep transport code free of review, retrieval, and parsing algorithms.
- Keep credentials out of browser storage and never return them from the server.
- Validate every browser-supplied endpoint setting before changing process state.
- Prefer pure functions for parsing and scoring.
- Preserve stable review and traceability payloads unless the API version changes.
- Add a regression test before changing behavior found during refactoring.
- Do not introduce a framework solely to reduce file length.

## Portability checks

Every release must pass Python compilation, the complete unit suite, JavaScript
syntax checks, `sh -n run.sh`, and a source scan for prohibited legacy backend
references or browser deployment-choice controls.
