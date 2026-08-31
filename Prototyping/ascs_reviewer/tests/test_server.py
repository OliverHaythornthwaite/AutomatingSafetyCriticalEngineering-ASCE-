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
        self.handler._clear_rag_content()
        with server.MODEL_CONTEXT_CACHE_LOCK:
            server.MODEL_CONTEXT_CACHE.clear()

    def tearDown(self):
        self.handler._clear_rag_content()

    def test_model_status_contains_only_ollama_models(self):
        responses = {
            "/api/tags": {
                "models": [
                    {
                        "name": "review-model:latest",
                        "size": 123,
                        "details": {
                            "format": "gguf",
                            "family": "test-family",
                            "parameter_size": "3B",
                            "quantization_level": "Q4_K_M",
                        },
                    }
                ]
            },
            "/api/ps": {
                "models": [
                    {
                        "name": "review-model:latest",
                        "context_length": 8192,
                        "size_vram": 456,
                    }
                ]
            },
            "/api/show": {"model_info": {"test-family.context_length": 32768}},
        }
        self.handler._request_ollama = lambda path, *args, **kwargs: responses[path]

        result = self.handler._get_model_status()

        self.assertEqual(["review-model:latest"], [item["name"] for item in result["models"]])
        model = result["models"][0]
        self.assertEqual("online", model["status"])
        self.assertEqual("gguf", model["format"])
        self.assertEqual("3B", model["parameter_size"])
        self.assertEqual("Q4_K_M", model["quantization_level"])
        self.assertEqual(8192, model["context_length"])
        self.assertEqual(32768, model["max_context_length"])
        self.assertEqual(456, model["size_vram"])

    def test_hosted_provider_is_normalized_and_rejects_embedded_credentials(self):
        provider = self.handler._resolve_model_provider(
            {
                "model_provider": {
                    "mode": "hosted",
                    "base_url": "https://models.example.test/",
                    "model": "review-model",
                    "api_key": "session-token",
                }
            }
        )

        self.assertEqual("https://models.example.test/v1", provider["base_url"])
        self.assertEqual("review-model", provider["model"])
        self.assertEqual("session-token", provider["api_key"])
        rejected = self.handler._resolve_model_provider(
            {"model_provider": {"mode": "hosted", "base_url": "https://user:pass@example.test/v1", "model": "m"}}
        )
        self.assertIn("cannot contain credentials", rejected["error"])

    def test_hosted_chat_uses_openai_compatible_contract(self):
        captured = {}

        def request_hosted(provider, path, payload=None, timeout=None):
            captured.update(provider=provider, path=path, payload=payload, timeout=timeout)
            return {
                "choices": [{"message": {"content": '{"summary":"Reviewed"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }

        self.handler._request_hosted_server = request_hosted
        response = self.handler._request_model_chat(
            {"mode": "hosted", "base_url": "https://models.example.test/v1", "model": "review-model", "api_key": ""},
            {
                "messages": [{"role": "user", "content": "Review this"}],
                "options": {"temperature": 0, "top_p": 1, "seed": 42, "num_predict": 500},
            },
            timeout=30,
        )

        self.assertEqual("/chat/completions", captured["path"])
        self.assertEqual("review-model", captured["payload"]["model"])
        self.assertEqual({"type": "json_object"}, captured["payload"]["response_format"])
        self.assertEqual(42, captured["payload"]["seed"])
        self.assertEqual('{"summary":"Reviewed"}', response["message"]["content"])
        self.assertEqual(12, response["prompt_eval_count"])

    def test_hosted_health_reports_model_availability(self):
        self.handler._request_hosted_server = lambda provider, path, timeout=None: {
            "data": [{"id": "review-model", "max_model_len": 65536}, {"id": "other-model"}]
        }

        result = self.handler._check_hosted_model_server(
            {
                "model_provider": {
                    "mode": "hosted",
                    "base_url": "https://models.example.test/v1",
                    "model": "review-model",
                }
            }
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["model_available"])
        self.assertIn("review-model", result["available_models"])
        self.assertEqual(65536, result["max_context_length"])

    def test_scade_graphical_formats_are_extracted_as_structured_xml(self):
        content = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<display name="PrimaryDisplay"><layer name="Status">'
            b'<object oid="42"><binding>HLR-001</binding></object>'
            b'</layer></display>'
        )

        for extension in (".ogfx", ".sgfx", ".dgfx"):
            with self.subTest(extension=extension):
                result = self.handler._extract_document_bytes(f"display{extension}", content)
                self.assertIn(f"[SCADE {extension[1:].upper()} structured model", result)
                self.assertIn('display name="PrimaryDisplay"', result)
                self.assertIn('binding text="HLR-001"', result)

    def test_scade_sss_scenario_is_extracted_as_labelled_text(self):
        content = b"SSS\nset input_speed 120\ncheck output_valid true\n"

        result = self.handler._extract_document_bytes("nominal.sss", content)

        self.assertIn("[SCADE SSS document: nominal.sss]", result)
        self.assertIn("set input_speed 120", result)
        self.assertIn("check output_valid true", result)

    def test_vector_store_loads_and_reports_dense_metadata(self):
        result = self.handler._load_rag_content(
            {
                "name": "assurance-store.json",
                "store": {
                    "name": "Assurance knowledge",
                    "embedding_model": "nomic-embed-text",
                    "dimensions": 2,
                    "chunks": [
                        {"id": "rule-1", "source": "standard.md", "content": "Verification shall be independent.", "embedding": [1, 0]},
                        {"id": "rule-2", "source": "plan.md", "content": "Changes require impact analysis.", "embedding": [0, 1]},
                    ],
                },
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["chunk_count"])
        self.assertEqual(2, result["vector_chunk_count"])
        self.assertEqual(2, result["source_count"])
        self.assertEqual("hybrid dense vector + TF-IDF", result["retrieval_mode"])

    def test_dense_rag_query_uses_embedding_similarity(self):
        self.handler._load_rag_content(
            {
                "store": {
                    "embedding_model": "embed-model",
                    "dimensions": 2,
                    "chunks": [
                        {"id": "first", "content": "Alpha guidance", "embedding": [1, 0]},
                        {"id": "second", "content": "Beta guidance", "embedding": [0, 1]},
                    ],
                }
            }
        )
        self.handler._request_ollama = lambda path, payload=None, timeout=None: {"embeddings": [[0, 1]]}

        result = self.handler._retrieve_rag_chunks("unrelated query", limit=2)

        self.assertIn("chunk second", result[0])

    def test_knowledge_documents_build_local_vector_index(self):
        result = self.handler._load_rag_content(
            {
                "documents": [
                    {"name": "safety-plan.txt", "content": "Safety changes shall receive independent impact analysis."}
                ],
                "append": True,
            }
        )

        self.assertTrue(result["loaded"])
        self.assertGreaterEqual(result["chunk_count"], 1)
        self.assertEqual("local TF-IDF vector", result["retrieval_mode"])

    def test_retrieval_budget_keeps_highest_ranked_complete_chunks(self):
        chunks = ["A" * 20, "B" * 20, "C" * 20]

        result = self.handler._select_chunks_with_budget(chunks, limit=3, character_budget=45)

        self.assertEqual(chunks[:2], result)

    def test_review_injects_retrieved_rag_evidence_with_provenance(self):
        self.handler._load_rag_content(
            {
                "documents": [
                    {"name": "project-standard.txt", "content": "Independent verification shall cover every safety requirement."}
                ]
            }
        )
        self.handler._check_model_readiness = lambda model: {"ready": True, "reason": "ready"}
        captured = {}

        def request_ollama(path, payload=None, timeout=None):
            captured["payload"] = payload
            return {
                "message": {
                    "content": json.dumps({"summary": "Reviewed", "sections": [], "atomic_comments": []})
                }
            }

        self.handler._request_ollama = request_ollama

        result = self.handler._build_reviewer_response(
            {
                "model": "review-model",
                "prompt_mode": "skill",
                "skill_id": "general-review",
                "document_text": "LLR-001 shall be independently verified.",
                "rag": {"enabled": True, "max_chunks": 12},
            }
        )

        prompt = captured["payload"]["messages"][1]["content"]
        self.assertIn("[RAG: project-standard.txt", prompt)
        self.assertIn("Independent verification shall cover every safety requirement", prompt)
        self.assertGreaterEqual(result["retrieval"]["selected_chunks"], 1)

    def test_review_can_use_hosted_provider_without_local_readiness_check(self):
        self.handler._check_model_readiness = lambda model: self.fail("Hosted reviews must not check local Ollama readiness")
        captured = {}

        def request_model_chat(provider, payload, timeout):
            captured.update(provider=provider, payload=payload, timeout=timeout)
            return {"message": {"content": json.dumps({"summary": "Hosted review", "sections": [], "atomic_comments": []})}}

        self.handler._request_model_chat = request_model_chat
        result = self.handler._build_reviewer_response(
            {
                "model": "hosted-review-model",
                "model_provider": {
                    "mode": "hosted",
                    "base_url": "https://models.example.test/v1",
                    "model": "hosted-review-model",
                    "api_key": "temporary",
                },
                "prompt_mode": "skill",
                "skill_id": "general-review",
                "document_text": "LLR-001 shall reject invalid input.",
                "rag": {"enabled": False},
            }
        )

        self.assertEqual("Hosted review", result["review"])
        self.assertEqual("hosted", result["provider_mode"])
        self.assertEqual("hosted", captured["provider"]["mode"])
        self.assertEqual("hosted-review-model", captured["payload"]["model"])

    def test_perfect_benchmark_output_scores_one_hundred(self):
        output = {
            "findings": [
                {"requirement_id": requirement_id, "rule_id": rule_id}
                for requirement_id, rule_id in server.BENCHMARK_EXPECTED_FINDINGS
            ],
            "pass_ids": sorted(server.BENCHMARK_CONTROL_IDS),
        }

        result = self.handler._score_benchmark_output(output)

        self.assertEqual(100.0, result["score"])
        self.assertEqual(100.0, result["precision_percent"])
        self.assertEqual(100.0, result["recall_percent"])
        self.assertEqual(100.0, result["control_accuracy_percent"])

    def test_benchmark_penalizes_missed_and_unexpected_findings(self):
        output = {
            "findings": [
                {"requirement_id": "LLR-B01", "rule_id": "BENCH-R1"},
                {"requirement_id": "LLR-B05", "rule_id": "BENCH-R2"},
            ],
            "pass_ids": ["LLR-B06"],
        }

        result = self.handler._score_benchmark_output(output)

        self.assertLess(result["score"], 50)
        self.assertEqual(1, result["true_positive_count"])
        self.assertEqual(1, result["false_positive_count"])
        self.assertEqual(3, result["missed_count"])
        self.assertEqual(50.0, result["control_accuracy_percent"])

    def test_model_benchmark_uses_repeatable_generation_settings(self):
        self.handler._start_model = lambda body: {"ok": True, "status": "ready"}
        captured = {}

        def request_ollama(path, payload=None, timeout=None):
            captured["path"] = path
            captured["payload"] = payload
            captured["timeout"] = timeout
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "findings": [
                                {"requirement_id": requirement_id, "rule_id": rule_id}
                                for requirement_id, rule_id in server.BENCHMARK_EXPECTED_FINDINGS
                            ],
                            "pass_ids": sorted(server.BENCHMARK_CONTROL_IDS),
                        }
                    )
                }
            }

        self.handler._request_ollama = request_ollama

        result = self.handler._run_model_benchmark({"model": "benchmark-model"})

        self.assertEqual(100.0, result["score"])
        self.assertEqual("/api/chat", captured["path"])
        self.assertEqual(0, captured["payload"]["options"]["temperature"])
        self.assertEqual(42, captured["payload"]["options"]["seed"])
        self.assertEqual(32768, captured["payload"]["options"]["num_ctx"])
        self.assertEqual(server.OLLAMA_BENCHMARK_TIMEOUT_SECONDS, captured["timeout"])

    def test_hosted_benchmark_skips_local_model_start(self):
        self.handler._start_model = lambda body: self.fail("Hosted benchmarks must not start a local model")

        def request_model_chat(provider, payload, timeout):
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "findings": [
                                {"requirement_id": requirement_id, "rule_id": rule_id}
                                for requirement_id, rule_id in server.BENCHMARK_EXPECTED_FINDINGS
                            ],
                            "pass_ids": sorted(server.BENCHMARK_CONTROL_IDS),
                        }
                    )
                }
            }

        self.handler._request_model_chat = request_model_chat
        result = self.handler._run_model_benchmark(
            {
                "model_provider": {
                    "mode": "hosted",
                    "base_url": "https://models.example.test/v1",
                    "model": "hosted-benchmark-model",
                }
            }
        )

        self.assertEqual(100.0, result["score"])
        self.assertEqual("hosted", result["provider_mode"])
        self.assertEqual(32768, result["context_window"])

    def test_review_context_window_can_be_raised_to_128k(self):
        self.assertEqual(131072, self.handler._resolve_review_context_window({"context_window": 131072}))
        options = self.handler._build_review_model_options(prompt_length=1000, context_window=131072)
        self.assertEqual(131072, options["num_ctx"])

        with self.assertRaisesRegex(ValueError, "between 8,192 and 131,072"):
            self.handler._resolve_review_context_window({"context_window": 262144})

        with self.assertRaisesRegex(ValueError, "supports at most 32,768"):
            self.handler._resolve_review_context_window({"context_window": 65536}, model_context_limit=32768)

    def test_model_warmup_uses_selected_context_window(self):
        captured = {}

        def request_ollama(path, payload=None, timeout=None):
            captured.update(path=path, payload=payload, timeout=timeout)
            return {"done": True}

        self.handler._request_ollama = request_ollama
        self.handler._load_model("review-model", 65536)

        self.assertEqual("/api/generate", captured["path"])
        self.assertEqual(65536, captured["payload"]["options"]["num_ctx"])

    def test_larger_context_increases_retrieval_budget(self):
        budget_32k = self.handler._calculate_retrieval_budget(1000, 1000, 32768)
        budget_128k = self.handler._calculate_retrieval_budget(1000, 1000, 131072)

        self.assertGreater(budget_128k, budget_32k)

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

    def test_sections_are_full_width_with_tooling_first(self):
        content = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")

        self.assertNotIn('class="grid"', content)
        self.assertLess(content.index("1. Tooling"), content.index("2. Retrieval knowledge (RAG)"))
        self.assertLess(content.index("2. Retrieval knowledge (RAG)"), content.index("3. Model access"))
        self.assertLess(content.index("3. Model access"), content.index("4. Review setup"))
        self.assertNotIn("Local, structured review", content)

    def test_all_main_sections_are_collapsible(self):
        content = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")

        self.assertEqual(6, content.count('class="panel collapsible-panel'))
        self.assertEqual(6, content.count('class="panel-summary"'))

    def test_tooling_lists_supported_document_types(self):
        content = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")

        supported_extensions = (
            server.WORD_EXTENSIONS
            | server.EXCEL_EXTENSIONS
            | server.LEGACY_OFFICE_EXTENSIONS
            | server.SCADE_XML_EXTENSIONS
            | server.SCADE_TEXT_EXTENSIONS
        )
        for extension in supported_extensions:
            self.assertIn(f"<code>{extension}</code>", content)
        self.assertIn("Text-based documents", content)
        self.assertIn("Direct text entry", content)

    def test_model_controls_have_consistent_buttons_and_reserved_scrollbar_space(self):
        javascript = (PROJECT_DIR / "app.js").read_text(encoding="utf-8")
        stylesheet = (PROJECT_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertEqual(4, javascript.count("secondary model-action"))
        self.assertIn("scrollbar-gutter: stable", stylesheet)
        self.assertRegex(stylesheet, r"\.model-actions > \.model-action\s*\{[^}]*flex:\s*0 0 5\.5rem")
        self.assertRegex(stylesheet, r"\.model-actions > \.model-action-ready\s*\{[^}]*width:\s*7rem")
        self.assertRegex(stylesheet, r"\.model-list\s*\{[^}]*overflow-x:\s*hidden")
        self.assertIn("renderModelMetadata(model)", javascript)
        self.assertIn('data-action="benchmark">Test</button>', javascript)

    def test_model_access_supports_local_and_hosted_modes(self):
        html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")
        javascript = (PROJECT_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="providerModeBtn"', html)
        self.assertIn('id="hostedBaseUrl"', html)
        self.assertIn('id="hostedModel"', html)
        self.assertIn('id="hostedApiKey"', html)
        self.assertIn('id="contextWindow"', html)
        self.assertIn('id="contextWindowStatus"', html)
        self.assertIn('id="hostedContextLimit"', html)
        self.assertIn("model_provider: modelProvider", javascript)
        self.assertIn("option.disabled = !contextLimit", javascript)
        self.assertNotIn("hostedApiKey: hostedApiKey.value", javascript)

    def test_tooling_formats_scroll_horizontally(self):
        stylesheet = (PROJECT_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertRegex(stylesheet, r"\.tooling-grid\s*\{[^}]*display:\s*flex")
        self.assertRegex(stylesheet, r"\.tooling-grid\s*\{[^}]*overflow-x:\s*auto")

    def test_javascript_asset_is_served(self):
        with urllib.request.urlopen(f"{self.base_url}/app.js", timeout=2) as response:
            content = response.read().decode("utf-8")

        self.assertEqual(200, response.status)
        self.assertIn("async function runReview()", content)

    def test_rag_status_endpoint_is_served(self):
        with urllib.request.urlopen(f"{self.base_url}/api/rag/status", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(200, response.status)
        self.assertFalse(payload["loaded"])
        self.assertEqual(0, payload["chunk_count"])
        self.assertIn("retrieval_mode", payload)

    def test_health_advertises_benchmark_and_rag_capabilities(self):
        with urllib.request.urlopen(f"{self.base_url}/api/health", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(server.API_VERSION, payload["api_version"])
        self.assertIn("model-benchmark-v1", payload["capabilities"])
        self.assertIn("rag-store-v1", payload["capabilities"])
        self.assertIn("hosted-model-v1", payload["capabilities"])
        self.assertIn("context-window-v1", payload["capabilities"])
        self.assertIn("model-context-discovery-v1", payload["capabilities"])

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

    def test_javascript_explains_stale_server_endpoints(self):
        javascript = (PROJECT_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("because the running ASCS Reviewer server is outdated", javascript)
        self.assertIn("Server update required: restart ASCS Reviewer", javascript)

    def test_unknown_static_path_is_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base_url}/../server.py", timeout=2)

        self.assertEqual(404, caught.exception.code)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
