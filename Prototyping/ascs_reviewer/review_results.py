"""Structured review-response parsing, normalization, and repair."""

import json
import re

from app_config import MODEL_KEEP_ALIVE, OLLAMA_REVIEW_TIMEOUT_SECONDS


class ReviewResultMixin:
    """Normalize model output into stable review sections and atomic comments."""

    def _parse_review_result(self, review_text):
        if not review_text:
            return {"summary": "No review returned.", "sections": [], "atomic_comments": []}

        text = review_text.strip()
        parsed = self._extract_json_value(text)
        if parsed is None:
            return {
                "summary": text,
                "sections": [{"title": "Review", "content": text}],
                "atomic_comments": [],
            }

        if isinstance(parsed, list):
            issue_keys = {"issue", "problem", "comment", "location", "suggested_resolution", "target_fix"}
            contains_comments = any(isinstance(item, dict) and issue_keys.intersection(item) for item in parsed)
            parsed = {
                "summary": "Review completed.",
                "atomic_comments" if contains_comments else "sections": parsed,
            }

        for wrapper_key in ("review_result", "review", "result", "output"):
            nested = parsed.get(wrapper_key) if isinstance(parsed, dict) else None
            if isinstance(nested, str):
                nested = self._extract_json_value(nested)
            if isinstance(nested, dict) and not any(key in parsed for key in ("summary", "sections", "atomic_comments")):
                parsed = nested
                break

        if not isinstance(parsed, dict):
            return {"summary": self._format_review_value(parsed), "sections": [], "atomic_comments": []}

        sections = parsed.get("sections") or parsed.get("review_sections") or []
        if isinstance(sections, dict):
            sections = [{"title": title, "content": content} for title, content in sections.items()]
        elif not isinstance(sections, list):
            sections = [sections] if sections else []

        atomic_comments = parsed.get("atomic_comments") or parsed.get("atomicComments") or parsed.get("comments") or parsed.get("findings") or []
        if isinstance(atomic_comments, dict):
            atomic_comments = [
                ({"id": comment_id, **comment} if isinstance(comment, dict) else {"id": comment_id, "comment": comment})
                for comment_id, comment in atomic_comments.items()
            ]
        elif not isinstance(atomic_comments, list):
            atomic_comments = [atomic_comments] if atomic_comments else []
        atomic_comments = [
            comment if isinstance(comment, dict) else {"comment": comment}
            for comment in atomic_comments
        ]

        normalized_sections = []
        for index, section in enumerate(sections):
            if isinstance(section, dict):
                title = section.get("title") or section.get("name") or f"Review section {index + 1}"
                content = section.get("content")
                if content is None:
                    content = (
                        section.get("findings")
                        or section.get("issues")
                        or section.get("assessment")
                        or section.get("text")
                        or {key: value for key, value in section.items() if key not in {"title", "name"}}
                    )
            else:
                title = f"Review section {index + 1}"
                content = section
            normalized_sections.append({
                "title": self._format_review_value(title) or "Review",
                "content": self._remove_page_references_from_locations(self._format_review_value(content)),
            })

        normalized_comments = [
            {
                "id": self._format_review_value(comment.get("id") or f"A{index + 1}"),
                "location": self._normalize_location_label(self._format_review_value(comment.get("location") or "")) or "Target location not specified",
                "violated_rule": self._normalize_rule_label(
                    self._format_review_value(
                        comment.get("violated_rule")
                        or comment.get("rule_violated")
                        or comment.get("applicable_rule")
                        or comment.get("rule")
                        or ""
                    )
                ),
                "rule_evidence": self._format_review_value(comment.get("rule_evidence") or comment.get("rule_reference") or ""),
                "issue": self._format_review_value(comment.get("issue") or comment.get("title") or "Issue"),
                "comment": self._format_review_value(comment.get("comment") or comment.get("evidence") or comment.get("details") or ""),
                "suggested_resolution": self._format_review_value(comment.get("suggested_resolution") or comment.get("target_fix") or comment.get("resolution") or ""),
            }
            for index, comment in enumerate(atomic_comments)
            if isinstance(comment, dict)
        ]
        normalized_comments = self._ensure_atomic_comments_cover_section_issues(normalized_sections, normalized_comments)

        return {
            "summary": self._format_review_value(
                parsed.get("summary")
                or parsed.get("overall_assessment")
                or parsed.get("executive_summary")
                or "Review completed."
            ),
            "sections": normalized_sections,
            "atomic_comments": normalized_comments,
        }

    def _review_requires_atomic_comment_repair(self, review_result):
        if review_result.get("atomic_comments"):
            return False
        sections = review_result.get("sections") or []
        if any(self._is_atomic_comments_summary_section(section) for section in sections):
            return True
        issue_language = re.compile(
            r"\b(missing|absent|undefined|unclear|ambiguous|inconsistent|conflict|confusion|gap|risk|"
            r"fail(?:s|ed|ure)?|unapproved|incomplete|insufficient|incorrect|lacks?|should|however)\b",
            re.IGNORECASE,
        )
        return any(issue_language.search(str(section.get("content") or "")) for section in sections)

    def _is_atomic_comments_summary_section(self, section):
        title = str(section.get("title") or "") if isinstance(section, dict) else ""
        normalized = re.sub(r"[^a-z0-9]+", "", title.lower())
        return normalized in {"atomiccommentssummary", "atomiccommentslist", "atomiccomments"}

    def _request_atomic_comment_repair(self, provider, model, context_window, review_text):
        repair_contract = {
            "atomic_comments": [
                {
                    "id": "A1",
                    "location": "Best available TARGET provenance, or Target location not specified",
                    "violated_rule": "REFERENCE rule, or Not found in provided reference material",
                    "rule_evidence": "Short governing obligation",
                    "issue": "One concise issue",
                    "comment": "Target evidence and required correction",
                    "suggested_resolution": "Specific actionable resolution",
                }
            ]
        }
        prompt = (
            "The previous review omitted its mandatory atomic_comments array. Convert every actionable issue in "
            "the previous review into one atomic comment. Preserve all distinct issues, do not create comments "
            "for passes or not-applicable statements, do not reassess the source documents, and do not omit an "
            "issue when its location is unavailable. Return only valid JSON matching this contract:\n"
            f"{json.dumps(repair_contract, ensure_ascii=False, indent=2)}\n\n"
            f"Previous review response:\n{review_text}"
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Convert review findings into complete atomic engineering comments."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": self._build_review_model_options(len(prompt), context_window),
            "keep_alive": MODEL_KEEP_ALIVE,
        }
        response = self._request_model_chat(provider, payload, timeout=OLLAMA_REVIEW_TIMEOUT_SECONDS)
        repair_text, error = self._extract_review_text(response)
        if error:
            return []
        return self._parse_review_result(repair_text).get("atomic_comments") or []

    def _build_atomic_comments_from_section_prose(self, sections):
        comments = []
        issue_language = re.compile(
            r"\b(missing|absent|undefined|unclear|ambiguous|inconsistent|conflict|confusion|gap|risk|"
            r"fail(?:s|ed|ure)?|unapproved|incomplete|insufficient|incorrect|lacks?|should|however)\b|"
            r"\b(?:no|not)\s+(?:clear|defined|specified|provided|identified|documented|traceable|consistent)\b",
            re.IGNORECASE,
        )
        pass_language = re.compile(r"\b(no|none)\s+(?:actionable\s+)?(?:issues|findings|concerns)\b", re.IGNORECASE)
        for section in sections:
            if self._is_atomic_comments_summary_section(section):
                continue
            title = str(section.get("title") or "Review")
            sentences = [
                sentence.strip(" -\t")
                for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(section.get("content") or ""))
                if sentence.strip(" -\t")
            ]
            for sentence in sentences:
                if pass_language.search(sentence) or not issue_language.search(sentence):
                    continue
                comments.append({
                    "id": f"A{len(comments) + 1}",
                    "location": "Target location not specified",
                    "violated_rule": "Not found in provided reference material",
                    "rule_evidence": "",
                    "issue": sentence[:240],
                    "comment": f"{title}: {sentence}",
                    "suggested_resolution": "Update the target document to resolve this issue and provide objective supporting evidence.",
                })
        return comments

    def _extract_json_value(self, text):
        cleaned = str(text or "").strip().lstrip("\ufeff")
        if not cleaned:
            return None

        candidates = [cleaned]
        candidates.extend(
            match.group(1).strip()
            for match in re.finditer(r"```(?:json)?\s*(.*?)```", cleaned, re.IGNORECASE | re.DOTALL)
        )
        without_thinking = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
        if without_thinking and without_thinking not in candidates:
            candidates.append(without_thinking)

        for candidate in candidates:
            decoded = self._decode_json_candidate(candidate)
            if decoded is not None:
                return decoded

        decoder = json.JSONDecoder()
        for candidate in candidates:
            for index, character in enumerate(candidate):
                if character not in "{[":
                    continue
                try:
                    decoded, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, str):
                    decoded = self._decode_json_candidate(decoded)
                if decoded is not None:
                    return decoded
        return None

    def _decode_json_candidate(self, candidate):
        value = candidate
        for _ in range(3):
            if not isinstance(value, str):
                return value
            try:
                value = json.loads(value.strip())
            except (json.JSONDecodeError, TypeError):
                return None
        return value

    def _format_review_value(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            nested = self._decode_json_candidate(value)
            return self._format_review_value(nested) if nested is not None and nested != value else value.strip()
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            blocks = []
            for item in value:
                formatted = self._format_review_value(item)
                if formatted:
                    blocks.append(formatted if "\n" in formatted else f"- {formatted}")
            return "\n\n".join(blocks)
        if isinstance(value, dict):
            finding = self._format_structured_finding(value)
            if finding:
                return finding
            lines = []
            for key, item in value.items():
                formatted = self._format_review_value(item)
                if not formatted:
                    continue
                label = str(key).replace("_", " ").strip().capitalize()
                lines.append(f"{label}: {formatted}" if "\n" not in formatted else f"{label}:\n{formatted}")
            return "\n".join(lines)
        return str(value)

    def _format_structured_finding(self, finding):
        finding_keys = {
            "location", "issue", "problem", "violated_rule", "rule_violated", "applicable_rule",
            "rule", "rule_evidence", "evidence", "comment", "details", "suggested_resolution",
            "target_fix", "resolution", "fix",
        }
        if not finding_keys.intersection(finding):
            return ""
        fields = (
            ("Location", finding.get("location")),
            ("Rule violated", finding.get("violated_rule") or finding.get("rule_violated") or finding.get("applicable_rule") or finding.get("rule")),
            ("Rule evidence", finding.get("rule_evidence") or finding.get("rule_reference")),
            ("Issue", finding.get("issue") or finding.get("problem") or finding.get("title")),
            ("Evidence", finding.get("evidence") or finding.get("comment") or finding.get("details")),
            ("Target fix", finding.get("suggested_resolution") or finding.get("target_fix") or finding.get("resolution") or finding.get("fix")),
        )
        return "\n".join(
            f"{label}: {self._format_review_value(item)}"
            for label, item in fields
            if item not in (None, "")
        )

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
        field_matches = list(re.finditer(
            r"(?im)^\s*(?:(?:[-*]|\d+[\).])\s*)?(Location|Issue):\s*",
            content,
        ))
        block_starts = []
        current_has_issue = False
        for match in field_matches:
            field_name = match.group(1).lower()
            if field_name == "location":
                block_starts.append(match.start())
                line_end = content.find("\n", match.end())
                line_end = len(content) if line_end < 0 else line_end
                current_has_issue = bool(re.search(r"\bIssue:\s*", content[match.end():line_end], re.IGNORECASE))
            elif not block_starts or current_has_issue:
                block_starts.append(match.start())
                current_has_issue = True
            else:
                current_has_issue = True

        for index, start in enumerate(block_starts):
            end = block_starts[index + 1] if index + 1 < len(block_starts) else len(content)
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
        first_issue_match = re.match(r"(?i)(?:(?:[-*]|\d+[\).])\s*)?Issue:\s*(.+)$", first_line)
        if first_issue_match:
            issue_text = first_issue_match.group(1).strip()
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
            re.sub(r"(?i)^(evidence|comment|details):\s*", "", line).strip()
            for line in lines[1:]
            if not re.match(r"(?i)target fix:|suggested resolution:|rule violated:|violated rule:|applicable rule:|rule:|rule evidence:|reference evidence:|rule text:|issue:", line)
        ]
        fix_lines = [
            re.sub(r"(?i)^(target fix|suggested resolution):\s*", "", line).strip()
            for line in lines[1:]
            if re.match(r"(?i)target fix:|suggested resolution:", line)
        ]

        return {
            "location": self._normalize_location_label(location_text) or "Target location not specified",
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
                return "section document-level content"
            return match.group(0)

        return re.sub(r"(?i)section\s+Document\s+([^|,]+)", replace_match, text, count=1)

    def _normalize_rule_label(self, rule):
        text = self._normalize_location_label(rule)
        if not text:
            return "Not found in provided reference material"
        return text

