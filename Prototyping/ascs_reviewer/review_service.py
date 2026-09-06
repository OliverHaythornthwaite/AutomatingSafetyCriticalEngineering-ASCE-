"""Review orchestration and prompt composition."""

import json

from app_config import SKILLS_DIRECTORY
from skill_store import SkillStore, SkillValidationError


SKILL_STORE = SkillStore(SKILLS_DIRECTORY).load()


class ReviewServiceMixin:
    """Compose review requests and coordinate the supporting capabilities."""

    def _build_reviewer_response(self, body):
        if not isinstance(body, dict):
            return {"error": "The review request was not received as valid JSON. Please try again from the application."}

        try:
            prompt_configuration = self._resolve_prompt_configuration(body)
        except SkillValidationError as exc:
            return {"error": str(exc)}
        skills_prompt = prompt_configuration["skills_prompt"]
        review_goal = prompt_configuration["review_goal"]
        document_text = (body.get("document_text") or "").strip()
        provider = self._configured_provider()
        if provider.get("error"):
            return {"error": provider["error"], "review": "", "retrieved_chunks": []}
        model = provider["model"]
        context_window = provider["context_limit"]
        documents = body.get("documents") or []
        reference_document_entries = body.get("reference_documents") or []
        rag_options = body.get("rag") if isinstance(body.get("rag"), dict) else {}
        rag_enabled = rag_options.get("enabled", True) is not False
        try:
            retrieval_limit = max(4, min(40, int(rag_options.get("max_chunks") or 24)))
        except (TypeError, ValueError):
            retrieval_limit = 24

        if documents:
            target_documents, document_errors = self._extract_uploaded_documents(documents, "document")
            if not target_documents:
                detail = f" {' '.join(document_errors[:3])}" if document_errors else ""
                return {"error": f"No readable document content was provided.{detail}"}
        elif document_text:
            target_documents = [{"name": "pasted-document", "content": document_text}]
        else:
            return {"error": "Please provide documentation text or files to review."}

        reference_documents = self._collect_reference_documents(reference_document_entries)
        rag_status = self._get_rag_status()
        source_count = len(target_documents) + len(reference_documents) + (rag_status["source_count"] if rag_enabled else 0)

        target_chunks = self._chunk_documents(target_documents, "TARGET")
        reference_chunks = self._chunk_documents(reference_documents, "REFERENCE")
        target_context_text = self._build_complete_target_context(target_chunks)
        relevance_plan = self._build_relevance_stepthrough(target_chunks, skills_prompt, review_goal)
        retrieval_query = relevance_plan["query"]
        retrieved_reference = self._retrieve_relevant_chunks(
            reference_chunks,
            skills_prompt,
            review_goal,
            relevance_plan["comparison_text"],
            limit=retrieval_limit,
            focus_chunks=relevance_plan["focus_chunks"],
        )
        retrieved_rag = self._retrieve_rag_chunks(
            retrieval_query,
            retrieval_limit,
            focus_queries=relevance_plan["focus_chunks"],
        ) if rag_enabled else []
        retrieval_candidates = self._interleave_chunks(retrieved_reference, retrieved_rag)
        retrieval_budget = self._calculate_retrieval_budget(
            len(target_context_text), len(skills_prompt) + len(review_goal), context_window
        )
        selected_reference = self._select_chunks_with_budget(retrieval_candidates, retrieval_limit, retrieval_budget)
        reference_context_text = "\n\n".join(selected_reference) if selected_reference else "No reference material was provided."
        retrieval_summary = {
            "enabled": rag_enabled,
            "context_window_tokens": context_window,
            "available_chunks": len(reference_chunks) + (rag_status["chunk_count"] if rag_enabled else 0),
            "selected_chunks": len(selected_reference),
            "context_budget_characters": retrieval_budget,
            "loaded_store": rag_status["name"] if rag_enabled else "",
            "retrieval_mode": rag_status["retrieval_mode"] if rag_enabled and rag_status["loaded"] else "local TF-IDF",
            "relevance_stepthrough": {
                "strategy": "section-aware staged retrieval",
                "target_chunks_scanned": len(target_chunks),
                "focus_chunks": len(relevance_plan["focus_chunks"]),
                "focus_locations": relevance_plan["focus_locations"],
                "query_characters": len(retrieval_query),
            },
        }

        user_prompt = self._build_review_prompt(prompt_configuration["prompt_configuration"], target_context_text, reference_context_text)
        prompt_length = len(user_prompt)

        request_payload = {
            "messages": [
                {
                    "role": "system",
                    "content": prompt_configuration["prompt_configuration"]["reviewer_role"],
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "stream": False,
            "options": self._build_review_model_options(prompt_length, context_window),
        }

        response = self._request_model_chat(provider, request_payload, timeout=provider["review_timeout"])
        if isinstance(response, dict) and response.get("error"):
            diagnostic_reason = self._diagnose_prompt_failure(response["error"], model, prompt_length, source_count)
            return {
                "error": diagnostic_reason,
                "review": "",
                "retrieved_chunks": target_chunks[:6] + selected_reference[:6],
                "context_window": context_window,
                "source_count": source_count,
                "retrieval": retrieval_summary,
            }

        review_text, extraction_error = self._extract_review_text(response)
        if extraction_error:
            return {
                "error": extraction_error,
                "review": "",
                "retrieved_chunks": target_chunks[:6] + selected_reference[:6],
                "context_window": context_window,
                "source_count": source_count,
                "retrieval": retrieval_summary,
            }
        review_result = self._parse_review_result(review_text)
        repair_attempted = self._review_requires_atomic_comment_repair(review_result)
        repair_source = ""
        if repair_attempted:
            repaired_comments = self._request_atomic_comment_repair(
                provider, model, context_window, review_text
            )
            if repaired_comments:
                review_result["atomic_comments"] = repaired_comments
                repair_source = "model repair"
            else:
                fallback_comments = self._build_atomic_comments_from_section_prose(review_result["sections"])
                if fallback_comments:
                    review_result["atomic_comments"] = fallback_comments
                    repair_source = "section fallback"
        review_result["sections"] = [
            section for section in review_result["sections"]
            if not self._is_atomic_comments_summary_section(section)
        ]
        return {
            "review": review_result.get("summary") or review_text.strip(),
            "review_result": review_result,
            "retrieved_chunks": target_chunks[:6] + selected_reference[:6],
            "context_window": context_window,
            "source_count": source_count,
            "retrieval": retrieval_summary,
            "atomic_comment_repair": {
                "attempted": repair_attempted,
                "source": repair_source,
                "comment_count": len(review_result["atomic_comments"]),
            },
            "prompt_mode": prompt_configuration["prompt_mode"],
            "skill_name": prompt_configuration.get("skill_name"),
        }

    def _resolve_prompt_configuration(self, body):
        prompt_mode = str(body.get("prompt_mode") or "skill").strip().lower()
        if prompt_mode == "skill":
            composed = SKILL_STORE.compose(body.get("skill_id") or "general-review", body.get("skill_answers"))
            return {**composed, "prompt_mode": "skill"}
        if prompt_mode != "custom":
            raise SkillValidationError("Prompt mode must be 'skill' or 'custom'.")

        custom = body.get("custom_prompt")
        if not isinstance(custom, dict):
            raise SkillValidationError("Custom prompt fields must be supplied as a JSON object.")
        allowed_fields = {
            "reviewer_role",
            "objective",
            "review_method",
            "additional_checks",
        }
        unknown_fields = sorted(set(custom) - allowed_fields)
        if unknown_fields:
            raise SkillValidationError(f"Unknown custom prompt field(s): {', '.join(unknown_fields)}")

        values = {}
        for field in allowed_fields:
            value = custom.get(field, "")
            if not isinstance(value, str):
                raise SkillValidationError(f"Custom field {field!r} must be text.")
            values[field] = value.strip()
        if not values["reviewer_role"]:
            raise SkillValidationError("Reviewer role is required in custom mode.")
        if not values["objective"]:
            raise SkillValidationError("Review objective is required in custom mode.")

        configured_instructions = []
        labels = (
            ("review_method", "Review method"),
            ("additional_checks", "Additional checks"),
        )
        configured_instructions.extend(f"{label}: {values[field]}" for field, label in labels if values[field])
        review_sections = [
            {
                "title": "Scope and applicable obligations",
                "instruction": "Review scope, applicability, assumptions, dependencies, governing plans, standards, requirements, instructions, and declared compliance obligations.",
            },
            {
                "title": "Completeness, correctness and clarity",
                "instruction": "Review every applicable statement for completeness, correctness, necessity, clarity, atomicity, unambiguity, consistency, and feasible implementation.",
            },
            {
                "title": "Safety and failure behaviour",
                "instruction": "Review hazards, safety objectives, assumptions, allocations, modes, interfaces, invalid inputs, degraded behaviour, recovery, and safe failure response.",
            },
            {
                "title": "Lifecycle, governance and control",
                "instruction": "Review responsibilities, independence, activities, inputs, outputs, entry and exit criteria, approvals, configuration control, changes, deviations, anomalies, and retained records.",
            },
            {
                "title": "Traceability and consistency",
                "instruction": "Review forward and reverse traceability, cross-document consistency, derived content, orphan content, duplication, conflicts, and complete allocation.",
            },
            {
                "title": "Verification and objective evidence",
                "instruction": "Review measurable acceptance criteria, verification methods, normal and robustness coverage, repeatability, objective evidence, tools, environments, and closure status.",
            },
            {
                "title": "Presentation and controlled use",
                "instruction": "Review structure, identifiers, terminology, cross-references, tables, readability, spelling, grammar, revision status, and suitability for controlled engineering use.",
            },
        ]
        if values["additional_checks"]:
            review_sections.append(
                {
                    "title": "User-supplied additional checks",
                    "instruction": values["additional_checks"],
                }
            )
        prompt_configuration = {
            "reviewer_role": values["reviewer_role"],
            "objective": values["objective"],
            "instructions": configured_instructions,
            "review_sections": review_sections,
        }
        return {
            "prompt_mode": "custom",
            "skill_id": None,
            "skill_name": "Custom review",
            "skills_prompt": "\n".join([values["reviewer_role"], values["objective"], *configured_instructions]),
            "review_goal": values["objective"],
            "prompt_configuration": prompt_configuration,
        }

    def _build_review_prompt(self, prompt_configuration, target_context_text, reference_context_text):
        reviewer_role = prompt_configuration["reviewer_role"]
        objective = prompt_configuration["objective"]
        instructions = prompt_configuration.get("instructions") or []
        review_sections = prompt_configuration["review_sections"]
        section_contract = [
            {
                "title": section["title"],
                "content": (
                    f"{section['instruction']} Concisely summarize coverage, passes, and non-applicable checks for "
                    "this section. Put every actionable issue in atomic_comments instead of duplicating its details here."
                ),
            }
            for section in review_sections
        ]
        output_contract = {
            "summary": "Short overall assessment",
            "atomic_comments": [
                {
                    "id": "A1",
                    "location": "Exact TARGET provenance header when available; otherwise the best target identifier or Target location not specified",
                    "violated_rule": "REFERENCE rule identifier/title, or Not found in provided reference material",
                    "rule_evidence": "Short paraphrase of the governing obligation",
                    "issue": "Short target-document issue description",
                    "comment": "Atomic comment to resolve in the TARGET document",
                    "suggested_resolution": "Actionable change to the TARGET document",
                }
            ],
            "sections": section_contract,
        }
        configured_instructions = "\n".join(f"- {instruction}" for instruction in instructions)

        return (
            f"Reviewer role:\n{reviewer_role}\n\n"
            "Review only the supplied TARGET document(s). Read the complete TARGET in document order and "
            "use the highest available review effort. Treat REFERENCE material only as standards, guidance, "
            "or comparison evidence; do not critique or propose changes to REFERENCE documents.\n\n"
            f"Review objective:\n{objective}\n\n"
            f"Configured instructions:\n{configured_instructions or '- Apply the review objective directly.'}\n\n"
            "Complete-checklist rules:\n"
            "- Execute every configured review section with equal diligence; no section is optional or secondary.\n"
            "- Check every applicable target statement against every applicable supplied plan, standard, requirement, and instruction.\n"
            "- Do not sample, omit lower-severity checks, or stop after finding significant issues.\n"
            "- Treat user-supplied context as additive; it must never narrow or replace the complete checklist.\n"
            "- Record a clear pass or justified not-applicable result when a section produces no finding.\n\n"
            "Evidence rules:\n"
            "- Report a finding only when it applies to the TARGET and is supported by target evidence.\n"
            "- Every target chunk starts with a provenance header such as [TARGET: document | section X | paragraph/row/requirement Y]. Copy that exact location without the surrounding brackets.\n"
            "- Prefer the resolved section supplied in the TARGET header. If an exact location cannot be resolved, use the best document/requirement/row/paragraph identifier available, or 'Target location not specified'.\n"
            "- Never omit a finding or atomic comment because its exact location is unavailable, and never use 'section not resolved'. Never invent page numbers.\n"
            "- Identify the governing REFERENCE rule when available and explain its obligation separately.\n"
            "- If no governing rule is supplied, write 'Not found in provided reference material'.\n"
            "- For interface findings, first compare the target against any supplied interface definition.\n"
            "- Put every actionable issue exactly once in atomic_comments; do not rely on section prose to report findings.\n\n"
            "Output-priority rules:\n"
            "- Populate the complete atomic_comments array before writing sections. It is mandatory whenever any issue is reported.\n"
            "- Never create an atomic_comments_summary section and never replace the array with text that points to another list.\n"
            "- Keep section content concise so the response budget is reserved for the complete atomic comment list.\n\n"
            f"Complete TARGET content:\n{target_context_text}\n\n"
            f"REFERENCE material:\n{reference_context_text}\n\n"
            "Return only valid JSON matching this configured contract:\n"
            f"{json.dumps(output_contract, ensure_ascii=False, indent=2)}"
        )
