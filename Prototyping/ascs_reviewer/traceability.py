"""Deterministic requirement traceability analysis."""

import re
import uuid

from app_config import ARTEFACT_ORDER
from document_processing import REQUIREMENT_ID_PATTERN


class TraceabilityMixin:
    """Discover requirements and build lifecycle traceability diagnostics."""

    def _build_traceability_response(self, body):
        if not isinstance(body, dict):
            return {"error": "The traceability request was not received as valid JSON."}

        document_text = (body.get("document_text") or "").strip()
        documents = body.get("documents") or []
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

        reference_documents = self._collect_reference_documents(reference_document_entries)
        artefacts = []
        for index, document in enumerate(target_documents, start=1):
            artefacts.append(self._build_traceability_artefact(document, "target", f"target-{index}"))
        for index, document in enumerate(reference_documents, start=1):
            artefacts.append(self._build_traceability_artefact(document, "associated", f"associated-{index}"))

        all_requirements = []
        for artefact in artefacts:
            all_requirements.extend(artefact["requirements"])

        relationships = self._build_traceability_relationships(all_requirements)
        diagnostics = self._build_traceability_diagnostics(all_requirements, relationships)
        return {
            "summary": {
                "artefact_count": len(artefacts),
                "requirement_count": len(all_requirements),
                "linked_requirement_count": diagnostics["linked_requirement_count"],
                "complete_requirement_count": diagnostics["complete_requirement_count"],
                "coverage_percent": diagnostics["coverage_percent"],
                "gap_count": len(diagnostics["gaps"]),
                "unresolved_reference_count": len(relationships["unresolved_mentions"]),
                "ambiguous_reference_count": len(relationships["ambiguous_references"]),
                "duplicate_id_count": len(relationships["duplicate_ids"]),
            },
            "artefacts": artefacts,
            "forward": relationships["forward"],
            "reverse": relationships["reverse"],
            "unresolved_mentions": relationships["unresolved_mentions"],
            "ambiguous_references": relationships["ambiguous_references"],
            "duplicate_ids": relationships["duplicate_ids"],
            "coverage_by_type": diagnostics["coverage_by_type"],
            "gaps": diagnostics["gaps"],
            "integrity_issues": diagnostics["integrity_issues"],
            "matrix": diagnostics["matrix"],
        }

    def _build_traceability_artefact(self, document, role, artefact_uid=None):
        name = document.get("name") or "document"
        artefact_uid = artefact_uid or f"{role}-1"
        artefact_type = self._infer_artefact_type(name, document.get("content") or "")
        requirements = self._extract_requirements_from_document(document, role, artefact_type, artefact_uid)
        return {
            "uid": artefact_uid,
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

    def _extract_requirements_from_document(self, document, role, artefact_type, artefact_uid):
        name = document.get("name") or "document"
        content = (document.get("content") or "").strip()
        if not content:
            return []

        blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
        if len(blocks) <= 1:
            blocks = [line.strip() for line in content.splitlines() if line.strip()]

        requirements = []
        occurrence_counts = {}
        for block_index, block in enumerate(blocks, start=1):
            requirement_id = self._select_defined_requirement_id(block)
            if not requirement_id:
                continue
            normalized_id = self._normalize_requirement_id(requirement_id)
            occurrence_counts[normalized_id] = occurrence_counts.get(normalized_id, 0) + 1
            occurrence = occurrence_counts[normalized_id]
            requirements.append(
                {
                    "id": requirement_id,
                    "normalized_id": normalized_id,
                    "uid": f"{artefact_uid}::{normalized_id}::{occurrence}",
                    "content": self._compact_requirement_content(block),
                    "mentions": self._find_requirement_mentions(block, requirement_id),
                    "document": name,
                    "role": role,
                    "artefact_type": self._infer_requirement_type(requirement_id, artefact_type),
                    "occurrence": occurrence,
                    "source_block": block_index,
                }
            )
        return requirements

    def _select_defined_requirement_id(self, block):
        candidates = self._find_requirement_ids(block)
        if not candidates:
            return None

        compact = re.sub(r"\s+", " ", (block or "").strip())
        for candidate in candidates:
            escaped = re.escape(candidate)
            if re.match(rf"^{escaped}(?![A-Z0-9])", compact, re.IGNORECASE):
                return candidate
            if re.match(rf"^(?:requirement id|requirement|req id|id)\s*[:=-]?\s*{escaped}(?![A-Z0-9])", compact, re.IGNORECASE):
                return candidate
            if re.match(rf"^Row\s+[^:]+:.*?=\s*{escaped}(?![A-Z0-9])", compact, re.IGNORECASE):
                return candidate
        return None

    def _find_requirement_ids(self, text):
        seen = set()
        result = []
        for match in REQUIREMENT_ID_PATTERN.finditer(text or ""):
            requirement_id = self._normalize_requirement_id(match.group(0))
            key = requirement_id
            if key not in seen:
                seen.add(key)
                result.append(requirement_id)
        return result

    def _normalize_requirement_id(self, requirement_id):
        return re.sub(r"[\s_]+", "-", str(requirement_id or "").strip()).upper()

    def _infer_requirement_type(self, requirement_id, fallback="OTHER"):
        normalized = self._normalize_requirement_id(requirement_id)
        for artefact_type in ("LLRV", "SRATS", "HLR", "LLR"):
            if re.search(rf"(?:^|-){artefact_type}(?:-|$)", normalized):
                return artefact_type
        if re.search(r"(?:^|-)(?:SRAT|SR)(?:-|$)", normalized):
            return "SR"
        return fallback

    def _compact_requirement_content(self, text, limit=650):
        content = re.sub(r"\s+", " ", (text or "").strip())
        if len(content) <= limit:
            return content
        return content[: limit - 3].rstrip() + "..."

    def _find_requirement_mentions(self, content, own_id):
        own_key = self._normalize_requirement_id(own_id)
        return [requirement_id for requirement_id in self._find_requirement_ids(content) if requirement_id != own_key]

    def _build_traceability_relationships(self, requirements):
        by_id = {}
        for requirement in requirements:
            by_id.setdefault(requirement["normalized_id"], []).append(requirement)

        duplicate_ids = [
            {
                "id": normalized_id,
                "occurrences": [
                    {
                        "uid": requirement["uid"],
                        "document": requirement["document"],
                        "source_block": requirement["source_block"],
                        "content": requirement["content"],
                    }
                    for requirement in matches
                ],
            }
            for normalized_id, matches in sorted(by_id.items())
            if len(matches) > 1
        ]
        forward = []
        reverse = []
        unresolved_mentions = []
        ambiguous_references = []
        seen_pairs = set()

        for requirement in requirements:
            source_order = ARTEFACT_ORDER.get(requirement["artefact_type"], 99)
            for mentioned_id in requirement.get("mentions", []):
                normalized_mention = self._normalize_requirement_id(mentioned_id)
                targets = by_id.get(normalized_mention, [])
                if not targets:
                    unresolved_mentions.append(
                        {
                            "source_uid": requirement["uid"],
                            "source_id": requirement["id"],
                            "source_document": requirement["document"],
                            "mentioned_id": normalized_mention,
                        }
                    )
                    continue
                if len(targets) > 1:
                    ambiguous_references.append(
                        {
                            "source_uid": requirement["uid"],
                            "source_id": requirement["id"],
                            "source_document": requirement["document"],
                            "mentioned_id": normalized_mention,
                            "candidate_uids": [target["uid"] for target in targets],
                        }
                    )
                    continue

                target = targets[0]
                target_order = ARTEFACT_ORDER.get(target["artefact_type"], 99)
                if source_order < target_order:
                    upstream = requirement
                    downstream = target
                elif target_order < source_order:
                    upstream = target
                    downstream = requirement
                else:
                    upstream = requirement
                    downstream = target

                relationship_kind = (
                    "same-level"
                    if source_order == target_order
                    else "adjacent"
                    if abs(source_order - target_order) == 1
                    else "cross-level"
                )
                pair_key = (
                    tuple(sorted((upstream["uid"], downstream["uid"])))
                    if relationship_kind == "same-level"
                    else (upstream["uid"], downstream["uid"])
                )
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                link = {
                    "source_uid": upstream["uid"],
                    "source_id": upstream["id"],
                    "source_document": upstream["document"],
                    "source_type": upstream["artefact_type"],
                    "target_uid": downstream["uid"],
                    "target_id": downstream["id"],
                    "target_document": downstream["document"],
                    "target_type": downstream["artefact_type"],
                    "relationship_kind": relationship_kind,
                }
                forward.append(link)
                reverse.append(
                    {
                        "source_uid": downstream["uid"],
                        "source_id": downstream["id"],
                        "source_document": downstream["document"],
                        "source_type": downstream["artefact_type"],
                        "target_uid": upstream["uid"],
                        "target_id": upstream["id"],
                        "target_document": upstream["document"],
                        "target_type": upstream["artefact_type"],
                        "relationship_kind": relationship_kind,
                    }
                )

        forward.sort(key=lambda item: (ARTEFACT_ORDER.get(item["source_type"], 99), item["source_id"], item["target_id"]))
        reverse.sort(key=lambda item: (ARTEFACT_ORDER.get(item["source_type"], 99), item["source_id"], item["target_id"]), reverse=True)
        return {
            "forward": forward,
            "reverse": reverse,
            "unresolved_mentions": unresolved_mentions,
            "ambiguous_references": ambiguous_references,
            "duplicate_ids": duplicate_ids,
        }

    def _build_traceability_diagnostics(self, requirements, relationships):
        forward = relationships["forward"]
        incoming = {requirement["uid"]: [] for requirement in requirements}
        outgoing = {requirement["uid"]: [] for requirement in requirements}
        lateral = {requirement["uid"]: [] for requirement in requirements}
        for link in forward:
            if link["relationship_kind"] == "same-level":
                lateral[link["source_uid"]].append(link)
                lateral[link["target_uid"]].append(link)
            else:
                outgoing[link["source_uid"]].append(link)
                incoming[link["target_uid"]].append(link)

        active_orders = sorted(
            {
                ARTEFACT_ORDER[requirement["artefact_type"]]
                for requirement in requirements
                if requirement["artefact_type"] in ARTEFACT_ORDER
            }
        )
        duplicate_uids = {
            occurrence["uid"]
            for duplicate in relationships["duplicate_ids"]
            for occurrence in duplicate["occurrences"]
        }
        gaps = []
        linked_requirement_count = 0
        complete_requirement_count = 0

        for requirement in requirements:
            uid = requirement["uid"]
            artefact_order = ARTEFACT_ORDER.get(requirement["artefact_type"])
            has_upstream = bool(incoming[uid])
            has_downstream = bool(outgoing[uid])
            has_lateral = bool(lateral[uid])
            is_linked = has_upstream or has_downstream or has_lateral
            if is_linked and uid not in duplicate_uids:
                linked_requirement_count += 1

            expects_upstream = artefact_order is not None and any(order < artefact_order for order in active_orders)
            expects_downstream = artefact_order is not None and any(order > artefact_order for order in active_orders)
            missing_directions = []
            if expects_upstream and not has_upstream:
                missing_directions.append("upstream")
                gaps.append(self._traceability_gap(requirement, "missing-upstream", "No link to an available upstream lifecycle level."))
            if expects_downstream and not has_downstream:
                missing_directions.append("downstream")
                gaps.append(self._traceability_gap(requirement, "missing-downstream", "No link to an available downstream lifecycle level."))

            if uid in duplicate_uids:
                trace_status = "duplicate"
            elif not is_linked:
                trace_status = "unlinked"
            elif missing_directions:
                trace_status = "partial"
            else:
                trace_status = "complete"
                complete_requirement_count += 1

            requirement["trace_status"] = trace_status
            requirement["upstream_link_count"] = len(incoming[uid])
            requirement["downstream_link_count"] = len(outgoing[uid])
            requirement["lateral_link_count"] = len(lateral[uid])

        coverage_by_type = []
        for artefact_type in sorted({item["artefact_type"] for item in requirements}, key=lambda item: ARTEFACT_ORDER.get(item, 99)):
            typed_requirements = [item for item in requirements if item["artefact_type"] == artefact_type]
            linked = [item for item in typed_requirements if item["trace_status"] not in {"unlinked", "duplicate"}]
            complete = [item for item in typed_requirements if item["trace_status"] == "complete"]
            coverage_by_type.append(
                {
                    "artefact_type": artefact_type,
                    "requirement_count": len(typed_requirements),
                    "linked_count": len(linked),
                    "complete_count": len(complete),
                    "coverage_percent": self._percentage(len(linked), len(typed_requirements)),
                }
            )

        integrity_issues = []
        integrity_issues.extend(
            {
                "severity": "error",
                "kind": "duplicate-id",
                "message": f"{item['id']} is defined {len(item['occurrences'])} times.",
            }
            for item in relationships["duplicate_ids"]
        )
        integrity_issues.extend(
            {
                "severity": "error",
                "kind": "unresolved-reference",
                "message": f"{item['source_id']} references missing {item['mentioned_id']}.",
            }
            for item in relationships["unresolved_mentions"]
        )
        integrity_issues.extend(
            {
                "severity": "error",
                "kind": "ambiguous-reference",
                "message": f"{item['source_id']} references duplicate {item['mentioned_id']}.",
            }
            for item in relationships["ambiguous_references"]
        )
        integrity_issues.extend(
            {
                "severity": "warning",
                "kind": "cross-level-link",
                "message": f"{link['source_id']} links directly to {link['target_id']}, skipping a lifecycle level.",
            }
            for link in forward
            if link["relationship_kind"] == "cross-level"
        )
        integrity_issues.extend(
            {
                "severity": "warning",
                "kind": "unlinked-requirement",
                "message": f"{requirement['id']} in {requirement['document']} has no resolved trace links.",
            }
            for requirement in requirements
            if requirement["trace_status"] == "unlinked"
        )

        matrix = [
            {
                "source": link["source_id"],
                "source_type": link["source_type"],
                "source_document": link["source_document"],
                "target": link["target_id"],
                "target_type": link["target_type"],
                "target_document": link["target_document"],
                "relationship_kind": link["relationship_kind"],
            }
            for link in forward
        ]
        requirement_count = len(requirements)
        return {
            "linked_requirement_count": linked_requirement_count,
            "complete_requirement_count": complete_requirement_count,
            "coverage_percent": self._percentage(linked_requirement_count, requirement_count),
            "coverage_by_type": coverage_by_type,
            "gaps": gaps,
            "integrity_issues": integrity_issues,
            "matrix": matrix,
        }

    def _traceability_gap(self, requirement, kind, message):
        return {
            "severity": "warning",
            "kind": kind,
            "requirement_uid": requirement["uid"],
            "requirement_id": requirement["id"],
            "artefact_type": requirement["artefact_type"],
            "document": requirement["document"],
            "message": message,
        }

    def _percentage(self, numerator, denominator):
        return round((numerator / denominator) * 100, 1) if denominator else 0.0

