# ASCS Reviewer

ASCS Reviewer is a local web application for structured review and traceability analysis of safety-critical engineering artefacts. Reviews can use models installed in [Ollama](https://ollama.com/) or an OpenAI-compatible model hosting server.

## Requirements

- Python 3.10 or later
- Ollama with at least one local model installed, or access to an OpenAI-compatible model server

The application itself uses only the Python standard library.

The codebase architecture and the separate minimal-edition branch strategy are
documented in [`MAINTAINABILITY.md`](MAINTAINABILITY.md).

## Run on Windows

```powershell
cd Prototyping\ascs_reviewer
.\run.ps1
```

## Run on Linux

```sh
cd Prototyping/ascs_reviewer
sh run.sh
```

Open <http://127.0.0.1:8000>, select an installed model, and start it before running a review.

## Review skills

Guided reviews are defined by portable, UTF-8 JSON files in `skills/`. Each file contains:

- Stable `schema_version` and `id` values.
- A human-readable name and description.
- The reviewer role, objective, fixed instructions, and ordered `review_sections` used to build the complete model prompt.
- The `inputs` array that tells the UI which questions to render.
- A `prompt_template` for converting each answer into a model instruction.

The supported input types are `text`, `textarea`, `select`, and `multiselect`. Selection options keep separate UI labels and model-facing `prompt_value` text.

Each `review_sections` entry contains a section `title` and its review `instruction`. The server turns these entries into the required JSON output contract, so a skill can change the review structure without changing Python code while the response remains reliably parseable. Every section is mandatory: the reviewer must execute each applicable check with equal diligence and record either findings, a clear pass, or a justified not-applicable result.

`skills/skill.schema.json` provides JSON Schema support for compatible editors. The server also performs strict validation without third-party packages and refuses unknown fields, invalid defaults, unsupported controls, and duplicate identifiers.

To produce a skill:

1. Copy the closest existing JSON skill and give it a unique lowercase hyphenated `id`.
2. Edit its concise prompt and UI input definitions.
3. Validate the complete skill directory:

   ```sh
   python3 skill_store.py skills
   ```

4. Restart ASCS Reviewer. The new skill will appear automatically in guided mode.

Custom mode does not require a skill file. It always applies a complete safety-critical baseline checklist and accepts separate reviewer-role, objective, review-method, and additional-check fields. Additional checks extend the baseline; they cannot narrow or replace it.

## Supported documents

The reviewer extracts modern Word (`.docx`, `.docm`, `.dotx`, `.dotm`) and Excel (`.xlsx`, `.xlsm`, `.xltx`, `.xltm`) content, with best-effort support for legacy `.doc` and `.xls` files. Plain-text and text-based data formats can also be reviewed directly.

SCADE support includes:

- Suite source and project files: `.scade`, `.xscade`, and `.etp`.
- Display and graphical resources: `.sgfx`, `.pgfx`, `.ogfx`, `.dgfx`, `.sdfx`, and `.rgfx`.
- Simulation and analysis text: `.sss`, `.in`, `.sns`, `.out`, and `.obs`.

XML-based SCADE resources are flattened into an indented representation that preserves element hierarchy, attributes, and text. Text-based SCADE files retain their complete decoded content with a format and filename label.

## Model providers

Section 3 starts in **Local Ollama** mode. Select **Switch to hosted server** to configure an OpenAI-compatible endpoint such as vLLM, LM Studio, llama.cpp, or a managed service. Supply its base URL (normally ending in `/v1`), exact model identifier, and an optional bearer API key. **Check hosted server** queries `/models`; reviews and benchmarks use `/chat/completions`.

The hosted URL and model identifier can be saved with the review setup. API keys are held only in the page for the current browser session and are never written to local storage. Use HTTPS whenever the model server is not on the same computer. Retrieval remains local: dense RAG queries use the configured Ollama embedding model when available and otherwise fall back to TF-IDF.

The **Review context window** setting applies consistently to review retrieval and benchmarks. It offers 8K, 16K, 32K, 64K, and 128K, plus the model's exact maximum when it falls between those values, preferring 32K where supported. For Ollama, the reviewer reads the architecture context limit from `/api/show` and disables oversized choices. Ollama receives the valid selection as `num_ctx`; larger values require correspondingly more memory. For hosted providers, **Check hosted server** uses context metadata from `/models` when available. If the hosting API does not publish it, enter the server-configured maximum manually before reviewing. Oversized choices are then disabled in the same way.

The **Reasoning effort** setting defaults to **Low** and also offers provider
default, disabled, medium, high, and extra high. Native Ollama requests receive
the corresponding `think` value (`false` when disabled); hosted OpenAI-compatible
requests receive `reasoning_effort`. Extra high is intended for models such as
Muse Glimmer that explicitly support it. If a model or provider rejects the
control, the reviewer retries once without it.

## Indexed reference documents (RAG)

The reference list and retrieval index are one workflow: every reference file added through the UI is immediately chunked into the temporary local TF-IDF vector index. Each reference shows its chunk count, estimated total tokens, and estimated tokens per chunk. Removing a reference removes only that document's associated chunks; **Clear all** removes every indexed reference and chunk. Before either a local or hosted review, a section-aware relevance step-through scans the artefact chunks, selects representative target sections, and uses those focused searches to rank reference evidence. This prevents an oversized whole-document query from allowing one section to dominate retrieval while the complete target remains available to the final reviewer. The focused, broad, and maximum settings select up to 12, 24, or 40 relevant chunks respectively.

Portable stores use this structure:

```json
{
  "name": "Project assurance knowledge",
  "embedding_model": "project-embedding-model",
  "dimensions": 3,
  "chunks": [
    {
      "id": "standard-4.2",
      "source": "software-standard.md",
      "content": "The governing rule or evidence text.",
      "embedding": [0.01, -0.02, 0.03]
    }
  ]
}
```

`embedding` is optional. Stores without embeddings and documents indexed through the UI use local TF-IDF cosine ranking. When embeddings, dimensions, and an `embedding_model` are present, the server asks the local Ollama embedding model for the query vector and combines dense cosine similarity with TF-IDF ranking. If embedding generation is unavailable, retrieval falls back to TF-IDF rather than blocking the review. Displayed token counts are model-neutral estimates; exact counts vary with the selected model's tokenizer. Loaded knowledge remains in memory and is cleared when the server stops or when **Clear all** is selected.

## Repeatable model benchmark

Each installed Ollama model has a **Test** action, and hosted mode provides **Test hosted model**. Benchmark version 1.0 reviews the same six simulated low-level requirements against four explicit benchmark rules. Four requirements contain one seeded defect each; two are clean controls. Local models are warmed up before timing; every provider receives deterministic generation settings where supported: temperature `0`, seed `42`, and a JSON response contract.

The quality score is independent of machine speed:

- 85% comes from the F1 score for exact requirement/rule finding pairs.
- 15% comes from correctly passing the two clean controls without findings.
- Missed seeded defects reduce recall; invented or misattributed findings reduce precision.

The UI reports score, precision, recall, clean-control accuracy, warm-up time, and measured review time. Timing is shown separately and does not alter the quality score. Results remain in the browser for the current page session.

## Traceability analysis

Traceability analysis runs locally and deterministically; it does not require a model. It extracts requirement definitions from the supplied artefacts and analyses explicit requirement-ID references across the supported lifecycle order: `SRATS`, `SR`, `HLR`, `LLR`, and `LLRV`.

The analysis reports:

- Overall and per-lifecycle-level link coverage.
- Complete, partial, unlinked, and duplicate requirement status.
- Missing upstream and downstream links where the corresponding lifecycle levels are present.
- Unresolved and ambiguous references, duplicate definitions, and cross-level links.
- A forward/reverse relationship view and a compact traceability matrix.
- Downloadable JSON containing the full analysis for audit evidence or downstream processing.

Requirement definitions should begin with their ID (for example, `HLR-001 ...`) or an explicit label such as `Requirement ID: HLR-001`. Other mentions of the ID are treated as references rather than additional definitions. IDs may contain hyphens, underscores, or spaces; the analyser normalises them for matching.

## Configuration

Configuration is supplied through environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ASCS_REVIEWER_HOST` | `127.0.0.1` | Web server bind address |
| `ASCS_REVIEWER_PORT` | `8000` | Web server port |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `OLLAMA_REQUEST_TIMEOUT` | `12` | General API timeout in seconds |
| `OLLAMA_LOAD_TIMEOUT` | `120` | Model loading timeout in seconds |
| `OLLAMA_READY_TIMEOUT` | `45` | Model readiness timeout in seconds |
| `OLLAMA_REVIEW_TIMEOUT` | `900` | Review timeout in seconds |
| `OLLAMA_BENCHMARK_TIMEOUT` | `180` | Repeatable model benchmark timeout in seconds |
| `OLLAMA_MODEL_KEEP_ALIVE` | `10m` | Ollama model retention period |
| `OLLAMA_REVIEW_MIN_NUM_CTX` | `8192` | Minimum accepted review context window |
| `OLLAMA_REVIEW_DEFAULT_NUM_CTX` | `32768` | Default context for API clients that omit the UI setting |
| `OLLAMA_REVIEW_MAX_NUM_CTX` | `131072` | Maximum selectable review context window |
| `OLLAMA_REVIEW_NUM_PREDICT` | `8192` | Maximum generated review tokens |

To expose the web application to other machines, explicitly set `ASCS_REVIEWER_HOST=0.0.0.0`. Do this only on a trusted network; the server has no authentication or TLS.

## Test

From this directory:

```sh
python3 -m unittest discover -s tests -v
```

On Windows, use `python` if that is the name of your Python executable.
