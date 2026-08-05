import base64
import binascii
from io import BytesIO
import json
import os
import re
import time
import urllib.request
import urllib.error
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_REQUEST_TIMEOUT", "12"))
OLLAMA_LOAD_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_LOAD_TIMEOUT", "120"))
OLLAMA_READY_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_READY_TIMEOUT", "45"))
OLLAMA_REVIEW_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_REVIEW_TIMEOUT", "900"))
OLLAMA_STOP_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_STOP_TIMEOUT", "30"))
MODEL_KEEP_ALIVE = os.environ.get("OLLAMA_MODEL_KEEP_ALIVE", "10m")
OLLAMA_REVIEW_MIN_NUM_CTX = int(os.environ.get("OLLAMA_REVIEW_MIN_NUM_CTX", "8192"))
OLLAMA_REVIEW_MAX_NUM_CTX = int(os.environ.get("OLLAMA_REVIEW_MAX_NUM_CTX", "32768"))
OLLAMA_REVIEW_NUM_PREDICT = int(os.environ.get("OLLAMA_REVIEW_NUM_PREDICT", "8192"))
OLLAMA_REVIEW_TEMPERATURE = float(os.environ.get("OLLAMA_REVIEW_TEMPERATURE", "0"))
OLLAMA_REVIEW_TOP_P = float(os.environ.get("OLLAMA_REVIEW_TOP_P", "0.9"))
OLLAMA_REVIEW_REPEAT_PENALTY = float(os.environ.get("OLLAMA_REVIEW_REPEAT_PENALTY", "1.05"))
APPROX_CHARS_PER_TOKEN = 4
WORD_EXTENSIONS = {".docx", ".docm", ".dotx", ".dotm"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls"}
TEXT_SOURCE_EXTENSIONS = {
    ".txt", ".md", ".rtf", ".json", ".csv", ".tsv", ".log", ".yaml", ".yml", ".xml", ".html", ".htm",
    ".toml", ".ini", ".cfg", ".conf", ".rst", ".py", ".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".cxx",
    ".hxx", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".sql", ".sh", ".bat", ".ps1", ".m", ".mm",
    ".s", ".asm",
}
ARTEFACT_ORDER = {"SRATS": 0, "SR": 0, "HLR": 1, "LLR": 2, "LLRV": 3}
DEMO_MODEL_NAME = "ChatGPT 5.6 SOL"
DEMO_REVIEW_FINDINGS = [
    {
        "section": "Critical findings",
        "id": "C-01",
        "issue": "Command guards are bypassed.",
        "evidence": "LLR-C2-001 excludes link, authority and vehicle mode; LLR-C2-010 permits transmission with lost link; LLR-C2-013 calls transport directly. Model lines 61-63/85 and C lines 81-83 transmit without the required guards.",
        "rules": "SDS-C2-001, SDS-HMI-004, SDS-PRN-002/003, SIS-IMP-003",
        "fix": "Align HLR/LLR command-guard requirements to SRAT-C2-002 and SRAT-C2-004: commands shall be inhibited when authority is invalid and transmission shall be prevented when link is lost. Remove the SRATS/HLR permissive exception wording unless it is approved as a separate derived safety requirement, then add HLR/LLR negative verification cases for invalid authority, lost link, invalid mode, invalid command kind and invalid parameters.",
    },
    {
        "section": "Critical findings",
        "id": "C-02",
        "issue": "One confirmation can cause multiple transmissions.",
        "evidence": "C line 53 sends during confirmation, then lines 95-99 send again in the same step. It continues sending every cycle while S_SENT. The model has equivalent level-sensitive behaviour at line 63.",
        "rules": "SDS-C2-002, SMS-STM-005",
        "fix": "Align HLR/LLR confirmation behaviour to SRAT-C2-006, whose acceptance criterion records one confirmation action. State that one valid confirmation produces at most one send request; a held confirmation control shall not cause repeated transmission. If retries are required, add a distinct SRATS/HLR requirement with bounded retry conditions and verification.",
    },
    {
        "section": "Critical findings",
        "id": "C-03",
        "issue": "Acknowledgements are not correlated to the pending transaction.",
        "evidence": "ack_id is unused in model lines 70-71 and discarded in C lines 58-65. Any positive acknowledgement produces ACCEPTED.",
        "rules": "SDS-C2-003, SDS-PRN-006",
        "fix": "Refine SRAT-C2-003 and SRAT-C2-008 through the HLR/LLR so accepted/rejected status is based on an acknowledgement whose transaction identifier matches the pending command. Update SRAT-C2-008 acceptance criteria beyond 'identifier is numeric' to require correlation, then add HLR/LLR cases for stale, missing, malformed and wrong-ID acknowledgements.",
    },
    {
        "section": "Critical findings",
        "id": "C-04",
        "issue": "Warm restore can immediately transmit an invalid command.",
        "evidence": "LLR-C2-007, model lines 43-53 and C lines 29-33 restore S_SENT. On the first step, C lines 95-99 send an empty command with transaction ID zero.",
        "rules": "SIS-IMP-004, SMS-STM-002, SMS-TIM-004, SDS-PRN-005",
        "fix": "Keep the HLR/LLR restart behaviour aligned with SRAT-C2-005: restore only the pending command selection so the operator can continue without re-entry; do not restore or resume transmission. Add HLR/LLR wording that after restart a fresh valid confirmation and guard check are required before any send request.",
    },
    {
        "section": "Critical findings",
        "id": "C-05",
        "issue": "Transaction ID lifecycle is invalid.",
        "evidence": "Zero is emitted for a new command and the ID increments only after acceptance. Multiple commands can consequently use the same ID.",
        "rules": "SIS T_CommandId, SIS-DAT-003, SDS-C2-002",
        "fix": "Clarify SRAT-C2-008 in the HLR/LLR: zero may be represented only as the startup/no-command identifier and shall not be emitted for a transmitted command. Require each transmitted command to carry a unique non-zero pending transaction identifier, with first-use, rejection, timeout and wraparound behaviour defined and verified.",
    },
    {
        "section": "Critical findings",
        "id": "C-06",
        "issue": "Unknown or corrupt values produce unsafe valid behaviour.",
        "evidence": "LLR-C2-012 converts an unknown command to RETURN_HOME, while model line 51 and C lines 111-114 convert an invalid state to ACCEPTED/GREEN.",
        "rules": "SMS-DF-005, SMS-STM-004, SDS-PRN-005/006",
        "fix": "Add HLR/LLR invalid-data behaviour that supports SRAT-C2-002, SRAT-C2-004 and SRAT-C2-003 failure conditions: unknown or corrupt command/state values shall inhibit transmission, prevent accepted status, and produce a defined operator-visible rejected/error indication. Do not map unknown values to valid commands or accepted states.",
    },
    {
        "section": "Critical findings",
        "id": "C-07",
        "issue": "Memory and pointer safety rules are violated.",
        "evidence": "C line 42 uses unbounded strcpy; line 50 allocates heap memory after initialization; line 51 dereferences it without checking allocation success. Input/output pointers are also dereferenced without validation. Static analysis reports a possible-null dereference at line 51.",
        "rules": "SIS-IMP-006, SIS-C-002, SIS-C-003",
        "fix": "Do not add C-pointer mechanics to the HLR. Instead, add HLR/LLR allocation text tying the PAN-C2 cyclic command path to DAL B deterministic behaviour in the SRATS header, then allocate detailed memory, bounded string and null-interface constraints to LLR/SIS verification while preserving trace to the affected SRATS failure conditions.",
    },
    {
        "section": "Critical findings",
        "id": "C-08",
        "issue": "A production test bypass is executable.",
        "evidence": "debug_force_send is part of the production operator and C step, with a production display button bound to it. It bypasses all command guards.",
        "rules": "SMS-CLS-001/002, SDS-HMI-004, SIS-GEN-006",
        "fix": "Add an HLR/LLR constraint aligned to SRAT-C2-002, SRAT-C2-004 and SRAT-C2-006 that no production control or interface may bypass authority, link or confirmation requirements. If maintenance/test functions are needed, record them outside the operational SRATS baseline or as separately approved non-production derived requirements.",
    },
    {
        "section": "Major findings",
        "id": "M-01",
        "issue": "Selection expiry is wrong and incomplete.",
        "evidence": "The SDS requires five seconds and cancellation on authority, mode, link or parameter change. The LLR/model use 200 x 50 ms = ten seconds and omit these cancellation conditions.",
        "rules": "SDS-C2-001, SDS-IF-003",
        "fix": "Update SRAT-C2-006/HLR/LLR consistency for destructive-command confirmation and selection arming: if the SDS requires five seconds, correct the HLR/LLR timeout and add cancellation on authority, link, mode, selected-command or parameter change. If this is not already represented in the SRATS, add or update the SRATS acceptance criterion before changing lower-level requirements.",
    },
    {
        "section": "Major findings",
        "id": "M-02",
        "issue": "Timing is not deterministically implemented.",
        "evidence": "The C implementation ignores dt, decrements once per invocation, and calls time(NULL). Missed/repeated tick behaviour and exact boundary semantics are undefined; the model timer is not saturating.",
        "rules": "SIS-IMP-005, SMS-TIM-001/002/003",
        "fix": "Make SRAT-C2-001 and SRAT-C2-003 timing verifiable in the HLR/LLR: replace 'promptly' and implicit timing with measurable seconds/application-cycle limits, start/stop events and boundary behaviour. Keep clock-source and saturation mechanics in the LLR/SIS, with tests linked back to the SRATS rows.",
    },
    {
        "section": "Major findings",
        "id": "M-03",
        "issue": "Command conversion is uncontrolled.",
        "evidence": "LLR-C2-015, model line 77 and C lines 51/98/119 convert real/double to int16_t without units, accepted range, rounding, saturation or overflow handling.",
        "rules": "SIS-IMP-007, SIS-DAT-001, SMS-DF-002/004",
        "fix": "Extend the HLR/LLR interface assumptions consistently with the SRATS failure conditions for unintended command and incorrect acknowledgement association: define command parameter units, ranges, resolution and invalid-value response. Keep conversion algorithms in LLR/SIS, but require out-of-range values to inhibit transmission or be rejected.",
    },
    {
        "section": "Major findings",
        "id": "M-04",
        "issue": "The interface contract is incomplete.",
        "evidence": "The LLR omits units, resolution, update rate, latency, source, age, validity, initialization and failure behaviour. Raw integers are used for link, authority, mode and command kind. Several model inputs are absent from the C header.",
        "rules": "SDS-IF-001, SIS-DAT-001/004, SMS-DF-002",
        "fix": "Update the HLR/LLR interface tables to support the SRATS rows directly: link state for SRAT-C2-004, authority for SRAT-C2-002, acknowledgement/transaction ID for SRAT-C2-003/008, and display outputs for SRAT-C2-007. Define typed value domains, validity, initialization, failure response, update rate and latency/freshness for each HLR-visible signal.",
    },
    {
        "section": "Major findings",
        "id": "M-05",
        "issue": "Validity is encoded as a numeric sentinel.",
        "evidence": "LLR-C2-002 treats both -1 and 0 as connected, rather than carrying validity separately.",
        "rules": "SIS-DAT-002, SDS-PRN-006",
        "fix": "Align link validity handling with SRAT-C2-004. Revise the HLR/LLR so link value and link validity are separate, and invalid or unavailable link data shall be treated as not usable for transmission and shall drive LINK LOST or another defined degraded/error presentation rather than connected.",
    },
    {
        "section": "Major findings",
        "id": "M-06",
        "issue": "Generated code is explicitly permitted to be hand-edited.",
        "evidence": "This appears in LLR-C2-014, model line 97 and the C source banner. Model or configuration defects must instead be corrected at source.",
        "rules": "SIS-GEN-002",
        "fix": "Keep lifecycle/code-generation controls outside the SRATS behavioural rows but trace them to the DAL B/provisional assurance context in the SRATS header and applicable standards. HLR/LLR changes should require corrections through approved requirements and model/configuration source, not manual generated-code edits.",
    },
    {
        "section": "Major findings",
        "id": "M-07",
        "issue": "Traceability and approval controls are inadequate.",
        "evidence": "The LLR is unapproved, LLR-C2-013-016 have no parent or planned verification, and all requirements trace only to the top-level operator.",
        "rules": "SIS-IMP-001, SMS-CLS-002, SDS-TRC-001/002/003",
        "fix": "Bring HLR/LLR trace into agreement with the SRATS Traceability sheet: allocate SRAT-C2-004 to an HLR, correct the obsolete HLR-C2-404 link for SRAT-C2-008, remove or formally create the orphan SRAT-C2-999 for HLR-C2-009, and ensure every HLR/LLR has planned verification rather than unapproved or review-only status.",
    },
    {
        "section": "Major findings",
        "id": "M-08",
        "issue": "State transition priority is determined by diagram placement.",
        "evidence": "Simultaneous acknowledgement and timeout resolution depends on visual ordering instead of an explicit requirement-derived priority. Invalid input and unexpected enum handling are incomplete.",
        "rules": "SMS-STM-003/004, SDS-PRN-006",
        "fix": "Add HLR/LLR priority rules that preserve the SRATS safety intent: authority inhibition and lost-link prevention from SRAT-C2-002/004 take precedence over send/accepted behaviour, while acknowledgement and timeout handling remain consistent with SRAT-C2-003. Add verification cases for simultaneous events.",
    },
    {
        "section": "Major findings",
        "id": "M-09",
        "issue": "Status meaning is carried by colour alone.",
        "evidence": "ACCEPTED is green and everything else red, with empty status text and no icon or alternative cue.",
        "rules": "SIS-IMP-008, SDS-HMI-002",
        "fix": "Align with SRAT-C2-007 without over-claiming it: retain the required green/red colour indication, but add a derived HLR/HMI requirement or update SRAT-C2-007 to include non-colour cues for accepted, rejected, pending, timeout and error states. Add inspection criteria beyond 'correct colour displayed'.",
    },
    {
        "section": "Major findings",
        "id": "M-10",
        "issue": "The model violates naming and decomposition rules.",
        "evidence": "DCDS_C2_Temp, N_DoStuff, data1, flag, flag2 and temp are non-domain names. The operator has 15 inputs and 9 outputs without an approved decomposition justification.",
        "rules": "SMS-NAM-001/003",
        "fix": "Use the SRATS Traceability sheet to drive decomposition: HLR/LLR responsibilities should map separately to command response, authority inhibition, acknowledgement, lost link, restart, destructive confirmation, status display and transaction identity. Leave internal naming corrections to model/LLR standards, but require traceable model elements rather than a single catch-all N_DoStuff allocation.",
    },
    {
        "section": "Major findings",
        "id": "M-11",
        "issue": "Several LLR behaviours are absent or inconsistent in the stubs.",
        "evidence": "Link-state mapping, ABORT second-confirmation behaviour, unknown-command handling and reset colour retention are not implemented. parameter_changed is ignored and absent from the C interface.",
        "rules": "SIS-IMP-001/002, SDS-TRC-001",
        "fix": "Clarify HLR/LLR behaviours using the existing SRATS anchors: link-state mapping to SRAT-C2-004, ABORT/RETURN HOME confirmation to SRAT-C2-006, restart selection continuity to SRAT-C2-005, status presentation to SRAT-C2-007, and transaction handling to SRAT-C2-008. Add planned verification rows for each rather than relying on passing unrelated tests.",
    },
    {
        "section": "Major findings",
        "id": "M-12",
        "issue": "Requirements and dataflow are not sufficiently verifiable.",
        "evidence": "\"Quickly enough to look immediate\" has no measurable limit. The model uses data2 * 0; the C source stores but never uses g_confirm_level; multiple input fields are never consumed.",
        "rules": "SDS-PRN-001, SDS-IF-003, SIS-IMP-002, SMS-DF-001",
        "fix": "Revise SRAT-C2-001 and its linked HLR/LLR so 'promptly' and 'reasonably quickly' become measurable response limits with acceptance criteria. For each HLR-visible input, either link it to an existing SRATS behaviour and verification case or add an approved derived SRATS/HLR requirement before implementation.",
    },
]
DEMO_RULE_EVIDENCE = {
    "C-01": "The governing command rules require transmission to be inhibited unless authority is valid and the command link is usable; SRAT-C2-002 covers authority inhibition and SRAT-C2-004 requires transmission prevention when link is lost.",
    "C-02": "The destructive-command allocation records one confirmation action, and the state-machine rules require event-triggered transitions rather than repeated level-sensitive sends from a held control.",
    "C-03": "The acknowledgement and transaction-identity rules require accepted/rejected status to be associated with the command transaction being acknowledged, not with any unrelated positive acknowledgement.",
    "C-04": "The restart allocation restores a pending command selection for operator continuity; it does not authorize immediate transmission or restoration of an unsafe sending state after restart.",
    "C-05": "The transaction-identity allocation permits zero only as the startup/no-prior-identifier condition; transmitted commands require a numeric identifier suitable for request/acknowledgement correlation.",
    "C-06": "The dataflow and state-machine rules require invalid or unknown values to be handled explicitly and safely, preserving authority/link/acknowledgement safety intent rather than mapping corrupt values to valid accepted behaviour.",
    "C-07": "The implementation standards require deterministic resource use, bounded data handling and defensive handling of invalid interfaces for DAL B allocated software.",
    "C-08": "The configuration, HMI and generated-code rules require production behaviour to preserve command guards and exclude unapproved debug or test bypasses from the operational baseline.",
    "M-01": "The command and interface rules require a bounded selection window and cancellation when relevant authority, link, mode, command or parameter context changes.",
    "M-02": "The implementation and timing rules require deterministic timing with measurable limits, defined start/expiry events and verifiable boundary behaviour.",
    "M-03": "The data and implementation rules require command parameters to have defined units, ranges, scaling and invalid-value responses before conversion or transmission.",
    "M-04": "The interface/data rules require each HLR-visible signal to have a defined type/domain, validity, initialization, rate, freshness and failure response.",
    "M-05": "The data rules require validity to be represented separately from the signal value so unavailable or invalid link data cannot be interpreted as connected.",
    "M-06": "The generated-code lifecycle rule requires production generated behaviour to be changed through approved source artefacts and regeneration, not by manual code edits.",
    "M-07": "The traceability and approval rules require each HLR/LLR to have a valid parent allocation, planned verification and approved lifecycle status.",
    "M-08": "The state-machine rules require simultaneous events and invalid enum/input handling to have explicit requirement-derived priority and safe outcomes.",
    "M-09": "The HMI rules require status meaning to remain distinguishable and verifiable, not solely dependent on colour recognition.",
    "M-10": "The modelling rules require domain-meaningful naming and decomposition that supports reviewable trace from SRATS rows to HLR/LLR responsibilities and model elements.",
    "M-11": "The implementation and traceability rules require allocated HLR behaviours to be consistently carried into LLR, model, interface and verification artefacts.",
    "M-12": "The precision, interface and dataflow rules require measurable requirements and traceable use or removal of every HLR-visible data item.",
}
DEMO_FINDING_LOCATIONS = {
    "C-01": "HLR-C2-001/002/010; LLR-C2-001/010/013; model 61-63,85; C 81-83",
    "C-02": "HLR-C2-005; model 63; C 53,95-99",
    "C-03": "HLR-C2-004; LLR ack handling; model 70-71; C 58-65",
    "C-04": "HLR-C2-007; LLR-C2-007; model 43-53; C 29-33,95-99",
    "C-05": "HLR-C2-011; SRAT-C2-008; transaction ID lifecycle",
    "C-06": "HLR-C2-012; LLR-C2-012; model 51; C 111-114",
    "C-07": "dcds_c2_stub.c lines 42,50-51; step I/O dereferences",
    "C-08": "debug_force_send interface; production HMI button; C step",
    "M-01": "HLR-C2-003; LLR/model selection timer",
    "M-02": "HLR-C2-008; C timing path; model timer",
    "M-03": "LLR-C2-015; model 77; C 51,98,119",
    "M-04": "HLR section 4 external interface assumptions; LLR/model/C interface",
    "M-05": "HLR section 4 i_CommandLink; LLR-C2-002",
    "M-06": "LLR-C2-014; model note 97; C source banner",
    "M-07": "HLR allocation table; SRATS Traceability rows 9,13-14; LLR-C2-013-016",
    "M-08": "state transition model; simultaneous ack/timeout handling",
    "M-09": "HLR-C2-006; SRAT-C2-007; status display",
    "M-10": "model naming/decomposition: DCDS_C2_Temp, N_DoStuff, data1/flag/temp",
    "M-11": "HLR/LLR behavioural stubs; parameter_changed interface",
    "M-12": "HLR-C2-008; model data2 * 0; C g_confirm_level",
}
REQUIREMENT_ID_PATTERN = re.compile(
    r"\b(?:"
    r"DCDS-[A-Z0-9]+-(?:SRATS|SR|HLR|LLR|LLRV)-\d+[A-Z]?"
    r"|(?:SRATS|SRAT|SR|SYS|SRS|HLR|LLR|LLRV|REQ|REQT|SWREQ|SWR)[-_ ]?\d+(?:[.\-_]\d+)*[A-Z]?"
    r"|[A-Z]{2,8}-\d{2,5}(?:[.\-_][A-Z0-9]+)*"
    r")\b",
    re.IGNORECASE,
)


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
        if self._is_demo_model(model_name):
            return {
                "ok": True,
                "model": DEMO_MODEL_NAME,
                "status": "ready",
                "ready": True,
                "note": "Demo model is ready.",
                "reason": "Demo model is ready.",
                "latency_seconds": 0,
            }

        response = self._request_ollama("/api/ps")
        if isinstance(response, dict) and response.get("error"):
            return {"error": response["error"], "model": model_name}

        running_names = self._extract_model_names(response)
        if model_name in running_names:
            readiness = self._probe_model_response(model_name)
            if readiness["ready"]:
                return {"ok": True, "model": model_name, "status": "ready", "note": readiness["reason"], **readiness}
            return {"ok": False, "model": model_name, "status": "not-ready", "error": readiness["reason"], **readiness}

        warmup_response = self._load_model(model_name)
        if isinstance(warmup_response, dict) and warmup_response.get("error"):
            return {"ok": False, "model": model_name, "status": "start-failed", "error": warmup_response["error"]}

        readiness = self._probe_model_response(model_name)
        if readiness["ready"]:
            return {"ok": True, "model": model_name, "status": "ready", "note": readiness["reason"], **readiness}

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
        if self._is_demo_model(model_name):
            return {"ok": True, "model": DEMO_MODEL_NAME, "status": "not-running", "note": "Demo model does not run in Ollama."}

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
        if self._is_demo_model(model_name):
            return {
                "ok": True,
                "model": DEMO_MODEL_NAME,
                "status": "ready",
                "ready": True,
                "note": "Demo model is ready.",
                "reason": "Demo model is ready.",
                "latency_seconds": 0,
            }

        installed_response = self._request_ollama("/api/tags")
        if isinstance(installed_response, dict) and installed_response.get("error"):
            return {"ok": False, "model": model_name, "status": "offline", "error": installed_response["error"]}

        installed_names = self._extract_model_names(installed_response)
        if model_name not in installed_names:
            return {"ok": False, "model": model_name, "status": "missing", "error": f"The selected model {model_name} is not installed locally. Pull it first with: ollama pull {model_name}."}

        load_response = self._load_model(model_name)
        if isinstance(load_response, dict) and load_response.get("error"):
            return {"ok": False, "model": model_name, "status": "load-failed", "error": load_response["error"]}

        readiness = self._probe_model_response(model_name)
        if readiness["ready"]:
            return {"ok": True, "model": model_name, "status": "ready", "note": readiness["reason"], **readiness}

        return {"ok": False, "model": model_name, "status": "not-ready", "error": readiness["reason"], **readiness}

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

        if not any(model.get("name") == DEMO_MODEL_NAME for model in result):
            result.insert(0, self._demo_model_status())

        return {"models": result}

    def _is_demo_model(self, model_name):
        return str(model_name or "").strip().lower() == DEMO_MODEL_NAME.lower()

    def _demo_model_status(self):
        return {
            "name": DEMO_MODEL_NAME,
            "status": "online",
            "size": None,
            "modified_at": None,
            "digest": "demo-canned-review",
            "family": "demo",
        }

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
        reference_document_entries = body.get("reference_documents") or []

        if self._is_demo_model(model):
            return self._build_demo_reviewer_response()

        if documents:
            target_documents, document_errors = self._extract_uploaded_documents(documents, "document")
            if not target_documents:
                detail = f" {' '.join(document_errors[:3])}" if document_errors else ""
                return {"error": f"No readable document content was provided.{detail}"}
        elif document_text:
            target_documents = [{"name": "pasted-document", "content": document_text}]
        else:
            return {"error": "Please provide documentation text or files to review."}

        reference_documents = self._collect_reference_documents(d0178c_context, reference_locations, reference_document_entries)
        source_count = len(target_documents) + len(reference_documents)

        readiness = self._check_model_readiness(model)
        if not readiness["ready"]:
            return {
                "error": readiness["reason"],
                "review": "",
                "retrieved_chunks": [],
                "model": model,
                "source_count": source_count,
            }

        target_chunks = self._chunk_documents(target_documents, "TARGET")
        reference_chunks = self._chunk_documents(reference_documents, "REFERENCE")
        target_context_text = self._build_complete_target_context(target_chunks)
        retrieved_reference = self._retrieve_relevant_chunks(reference_chunks, skills_prompt, review_goal, target_context_text)
        reference_context_text = "\n\n".join(retrieved_reference[:8]) if retrieved_reference else "No reference material was provided."

        prompt_length = len(skills_prompt) + len(review_goal) + len(target_context_text) + len(reference_context_text)
        user_prompt = self._build_review_prompt(skills_prompt, review_goal, target_context_text, reference_context_text)

        ollama_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an experienced engineering reviewer. Use the highest available reasoning effort for this review. Be precise, practical, evidence-based, and apply common-sense engineering judgment to the full artefact and its context.",
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "stream": False,
            "format": "json",
            "options": self._build_review_model_options(prompt_length),
            "keep_alive": MODEL_KEEP_ALIVE,
        }

        response = self._request_ollama("/api/chat", ollama_payload, timeout=OLLAMA_REVIEW_TIMEOUT_SECONDS)
        if isinstance(response, dict) and response.get("error"):
            diagnostic_reason = self._diagnose_prompt_failure(response["error"], model, prompt_length, source_count)
            return {
                "error": diagnostic_reason,
                "review": "",
                "retrieved_chunks": target_chunks[:6] + retrieved_reference[:6],
                "model": model,
                "source_count": source_count,
            }

        review_text, extraction_error = self._extract_review_text(response)
        if extraction_error:
            return {
                "error": extraction_error,
                "review": "",
                "retrieved_chunks": target_chunks[:6] + retrieved_reference[:6],
                "model": model,
                "source_count": source_count,
            }
        review_result = self._parse_review_result(review_text)
        return {
            "review": review_result.get("summary") or review_text.strip(),
            "review_result": review_result,
            "retrieved_chunks": target_chunks[:6] + retrieved_reference[:6],
            "model": model,
            "source_count": source_count,
        }

    def _build_traceability_response(self, body):
        if not isinstance(body, dict):
            return {"error": "The traceability request was not received as valid JSON."}

        document_text = (body.get("document_text") or "").strip()
        documents = body.get("documents") or []
        d0178c_context = (body.get("d0178c_context") or "").strip()
        reference_locations = body.get("reference_locations") or []
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

        reference_documents = self._collect_reference_documents(d0178c_context, reference_locations, reference_document_entries)
        artefacts = []
        for document in target_documents:
            artefacts.append(self._build_traceability_artefact(document, "target"))
        for document in reference_documents:
            if document.get("name") == "DO-178C-context":
                continue
            artefacts.append(self._build_traceability_artefact(document, "associated"))

        all_requirements = []
        for artefact in artefacts:
            all_requirements.extend(artefact["requirements"])

        requirement_ids = {requirement["id"] for requirement in all_requirements}
        for requirement in all_requirements:
            mentioned = self._find_requirement_mentions(requirement["content"], requirement_ids, requirement["id"])
            requirement["mentions"] = mentioned

        relationships = self._build_traceability_relationships(all_requirements)
        return {
            "summary": {
                "artefact_count": len(artefacts),
                "requirement_count": len(all_requirements),
                "linked_requirement_count": len({item["source_id"] for item in relationships["forward"]} | {item["target_id"] for item in relationships["forward"]}),
            },
            "artefacts": artefacts,
            "forward": relationships["forward"],
            "reverse": relationships["reverse"],
            "unresolved_mentions": relationships["unresolved_mentions"],
        }

    def _build_traceability_artefact(self, document, role):
        name = document.get("name") or "document"
        artefact_type = self._infer_artefact_type(name, document.get("content") or "")
        requirements = self._extract_requirements_from_document(document, role, artefact_type)
        return {
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

    def _extract_requirements_from_document(self, document, role, artefact_type):
        name = document.get("name") or "document"
        content = (document.get("content") or "").strip()
        if not content:
            return []

        blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
        if len(blocks) <= 1:
            blocks = [line.strip() for line in content.splitlines() if line.strip()]

        requirements = []
        seen = set()
        for block in blocks:
            ids = self._find_requirement_ids(block)
            if not ids:
                continue
            requirement_id = ids[0]
            key = requirement_id.upper()
            if key in seen:
                continue
            seen.add(key)
            requirements.append(
                {
                    "id": requirement_id,
                    "content": self._compact_requirement_content(block),
                    "document": name,
                    "role": role,
                    "artefact_type": artefact_type,
                }
            )
        return requirements

    def _find_requirement_ids(self, text):
        seen = set()
        result = []
        for match in REQUIREMENT_ID_PATTERN.finditer(text or ""):
            requirement_id = re.sub(r"\s+", "-", match.group(0).strip())
            key = requirement_id.upper()
            if key not in seen:
                seen.add(key)
                result.append(requirement_id)
        return result

    def _compact_requirement_content(self, text, limit=650):
        content = re.sub(r"\s+", " ", (text or "").strip())
        if len(content) <= limit:
            return content
        return content[: limit - 3].rstrip() + "..."

    def _find_requirement_mentions(self, content, requirement_ids, own_id):
        mentions = []
        upper_content = (content or "").upper()
        own_key = own_id.upper()
        for requirement_id in sorted(requirement_ids, key=len, reverse=True):
            key = requirement_id.upper()
            if key == own_key:
                continue
            if re.search(rf"(?<![A-Z0-9]){re.escape(key)}(?![A-Z0-9])", upper_content):
                mentions.append(requirement_id)
        return mentions

    def _build_traceability_relationships(self, requirements):
        by_id = {requirement["id"]: requirement for requirement in requirements}
        forward = []
        reverse = []
        unresolved_mentions = []
        seen_pairs = set()

        for requirement in requirements:
            source_order = ARTEFACT_ORDER.get(requirement["artefact_type"], 99)
            for mentioned_id in requirement.get("mentions", []):
                target = by_id.get(mentioned_id)
                if not target:
                    unresolved_mentions.append(
                        {
                            "source_id": requirement["id"],
                            "source_document": requirement["document"],
                            "mentioned_id": mentioned_id,
                        }
                    )
                    continue
                target_order = ARTEFACT_ORDER.get(target["artefact_type"], 99)
                if target_order >= source_order:
                    upstream = requirement
                    downstream = target
                else:
                    upstream = target
                    downstream = requirement

                pair_key = (upstream["id"], upstream["document"], downstream["id"], downstream["document"])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                forward.append(
                    {
                        "source_id": upstream["id"],
                        "source_document": upstream["document"],
                        "source_type": upstream["artefact_type"],
                        "target_id": downstream["id"],
                        "target_document": downstream["document"],
                        "target_type": downstream["artefact_type"],
                    }
                )
                reverse.append(
                    {
                        "source_id": downstream["id"],
                        "source_document": downstream["document"],
                        "source_type": downstream["artefact_type"],
                        "target_id": upstream["id"],
                        "target_document": upstream["document"],
                        "target_type": upstream["artefact_type"],
                    }
                )

        forward.sort(key=lambda item: (ARTEFACT_ORDER.get(item["source_type"], 99), item["source_id"], item["target_id"]))
        reverse.sort(key=lambda item: (ARTEFACT_ORDER.get(item["source_type"], 99), item["source_id"], item["target_id"]), reverse=True)
        return {"forward": forward, "reverse": reverse, "unresolved_mentions": unresolved_mentions}

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

        readiness = self._probe_model_response(model)
        if not readiness["ready"]:
            return {"ready": False, "reason": readiness["reason"]}

        return {"ready": True, "reason": readiness["reason"]}

    def _build_review_prompt(self, skills_prompt, review_goal, target_context_text, reference_context_text):
        return (
            "You are reviewing only the TARGET document(s) for a safety-critical engineering workflow. "
            "Use the highest review effort available to the selected model: deliberate carefully, cross-check target statements against supplied references, and verify each proposed finding before reporting it. "
            "Perform a complete review of the entire supplied TARGET content, not only the most obviously relevant excerpts. "
            "Read all TARGET chunks in document order before deciding that no issue exists in a review area. "
            "REFERENCE material is supplied only as supporting context, standards guidance, or comparison evidence. "
            "Do not critique the REFERENCE material and do not suggest edits to reference documents. "
            "Only raise an issue when it applies to the TARGET document or when the TARGET document conflicts with, omits, or fails to satisfy the REFERENCE material. "
            "Every atomic comment must be framed as a change to the TARGET document. "
            "For every finding, explicitly identify the governing rule, standard objective, requirement, checklist item, or reference statement violated by the TARGET. "
            "Use the exact rule identifier/title when one is present in the REFERENCE excerpts, and include the REFERENCE document, section, and paragraph/row label that supplied it. "
            "Rule violated must contain the rule identifier(s) or title(s). Rule evidence must be different: summarise the actual obligation imposed by those rules and why it governs this finding, rather than repeating the same identifier list. "
            "If no governing rule is available in the supplied REFERENCE material, write 'Rule violated: Not found in provided reference material' and frame the finding as needing rule/evidence confirmation. "
            "For every issue mentioned in any review section above the atomic comment list, identify the precise TARGET location using the exact document, section, and paragraph/row labels provided in the TARGET excerpts. "
            "Do not invent, estimate, or report page numbers. Page identifiers are not reliable in extracted Office/text content, so omit page numbers entirely from every Location field. "
            "Write each issue as an indented block beginning with two spaces and a location prefix, such as '  Location: document filename.docx, section Verification Evidence, paragraph 12 - ...' or '  Location: document interfaces.xlsx, section Worksheet: Interfaces, row 8 - ...'. "
            "Indent continuation lines under that issue by four spaces, using '    Rule violated:', '    Rule evidence:', '    Issue:', '    Evidence:', and '    Target fix:'. "
            "Separate every issue block with one blank line. Do not put details for multiple issues under the same Location, Issue, Evidence, or Target fix fields. "
            "Repeat the Location, Rule violated, Rule evidence, Issue, Evidence, and Target fix fields for each distinct issue, even when two issues occur in the same document section. "
            "Every issue block in a review section must be replicated as a separate entry in atomic_comments at the bottom so it can be copied easily. "
            "For LLR, low-level requirement, interface, signal, data item, API, message, port, or parameter issues, first check the target and reference excerpts for an interface table, interface definition table, data dictionary, signal list, API definition, ICD, or similar definition source. "
            "Do not raise an interface-related issue until you have compared the requirement against that definition source. "
            "If the interface table defines the item, cite that definition in Evidence and judge the TARGET against it. "
            "If no interface definition source is available, say 'Interface definition source not found in provided artefacts' and frame the finding as a missing evidence/definition issue, not as an assumed interface defect. "
            "Do not report vague locations such as 'throughout the document' unless you also list the specific document, section, and paragraph/row labels where the issue appears. "
            "Apply practical engineering judgment and common sense to the target content for completeness, consistency, clarity, risks, omissions, and suitability for use. "
            "Always include a visual check, a spelling and grammar check (not overly pedantic), a process review, and a traceability review if relevant. "
            "If a review area is not applicable, say so briefly rather than inventing an answer.\n\n"
            f"Skills prompt:\n{skills_prompt or 'Review for clarity, traceability, hazards, and omissions.'}\n\n"
            f"Review goal:\n{review_goal}\n\n"
            f"Complete TARGET document content to review:\n{target_context_text}\n\n"
            f"REFERENCE material for context only:\n{reference_context_text}\n\n"
            "Scope rule: if a problem appears only in REFERENCE material, do not report it as a review finding. "
            "Use REFERENCE material to judge the TARGET document, not as a document under review. "
            "A finding is incomplete unless it links the TARGET evidence to the actual rule or reference requirement being violated.\n\n"
            "Return a JSON object with the following shape and no extra commentary:\n"
            "{\n"
            "  \"summary\": \"Short overall assessment\",\n"
            "  \"sections\": [\n"
            "    {\"title\": \"Visual review\", \"content\": \"For each distinct issue use a separate indented block: Location, Rule violated, Rule evidence, Issue, Evidence, Target fix. Put one blank line between issue blocks. If no issue exists, state that no issue was found in the complete reviewed target content.\"},\n"
            "    {\"title\": \"Spelling and grammar\", \"content\": \"For each distinct issue use a separate indented block: Location, Rule violated, Rule evidence, Issue, Evidence, Target fix. Put one blank line between issue blocks. If no issue exists, state that no issue was found in the complete reviewed target content.\"},\n"
            "    {\"title\": \"Process review\", \"content\": \"For each distinct issue use a separate indented block: Location, Rule violated, Rule evidence, Issue, Evidence, Target fix. Put one blank line between issue blocks. If no issue exists, state that no issue was found in the complete reviewed target content.\"},\n"
            "    {\"title\": \"Traceability review\", \"content\": \"For each distinct issue use a separate indented block: Location, Rule violated, Rule evidence, Issue, Evidence, Target fix. Put one blank line between issue blocks. If no issue exists, state that no issue was found in the complete reviewed target content.\"},\n"
            "    {\"title\": \"Additional observations\", \"content\": \"For each distinct issue use a separate indented block: Location, Rule violated, Rule evidence, Issue, Evidence, Target fix. Put one blank line between issue blocks. If no issue exists, state that no issue was found in the complete reviewed target content.\"}\n"
            "  ],\n"
            "  \"atomic_comments\": [\n"
            "    {\"id\": \"A1\", \"location\": \"document DOCUMENT, section SECTION, paragraph/row LABEL\", \"violated_rule\": \"REFERENCE document, section SECTION, paragraph/row LABEL - exact rule id/title or Not found in provided reference material\", \"rule_evidence\": \"Short quote or paraphrase of the governing rule\", \"issue\": \"Short target-document issue description\", \"comment\": \"Atomic comment to resolve in the TARGET document\", \"suggested_resolution\": \"How to fix the TARGET document\"}\n"
            "  ]\n"
            "}"
        )

    def _build_demo_reviewer_response(self):
        review_result = self._build_demo_review_result()
        return {
            "review": review_result["summary"],
            "review_result": review_result,
            "retrieved_chunks": [],
            "model": DEMO_MODEL_NAME,
            "source_count": 0,
        }

    def _build_demo_review_result(self):
        sections = []
        atomic_comments = []
        for section_name in ("Critical findings", "Major findings"):
            findings = [finding for finding in DEMO_REVIEW_FINDINGS if finding["section"] == section_name]
            sections.append(
                {
                    "title": section_name,
                    "content": "\n\n".join(self._format_demo_issue_block(finding) for finding in findings),
                }
            )
            for finding in findings:
                atomic_comments.append(self._build_demo_atomic_comment(finding))

        return {
            "summary": "Demo review completed: 8 critical findings and 12 major findings were identified.",
            "sections": sections,
            "atomic_comments": atomic_comments,
        }

    def _format_demo_issue_block(self, finding):
        return (
            f"Location: {self._demo_location_for_finding(finding)}\n"
            f"    Rule violated: {finding['rules']}\n"
            f"    Rule evidence: {self._demo_rule_evidence_for_finding(finding)}\n"
            f"    Issue: {finding['issue']}\n"
            f"    Evidence: {finding['evidence']}\n"
            f"    Target fix: {finding['fix']}"
        )

    def _build_demo_atomic_comment(self, finding):
        return {
            "id": finding["id"],
            "location": self._demo_location_for_finding(finding),
            "violated_rule": finding["rules"],
            "rule_evidence": self._demo_rule_evidence_for_finding(finding),
            "issue": finding["issue"],
            "comment": finding["evidence"],
            "suggested_resolution": finding["fix"],
        }

    def _demo_rule_evidence_for_finding(self, finding):
        return DEMO_RULE_EVIDENCE.get(finding["id"], "The cited rules define the governing obligation violated by the target evidence.")

    def _demo_location_for_finding(self, finding):
        return DEMO_FINDING_LOCATIONS.get(finding["id"], f"{finding['section']} {finding['id']}")

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
            return f"The portal could not reach Ollama at {OLLAMA_BASE_URL}. Check the Ollama service and ensure it is listening on the expected port."
        if "not found" in lowered:
            return f"The selected model {model} was not found locally. Pull it first with: ollama pull {model}."
        return f"The review request failed: {error_message}"

    def _collect_reference_documents(self, d0178c_context, reference_locations, reference_document_entries=None):
        documents = []
        if d0178c_context.strip():
            documents.append({"name": "DO-178C-context", "content": d0178c_context.strip()})

        uploaded_documents, _ = self._extract_uploaded_documents(reference_document_entries or [], "reference")
        documents.extend(uploaded_documents)

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
                if not self._is_supported_document_path(candidate):
                    continue
                content = self._read_document_file(candidate)
                if content:
                    documents.append({"name": str(candidate), "content": content})

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

    def _is_supported_document_path(self, path):
        suffix = path.suffix.lower()
        return suffix in WORD_EXTENSIONS | EXCEL_EXTENSIONS | LEGACY_OFFICE_EXTENSIONS | TEXT_SOURCE_EXTENSIONS or suffix == ""

    def _read_document_file(self, path):
        try:
            return self._extract_document_bytes(path.name, path.read_bytes())
        except OSError:
            return ""

    def _extract_document_bytes(self, name, raw_content):
        suffix = Path(name).suffix.lower()
        if suffix in WORD_EXTENSIONS:
            return self._extract_docx_text(raw_content)
        if suffix in EXCEL_EXTENSIONS:
            return self._extract_xlsx_text(raw_content)
        if suffix in LEGACY_OFFICE_EXTENSIONS:
            return self._extract_legacy_doc_text(raw_content)

        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return raw_content.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return ""

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

    def _build_review_model_options(self, prompt_length=0):
        requested_context = self._estimate_review_context_tokens(prompt_length)
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

    def _retrieve_relevant_chunks(self, chunks, skills_prompt, review_goal, comparison_text=""):
        query = " ".join([skills_prompt, review_goal, comparison_text]).lower()
        query_terms = set(re.findall(r"[a-zA-Z0-9_]+", query))
        scored = []
        for chunk in chunks:
            chunk_lower = chunk.lower()
            score = 0
            for term in query_terms:
                if len(term) < 3:
                    continue
                score += chunk_lower.count(term)
            if re.search(r"\b(rule|shall|must|required|objective|standard|compliance|criterion|criteria)\b", chunk_lower):
                score += 2
            if re.search(r"\b[A-Z]{2,10}[-_ ]?\d+(?:[.\-_]\d+)*[A-Z]?\b", chunk):
                score += 2
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        ranked = [chunk for _, chunk in scored if chunk]
        return ranked[:8] if ranked else chunks[:3]

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

    def _load_model(self, model_name):
        return self._request_ollama(
            "/api/generate",
            {"model": model_name, "prompt": "", "stream": False, "keep_alive": MODEL_KEEP_ALIVE},
            timeout=OLLAMA_LOAD_TIMEOUT_SECONDS,
        )

    def _unload_model(self, model_name):
        return self._request_ollama(
            "/api/generate",
            {"model": model_name, "prompt": "", "stream": False, "keep_alive": 0},
            timeout=OLLAMA_STOP_TIMEOUT_SECONDS,
        )

    def _probe_model_response(self, model_name):
        start_time = time.time()
        response = self._request_ollama(
            "/api/generate",
            {
                "model": model_name,
                "prompt": "Reply with OK.",
                "stream": False,
                "keep_alive": MODEL_KEEP_ALIVE,
                "options": {"num_predict": 3, "temperature": 0},
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
    server = ThreadingHTTPServer(("127.0.0.1", 8000), OllamaDemoHandler)
    print("Ollama reviewer demo running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
