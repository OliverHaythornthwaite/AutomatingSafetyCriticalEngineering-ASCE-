"""In-memory reference indexing and relevance retrieval."""

import math
import re
import uuid
from collections import Counter

from app_config import (
    APPROX_CHARS_PER_TOKEN,
    MODEL_CONTEXT_LIMIT,
    REVIEW_MAX_CONTEXT,
    REVIEW_MAX_OUTPUT_TOKENS,
    REVIEW_MIN_CONTEXT,
    REVIEW_TEMPERATURE,
    REVIEW_TOP_P,
    RAG_LOCK,
    RAG_MAX_CHUNKS,
    RAG_MAX_CONTENT_CHARS,
    RAG_STORE,
)


class RetrievalMixin:
    """Manage reference documents and select relevant evidence."""

    def _get_rag_status(self):
        with RAG_LOCK:
            chunks = list(RAG_STORE["chunks"])
            documents_by_id = {}
            for chunk in chunks:
                source = chunk.get("source") or "knowledge"
                document_id = chunk.get("document_id") or f"source:{source}"
                document = documents_by_id.setdefault(
                    document_id,
                    {"document_id": document_id, "name": source, "chunk_count": 0, "token_count": 0, "chunks": []},
                )
                document["chunk_count"] += 1
                token_count = self._chunk_token_count(chunk.get("content") or "")
                document["token_count"] += token_count
                document["chunks"].append({
                    "id": str(chunk.get("id") or f"chunk-{document['chunk_count']}"),
                    "token_count": token_count,
                })
            return {
                "loaded": bool(chunks),
                "name": RAG_STORE["name"],
                "chunk_count": len(chunks),
                "source_count": len(documents_by_id),
                "documents": list(documents_by_id.values()),
                "token_count": sum(document["token_count"] for document in documents_by_id.values()),
                "retrieval_mode": "local TF-IDF",
            }

    def _clear_rag_content(self):
        global RAG_STORE
        with RAG_LOCK:
            RAG_STORE = {"name": "", "chunks": []}
        return {"ok": True, **self._get_rag_status()}

    def _remove_rag_documents(self, body):
        if not isinstance(body, dict) or not isinstance(body.get("document_ids"), list):
            return {"error": "Provide a list of RAG document IDs to remove."}
        document_ids = {
            str(document_id).strip()
            for document_id in body["document_ids"]
            if str(document_id).strip()
        }
        if not document_ids:
            return {"error": "Select at least one RAG document to remove."}

        global RAG_STORE
        with RAG_LOCK:
            existing_chunks = list(RAG_STORE["chunks"])
            removed_document_ids = {
                chunk.get("document_id")
                for chunk in existing_chunks
                if chunk.get("document_id") in document_ids
            }
            remaining_chunks = [
                chunk for chunk in existing_chunks if chunk.get("document_id") not in document_ids
            ]
            removed_chunks = len(existing_chunks) - len(remaining_chunks)
            RAG_STORE = {
                "name": RAG_STORE["name"] if remaining_chunks else "",
                "chunks": remaining_chunks,
            }
        status = self._get_rag_status()
        return {
            "ok": True,
            "removed_chunk_count": removed_chunks,
            "removed_document_count": len(removed_document_ids),
            **status,
        }

    def _load_rag_content(self, body):
        if not isinstance(body, dict):
            return {"error": "RAG content must be supplied as a JSON object."}

        append = bool(body.get("append"))
        if isinstance(body.get("store"), dict):
            result = self._normalize_reference_store(body["store"], body.get("name") or "Loaded reference store")
        elif isinstance(body.get("documents"), list):
            documents, errors = self._extract_uploaded_documents(body["documents"], "knowledge")
            if not documents:
                detail = f" {' '.join(errors[:3])}" if errors else ""
                return {"error": f"No readable knowledge documents were provided.{detail}"}
            result = self._build_rag_entries_from_documents(documents, body.get("name") or "Knowledge documents")
        else:
            return {"error": "Provide either a portable reference store or knowledge documents."}

        if result.get("error"):
            return result

        global RAG_STORE
        with RAG_LOCK:
            existing_chunks = list(RAG_STORE["chunks"]) if append else []
            combined_chunks = existing_chunks + result["chunks"]
            if len(combined_chunks) > RAG_MAX_CHUNKS:
                return {"error": f"The RAG store exceeds the {RAG_MAX_CHUNKS:,}-chunk safety limit."}
            if sum(len(chunk["content"]) for chunk in combined_chunks) > RAG_MAX_CONTENT_CHARS:
                return {"error": "The RAG store exceeds the 20,000,000-character safety limit."}
            RAG_STORE = {
                "name": result["name"] if not append or not RAG_STORE["name"] else RAG_STORE["name"],
                "chunks": combined_chunks,
            }
        return {"ok": True, **self._get_rag_status()}

    def _normalize_reference_store(self, store, default_name):
        raw_chunks = store.get("chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            return {"error": "The reference store must contain a non-empty 'chunks' array."}
        if len(raw_chunks) > RAG_MAX_CHUNKS:
            return {"error": f"The reference store exceeds the {RAG_MAX_CHUNKS:,}-chunk safety limit."}

        normalized = []
        source_document_ids = {}
        total_characters = 0
        for index, chunk in enumerate(raw_chunks, start=1):
            if not isinstance(chunk, dict):
                return {"error": f"Reference-store chunk {index} must be a JSON object."}
            content = str(chunk.get("content") or chunk.get("text") or "").strip()
            if not content:
                continue
            total_characters += len(content)
            if total_characters > RAG_MAX_CONTENT_CHARS:
                return {"error": "The reference store exceeds the 20,000,000-character safety limit."}

            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            source = str(chunk.get("source") or metadata.get("source") or metadata.get("document") or default_name).strip()
            chunk_id = str(chunk.get("id") or metadata.get("id") or f"chunk-{index}").strip()
            document_id = str(chunk.get("document_id") or metadata.get("document_id") or "").strip()
            if not document_id:
                document_id = source_document_ids.setdefault(source, f"store-{uuid.uuid4().hex}")
            normalized.append({
                "id": chunk_id,
                "document_id": document_id,
                "source": source,
                "content": content,
            })

        if not normalized:
            return {"error": "The reference store did not contain readable chunk content."}
        return {
            "name": str(store.get("name") or default_name).strip(),
            "chunks": normalized,
        }

    def _build_rag_entries_from_documents(self, documents, name):
        entries = []
        for document in documents:
            source = document.get("name") or str(name)
            document_id = str(document.get("document_id") or f"document-{uuid.uuid4().hex}").strip()
            chunks = self._chunk_documents([document], "KNOWLEDGE")
            for index, content in enumerate(chunks, start=1):
                entries.append({
                    "id": f"{document_id}-chunk-{index}",
                    "document_id": document_id,
                    "source": source,
                    "content": content,
                })
        return {"name": str(name), "chunks": entries}

    def _chunk_token_count(self, content):
        """Return a model-neutral token estimate for chunk visibility and budgeting."""
        text = str(content or "").strip()
        if not text:
            return 0
        lexical_tokens = len(re.findall(r"\w+|[^\w\s]", text, re.UNICODE))
        character_estimate = math.ceil(len(text) / APPROX_CHARS_PER_TOKEN)
        return max(1, round((lexical_tokens + character_estimate) / 2))

    def _resolve_review_context_window(self, body, model_context_limit=None):
        raw_value = body.get("context_window") if isinstance(body, dict) else None
        if raw_value in (None, ""):
            requested_context = max(REVIEW_MIN_CONTEXT, min(REVIEW_MAX_CONTEXT, MODEL_CONTEXT_LIMIT))
        else:
            try:
                requested_context = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Context window must be a whole number of tokens.") from exc
            if requested_context < REVIEW_MIN_CONTEXT or requested_context > REVIEW_MAX_CONTEXT:
                raise ValueError(
                    f"Context window must be between {REVIEW_MIN_CONTEXT:,} and {REVIEW_MAX_CONTEXT:,} tokens."
                )
        try:
            maximum_context = int(model_context_limit) if model_context_limit not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise ValueError("Model context limit must be a whole number of tokens.") from exc
        if maximum_context and requested_context > maximum_context:
            raise ValueError(
                f"The configured inference service supports at most {maximum_context:,} context tokens."
            )
        return requested_context

    def _build_review_model_options(self, prompt_length=0, context_window=None):
        requested_context = context_window or self._estimate_review_context_tokens(prompt_length)
        return {
            "temperature": REVIEW_TEMPERATURE,
            "top_p": REVIEW_TOP_P,
            "num_predict": REVIEW_MAX_OUTPUT_TOKENS,
        }

    def _estimate_review_context_tokens(self, prompt_length):
        prompt_tokens = max(1, int(prompt_length / APPROX_CHARS_PER_TOKEN))
        needed_tokens = prompt_tokens + REVIEW_MAX_OUTPUT_TOKENS + 1024
        rounded_tokens = ((needed_tokens + 2047) // 2048) * 2048
        return max(REVIEW_MIN_CONTEXT, min(REVIEW_MAX_CONTEXT, rounded_tokens))

    def _build_relevance_stepthrough(self, target_chunks, skills_prompt, review_goal, focus_limit=10):
        """Build a bounded, section-diverse retrieval query before composing the review prompt."""
        if not target_chunks:
            base_query = " ".join([skills_prompt, review_goal]).strip()
            return {
                "query": base_query,
                "comparison_text": "",
                "focus_chunks": [],
                "focus_locations": [],
            }

        ranked = self._score_retrieval_chunks(target_chunks, " ".join([skills_prompt, review_goal]))
        selected = []
        selected_indexes = set()
        selected_sections = set()

        def section_key(chunk):
            header = re.match(r"^\[([^\]]+)\]", chunk or "")
            location = header.group(1) if header else "Target location not specified"
            section_match = re.search(r"\|\s*section\s+([^|]+)", location, re.IGNORECASE)
            section = section_match.group(1).strip().lower() if section_match else location.lower()
            source = location.split("|", 1)[0].strip().lower()
            return f"{source}|{section}", location

        # First cover distinct document sections, then fill remaining slots by relevance.
        for _, index, chunk in ranked:
            key, location = section_key(chunk)
            if key in selected_sections:
                continue
            selected.append((index, chunk, location))
            selected_indexes.add(index)
            selected_sections.add(key)
            if len(selected) >= focus_limit:
                break
        if len(selected) < focus_limit:
            for _, index, chunk in ranked:
                if index in selected_indexes:
                    continue
                _, location = section_key(chunk)
                selected.append((index, chunk, location))
                if len(selected) >= focus_limit:
                    break

        focus_chunks = [chunk for _, chunk, _ in selected]
        focus_locations = [location for _, _, location in selected]
        # Keep the search query bounded; complete target content is still supplied to the final reviewer.
        comparison_text = "\n".join(chunk[:1200] for chunk in focus_chunks)
        return {
            "query": "\n".join([skills_prompt, review_goal, comparison_text]).strip(),
            "comparison_text": comparison_text,
            "focus_chunks": focus_chunks,
            "focus_locations": focus_locations,
        }

    def _retrieve_relevant_chunks(self, chunks, skills_prompt, review_goal, comparison_text="", limit=8, focus_chunks=None):
        query = " ".join([skills_prompt, review_goal, comparison_text])
        scored = self._score_staged_retrieval_chunks(chunks, query, focus_chunks or [])
        ranked = [chunk for _, _, chunk in scored]
        return ranked[:limit] if ranked else chunks[: min(3, limit)]

    def _score_staged_retrieval_chunks(self, chunks, query, focus_queries=None):
        """Fuse the overall query with small per-section searches so one long section cannot dominate."""
        base_scored = self._score_retrieval_chunks(chunks, query)
        if not base_scored or not focus_queries:
            return base_scored
        score_by_index = {index: score for score, index, _ in base_scored}
        candidate_pool = max(12, min(len(chunks), 48))
        for focus_query in focus_queries:
            for rank, (score, index, _) in enumerate(
                self._score_retrieval_chunks(chunks, focus_query)[:candidate_pool]
            ):
                score_by_index[index] = score_by_index.get(index, 0.0) + max(0.0, score) * 0.45
                score_by_index[index] += 0.12 / (rank + 1)
        return sorted(
            [(score_by_index.get(index, 0.0), index, chunk) for index, chunk in enumerate(chunks)],
            key=lambda item: (-item[0], item[1]),
        )

    def _score_retrieval_chunks(self, chunks, query):
        if not chunks:
            return []
        stop_words = {
            "the", "and", "for", "that", "with", "this", "from", "into", "only", "every", "each",
            "then", "than", "when", "where", "which", "while", "have", "has", "had", "are", "was",
            "were", "will", "would", "should", "could", "document", "documents", "target", "reference",
            "review", "reviewer", "content", "section", "complete", "supplied", "applicable",
        }

        def tokens(value):
            return [
                token.lower()
                for token in re.findall(r"[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*", value or "")
                if len(token) >= 3 and token.lower() not in stop_words
            ]

        query_counts = Counter(tokens(query))
        document_counts = [Counter(tokens(chunk)) for chunk in chunks]
        if not query_counts:
            return [(0.0, index, chunk) for index, chunk in enumerate(chunks)]

        document_frequency = Counter()
        for counts in document_counts:
            document_frequency.update(counts.keys())
        document_total = len(chunks)
        idf = {
            term: math.log((document_total + 1) / (document_frequency.get(term, 0) + 1)) + 1
            for term in query_counts
        }
        query_vector = {term: count * idf[term] for term, count in query_counts.items()}
        query_norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0

        scored = []
        for index, (chunk, counts) in enumerate(zip(chunks, document_counts)):
            dot_product = 0.0
            document_norm_squared = 0.0
            for term, count in counts.items():
                weight = count * idf.get(term, 0.0)
                if weight:
                    document_norm_squared += weight * weight
                    dot_product += weight * query_vector.get(term, 0.0)
            score = dot_product / (query_norm * math.sqrt(document_norm_squared)) if document_norm_squared else 0.0
            if re.search(r"\b(rule|shall|must|required|objective|standard|compliance|criterion|criteria)\b", chunk, re.IGNORECASE):
                score += 0.12
            if re.search(r"\b[A-Z]{2,10}[-_ ]?\d+(?:[.\-_]\d+)*[A-Z]?\b", chunk):
                score += 0.12
            scored.append((score, index, chunk))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored

    def _retrieve_rag_chunks(self, query, limit=24, focus_queries=None):
        with RAG_LOCK:
            store = {"chunks": [dict(chunk) for chunk in RAG_STORE["chunks"]]}
        if not store["chunks"]:
            return []

        formatted = [
            f"[RAG: {chunk['source']} | chunk {chunk['id']}] {chunk['content']}"
            for chunk in store["chunks"]
        ]
        scored = self._score_staged_retrieval_chunks(formatted, query, focus_queries or [])
        return [chunk for _, _, chunk in scored[:limit]]

    def _interleave_chunks(self, primary, secondary):
        interleaved = []
        for index in range(max(len(primary), len(secondary))):
            if index < len(primary):
                interleaved.append(primary[index])
            if index < len(secondary):
                interleaved.append(secondary[index])
        return interleaved

    def _calculate_retrieval_budget(self, target_characters, instruction_characters, context_window=None):
        effective_context_window = context_window or MODEL_CONTEXT_LIMIT
        maximum_input_tokens = max(1024, effective_context_window - REVIEW_MAX_OUTPUT_TOKENS - 2048)
        maximum_input_characters = maximum_input_tokens * APPROX_CHARS_PER_TOKEN
        prompt_overhead = instruction_characters + 14000
        return max(4000, maximum_input_characters - target_characters - prompt_overhead)

    def _select_chunks_with_budget(self, chunks, limit, character_budget):
        selected = []
        used_characters = 0
        for chunk in chunks:
            if len(selected) >= limit:
                break
            separator_size = 2 if selected else 0
            if selected and used_characters + separator_size + len(chunk) > character_budget:
                continue
            selected.append(chunk)
            used_characters += separator_size + len(chunk)
        return selected
