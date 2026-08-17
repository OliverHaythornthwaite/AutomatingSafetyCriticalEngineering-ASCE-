import json
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import server  # noqa: E402


class ReviewerLogicTests(unittest.TestCase):
    def setUp(self):
        self.handler = server.ASCSReviewerHandler.__new__(server.ASCSReviewerHandler)

    def test_model_status_contains_only_ollama_models(self):
        responses = {
            "/api/tags": {
                "models": [
                    {
                        "name": "review-model:latest",
                        "size": 123,
                        "details": {"family": "test-family"},
                    }
                ]
            },
            "/api/ps": {"models": []},
        }
        self.handler._request_ollama = lambda path, *args, **kwargs: responses[path]

        result = self.handler._get_model_status()

        self.assertEqual(["review-model:latest"], [item["name"] for item in result["models"]])
        self.assertEqual("offline", result["models"][0]["status"])

    def test_traceability_links_requirements_between_artefacts(self):
        result = self.handler._build_traceability_response(
            {
                "documents": [
                    {"name": "system-HLR.txt", "content": "HLR-001 The system shall reject invalid input."},
                    {"name": "software-LLR.txt", "content": "LLR-002 implements HLR-001 using a bounded check."},
                ]
            }
        )

        self.assertEqual(2, result["summary"]["requirement_count"])
        self.assertEqual("HLR-001", result["forward"][0]["source_id"])
        self.assertEqual("LLR-002", result["forward"][0]["target_id"])
        self.assertEqual(100.0, result["summary"]["coverage_percent"])

    def test_traceability_reports_complete_lifecycle_chain(self):
        result = self.handler._build_traceability_response(
            {
                "documents": [
                    {"name": "safety-SRATS.txt", "content": "SRATS-001 The system shall prevent unsafe output."},
                    {"name": "system-HLR.txt", "content": "HLR-001 refines SRATS-001 and shall reject invalid input."},
                    {"name": "software-LLR.txt", "content": "LLR-001 implements HLR-001 with a bounded check."},
                    {"name": "verification-LLRV.txt", "content": "LLRV-001 verifies LLR-001 at both boundaries."},
                ]
            }
        )

        self.assertEqual(4, result["summary"]["complete_requirement_count"])
        self.assertEqual(100.0, result["summary"]["coverage_percent"])
        self.assertEqual([], result["gaps"])
        self.assertEqual(3, len(result["matrix"]))

    def test_traceability_reports_unresolved_references_and_gaps(self):
        result = self.handler._build_traceability_response(
            {
                "documents": [
                    {"name": "system-HLR.txt", "content": "HLR-001 The system shall reject invalid input."},
                    {"name": "software-LLR.txt", "content": "LLR-002 implements HLR-999 using a bounded check."},
                ]
            }
        )

        self.assertEqual(1, result["summary"]["unresolved_reference_count"])
        self.assertEqual(2, result["summary"]["gap_count"])
        self.assertEqual(0.0, result["summary"]["coverage_percent"])
        self.assertEqual("HLR-999", result["unresolved_mentions"][0]["mentioned_id"])

    def test_traceability_reports_duplicate_and_ambiguous_ids(self):
        result = self.handler._build_traceability_response(
            {
                "documents": [
                    {"name": "primary-HLR.txt", "content": "HLR-001 The system shall reject invalid input."},
                    {"name": "secondary-HLR.txt", "content": "HLR-001 The system shall reject invalid data."},
                    {"name": "software-LLR.txt", "content": "LLR-001 implements HLR-001."},
                ]
            }
        )

        self.assertEqual(1, result["summary"]["duplicate_id_count"])
        self.assertEqual(1, result["summary"]["ambiguous_reference_count"])
        self.assertEqual("HLR-001", result["duplicate_ids"][0]["id"])
        self.assertEqual([], result["matrix"])

    def test_traceability_flags_cross_level_links(self):
        result = self.handler._build_traceability_response(
            {
                "documents": [
                    {"name": "safety-SRATS.txt", "content": "SRATS-001 The system shall prevent unsafe output."},
                    {"name": "software-LLR.txt", "content": "LLR-001 directly implements SRATS-001."},
                ]
            }
        )

        self.assertEqual("cross-level", result["matrix"][0]["relationship_kind"])
        self.assertTrue(any(issue["kind"] == "cross-level-link" for issue in result["integrity_issues"]))

    def test_traceability_does_not_treat_reference_paragraph_as_definition(self):
        result = self.handler._build_traceability_response(
            {
                "documents": [
                    {
                        "name": "system-HLR.txt",
                        "content": (
                            "Requirement ID: HLR-001\n"
                            "The system shall reject invalid input.\n\n"
                            "Trace HLR-001 to the corresponding verification evidence."
                        ),
                    }
                ]
            }
        )

        self.assertEqual(1, result["summary"]["requirement_count"])
        self.assertEqual(0, result["summary"]["duplicate_id_count"])
        self.assertEqual("unlinked", result["artefacts"][0]["requirements"][0]["trace_status"])
        self.assertTrue(any(issue["kind"] == "unlinked-requirement" for issue in result["integrity_issues"]))

    def test_traceability_extracts_mixed_lifecycle_pasted_content(self):
        result = self.handler._build_traceability_response(
            {
                "document_text": (
                    "SRATS-001 The system shall prevent unsafe output.\n\n"
                    "HLR-001 refines SRATS-001 and shall reject invalid input.\n\n"
                    "LLR-001 implements HLR-001 using a bounded check."
                )
            }
        )

        self.assertEqual(3, result["summary"]["requirement_count"])
        self.assertEqual(3, result["summary"]["complete_requirement_count"])
        self.assertEqual(["SRATS", "HLR", "LLR"], [item["artefact_type"] for item in result["coverage_by_type"]])

    def test_traceability_scans_references_beyond_display_excerpt(self):
        long_requirement = "LLR-001 " + ("bounded behaviour " * 50) + "implements HLR-001."
        result = self.handler._build_traceability_response(
            {
                "documents": [
                    {"name": "system-HLR.txt", "content": "HLR-001 The system shall reject invalid input."},
                    {"name": "software-LLR.txt", "content": long_requirement},
                ]
            }
        )

        self.assertTrue(result["artefacts"][1]["requirements"][0]["content"].endswith("..."))
        self.assertEqual(["HLR-001"], result["artefacts"][1]["requirements"][0]["mentions"])
        self.assertEqual(1, len(result["matrix"]))

    def test_guided_skill_composes_defaults_and_answers(self):
        result = self.handler._resolve_prompt_configuration(
            {
                "prompt_mode": "skill",
                "skill_id": "llr-review",
                "skill_answers": {"implementation-context": "model"},
            }
        )

        self.assertEqual("Low-level requirements review", result["skill_name"])
        self.assertIn("model-based design and generated code", result["skills_prompt"])
        self.assertNotIn("Prioritise", result["skills_prompt"])

    def test_all_guided_skills_use_complete_non_selective_checklists(self):
        prohibited = re.compile(r"prioriti[sz]|emphasis|focus area", re.IGNORECASE)
        for skill in server.SKILL_STORE.list_skills():
            with self.subTest(skill=skill["id"]):
                input_text = json.dumps(skill["inputs"], ensure_ascii=False)
                self.assertIsNone(prohibited.search(input_text))
                self.assertGreaterEqual(len(skill["prompt"]["review_sections"]), 8)
                self.assertTrue(any("equal diligence" in item for item in skill["prompt"]["instructions"]))

    def test_custom_mode_composes_individual_fields(self):
        result = self.handler._resolve_prompt_configuration(
            {
                "prompt_mode": "custom",
                "custom_prompt": {
                    "reviewer_role": "Act as an independent reviewer.",
                    "objective": "Assess the target requirements.",
                    "review_method": "Inspect every requirement",
                    "additional_checks": "Check project-specific partitioning constraints",
                },
            }
        )

        self.assertEqual("custom", result["prompt_mode"])
        self.assertIn("Additional checks: Check project-specific partitioning constraints", result["skills_prompt"])
        self.assertIn("Traceability and consistency", [section["title"] for section in result["prompt_configuration"]["review_sections"]])
        self.assertEqual("Assess the target requirements.", result["review_goal"])

    def test_custom_mode_rejects_removed_selective_fields(self):
        with self.assertRaisesRegex(server.SkillValidationError, "Unknown custom prompt field"):
            self.handler._resolve_prompt_configuration(
                {
                    "prompt_mode": "custom",
                    "custom_prompt": {
                        "reviewer_role": "Act as an independent reviewer.",
                        "objective": "Assess the target requirements.",
                        "reporting_priorities": "Only report selected findings",
                    },
                }
            )

    def test_review_prompt_uses_skill_configured_sections(self):
        configured = self.handler._resolve_prompt_configuration(
            {"prompt_mode": "skill", "skill_id": "llr-review", "skill_answers": {}}
        )

        prompt = self.handler._build_review_prompt(
            configured["prompt_configuration"],
            "TARGET: LLR-001 shall bound the value.",
            "REFERENCE: HLR-001 requires bounded input.",
        )

        self.assertIn('"title": "Deterministic behaviour and algorithms"', prompt)
        self.assertIn('"title": "State and timing"', prompt)
        self.assertNotIn('"title": "Visual review"', prompt)
        self.assertIn("Assume a mixed model-based and hand-written implementation.", prompt)
        self.assertIn("Reviewer role:\nAct as an independent low-level software requirements and design reviewer.", prompt)
        self.assertIn("Execute every configured review section with equal diligence", prompt)
        self.assertIn("every applicable supplied plan, standard, requirement, and instruction", prompt)

    def test_unknown_skill_is_rejected_before_review(self):
        result = self.handler._build_reviewer_response(
            {"prompt_mode": "skill", "skill_id": "missing-skill"}
        )

        self.assertIn("Unknown review skill", result["error"])


class StaticServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.ASCSReviewerHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_index_is_branded(self):
        with urllib.request.urlopen(f"{self.base_url}/", timeout=2) as response:
            content = response.read().decode("utf-8")

        self.assertEqual(200, response.status)
        self.assertIn("<title>ASCS Reviewer</title>", content)

    def test_setup_grid_does_not_stretch_shorter_panel(self):
        stylesheet = (PROJECT_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertRegex(stylesheet, r"\.grid\s*\{[^}]*align-items:\s*start")

    def test_javascript_asset_is_served(self):
        with urllib.request.urlopen(f"{self.base_url}/app.js", timeout=2) as response:
            content = response.read().decode("utf-8")

        self.assertEqual(200, response.status)
        self.assertIn("async function runReview()", content)

    def test_skill_definitions_are_served(self):
        with urllib.request.urlopen(f"{self.base_url}/api/skills", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual("1.1", payload["schema_version"])
        self.assertGreaterEqual(len(payload["skills"]), 6)
        self.assertTrue(all(skill.get("inputs") is not None for skill in payload["skills"]))

    def test_javascript_static_element_references_exist(self):
        html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")
        javascript = (PROJECT_DIR / "app.js").read_text(encoding="utf-8")
        element_ids = set(re.findall(r'\bid="([^"]+)"', html))
        referenced_ids = set(re.findall(r"getElementById\('([^']+)'\)", javascript))

        self.assertEqual(set(), referenced_ids - element_ids)

    def test_unknown_static_path_is_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base_url}/../server.py", timeout=2)

        self.assertEqual(404, caught.exception.code)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
