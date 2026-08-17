# ASCS Reviewer

ASCS Reviewer is a local web application for structured review and traceability analysis of safety-critical engineering artefacts. It uses models installed in [Ollama](https://ollama.com/) and sends review content only to the configured Ollama endpoint.

## Requirements

- Python 3.10 or later
- Ollama, with at least one local model installed

The application itself uses only the Python standard library.

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
| `OLLAMA_MODEL_KEEP_ALIVE` | `10m` | Ollama model retention period |

To expose the web application to other machines, explicitly set `ASCS_REVIEWER_HOST=0.0.0.0`. Do this only on a trusted network; the server has no authentication or TLS.

## Test

From this directory:

```sh
python3 -m unittest discover -s tests -v
```

On Windows, use `python` if that is the name of your Python executable.
