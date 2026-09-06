"""Document decoding, extraction, and provenance-aware chunking.

This module deliberately uses only the Python standard library.  The mixin keeps
document-format concerns separate from HTTP routing and review orchestration while
preserving the handler's existing private API.
"""

import base64
import binascii
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path


WORD_EXTENSIONS = {".docx", ".docm", ".dotx", ".dotm"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls"}
SCADE_XML_EXTENSIONS = {".xscade", ".etp", ".sgfx", ".pgfx", ".ogfx", ".dgfx", ".sdfx", ".rgfx"}
SCADE_TEXT_EXTENSIONS = {".scade", ".sss", ".in", ".sns", ".out", ".obs"}

REQUIREMENT_ID_PATTERN = re.compile(
    r"\b(?:"
    r"DCDS-[A-Z0-9]+-(?:SRATS|SR|HLR|LLR|LLRV)-\d+[A-Z]?"
    r"|(?:SRATS|SRAT|SR|SYS|SRS|HLR|LLR|LLRV|REQ|REQT|SWREQ|SWR)[-_ ]?\d+(?:[.\-_]\d+)*[A-Z]?"
    r"|[A-Z]{2,8}-\d{2,5}(?:[.\-_][A-Z0-9]+)*"
    r")\b",
    re.IGNORECASE,
)


class DocumentProcessingMixin:
    """Add document ingestion behavior to the application request handler."""

    def _collect_reference_documents(self, reference_document_entries=None):
        documents, _ = self._extract_uploaded_documents(reference_document_entries or [], "reference")
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
        document_id = str(entry.get("document_id") or "").strip()
        document_metadata = {"document_id": document_id} if document_id else {}
        encoded_content = entry.get("data_base64") or ""
        if encoded_content:
            try:
                raw_content = base64.b64decode(encoded_content, validate=True)
            except (binascii.Error, ValueError):
                return None, f"{name} could not be decoded."
            content = self._extract_document_bytes(name, raw_content)
            if content:
                return {"name": name, "content": content, **document_metadata}, ""
            return None, f"{name} could not be read as a supported document."

        content = (entry.get("content") or "").strip()
        if content:
            suffix = Path(name).suffix.lower()
            if suffix in WORD_EXTENSIONS | EXCEL_EXTENSIONS:
                return None, f"{name} is an Office document, but the upload did not include binary content. Re-add the file and try again."
            return {"name": name, "content": content, **document_metadata}, ""

        return None, f"{name} did not contain readable text."

    def _extract_document_bytes(self, name, raw_content):
        suffix = Path(name).suffix.lower()
        if suffix in WORD_EXTENSIONS:
            return self._extract_docx_text(raw_content)
        if suffix in EXCEL_EXTENSIONS:
            return self._extract_xlsx_text(raw_content)
        if suffix in LEGACY_OFFICE_EXTENSIONS:
            return self._extract_legacy_doc_text(raw_content)
        if suffix in SCADE_XML_EXTENSIONS:
            return self._extract_scade_xml_text(name, raw_content)
        if suffix in SCADE_TEXT_EXTENSIONS:
            return self._extract_scade_text(name, raw_content)

        return self._decode_text_bytes(raw_content)

    @staticmethod
    def _decode_text_bytes(raw_content):
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
            try:
                return raw_content.decode(encoding).strip()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return ""

    def _extract_scade_text(self, name, raw_content):
        content = self._decode_text_bytes(raw_content)
        if not content:
            return ""
        suffix = Path(name).suffix.lower().lstrip(".").upper()
        return f"[SCADE {suffix} document: {name}]\n{content}"

    def _extract_scade_xml_text(self, name, raw_content):
        try:
            root = ET.fromstring(raw_content)
        except (ET.ParseError, ValueError):
            content = self._decode_text_bytes(raw_content)
            if not content:
                return ""
            suffix = Path(name).suffix.lower().lstrip(".").upper()
            return f"[SCADE {suffix} document: {name}]\n{content}"

        suffix = Path(name).suffix.lower().lstrip(".").upper()
        lines = [f"[SCADE {suffix} structured model: {name}]"]

        def local_name(value):
            return value.rsplit("}", 1)[-1] if "}" in value else value

        def visit(element, depth=0):
            attributes = []
            for key, value in element.attrib.items():
                normalized = " ".join(str(value).split())
                attributes.append(f"{local_name(key)}={json.dumps(normalized, ensure_ascii=False)}")
            text = " ".join((element.text or "").split())
            details = " " + " ".join(attributes) if attributes else ""
            if text:
                details += f" text={json.dumps(text, ensure_ascii=False)}"
            lines.append(f"{'  ' * depth}{local_name(element.tag)}{details}")
            for child in element:
                visit(child, depth + 1)

        visit(root)
        return "\n".join(lines)

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

    @staticmethod
    def _extract_word_xml_text(xml_content):
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

    @staticmethod
    def _read_xlsx_shared_strings(archive):
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

    @staticmethod
    def _read_xlsx_sheet_names(archive):
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

    @staticmethod
    def _extract_xlsx_cell_value(cell, shared_strings):
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

    @staticmethod
    def _extract_legacy_doc_text(raw_content):
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
            current_section = "Document overview"
            explicit_pages = re.split(r"\f+", content)
            paragraph_counter = 0

            for page_content in explicit_pages:
                paragraphs = self._split_document_blocks(page_content)

                for paragraph in paragraphs:
                    paragraph_counter += 1
                    section_heading = self._section_heading_label(paragraph)
                    if section_heading:
                        current_section = section_heading

                    detail_label = self._location_detail_label(paragraph, paragraph_counter, bool(section_heading))
                    location = f"{role_label}: {name} | section {current_section} | {detail_label}"
                    if len(paragraph) > 1800:
                        sub_paragraphs = re.split(r"(?<=[.;:])\s+", paragraph)
                        for sub_paragraph in sub_paragraphs:
                            if sub_paragraph.strip():
                                chunks.append(f"[{location}] {sub_paragraph.strip()}")
                    else:
                        chunks.append(f"[{location}] {paragraph}")
        return chunks

    @staticmethod
    def _split_document_blocks(content):
        blocks = []
        for paragraph in re.split(r"\n\s*\n", content or ""):
            lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
            if not lines:
                continue
            # Extracted formats use a single newline between logical rows or
            # paragraphs.  Preserve each one so provenance stays precise.
            blocks.extend(lines)
        return blocks

    def _looks_like_section_heading(self, paragraph):
        return bool(self._section_heading_label(paragraph))

    def _section_heading_label(self, paragraph):
        text = re.sub(r"\s+", " ", paragraph.strip())
        if not text or len(text) > 160 or "\n" in paragraph.strip():
            return ""
        if re.match(r"^Row\s+[A-Za-z0-9_.-]+:", text, re.IGNORECASE):
            return ""
        if REQUIREMENT_ID_PATTERN.match(text) or re.search(r"\b(shall|must|should|will|may|can)\b", text, re.IGNORECASE):
            return ""
        if re.match(r"^[A-Za-z][A-Za-z0-9_.-]*\s*=", text):
            return ""

        markdown_match = re.match(r"^#{1,6}\s+(.+?)\s*#*$", text)
        if markdown_match:
            return markdown_match.group(1).strip().rstrip(":")

        scade_header = re.match(r"^\[SCADE\s+([^\]]+?)\s+(?:structured model|document):", text, re.IGNORECASE)
        if scade_header:
            return f"SCADE {scade_header.group(1).upper()} structure"

        numbered_match = re.match(
            r"^((?:\d+(?:\.\d+)*|[A-Z])(?:[\).:\-]|\s))\s*(\S.+)$",
            text,
        )
        if numbered_match and len(numbered_match.group(2).split()) <= 14 and not re.search(r"[;!?]$", text):
            return text.rstrip(":")

        known_heading = re.match(
            r"^(Worksheet|Sheet|Table|Section|Chapter|Appendix|Requirements|Verification|Traceability|Scope|Purpose|Introduction|Conclusion|Summary|Overview|Definitions|References|Interfaces|Architecture|Design|Assumptions)(?:\s*:\s*|\s+)(\S.*)?$",
            text,
            re.IGNORECASE,
        )
        if known_heading:
            return text.rstrip(":")

        words = text.rstrip(":").split()
        letters = [word for word in words if re.search(r"[A-Za-z]", word)]
        is_uppercase = bool(letters) and text.upper() == text
        is_title_case = bool(letters) and all(
            word[0].isupper() or word.lower() in {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"}
            for word in letters
        )
        if len(words) <= 12 and not re.search(r"[.;!?]$", text) and (is_uppercase or is_title_case or text.endswith(":")):
            return text.rstrip(":")
        return ""

    def _location_detail_label(self, paragraph, paragraph_counter, is_heading=False):
        if is_heading:
            return "heading"
        row_match = re.match(r"^Row\s+([A-Za-z0-9_.-]+):", paragraph.strip(), re.IGNORECASE)
        if row_match:
            return f"row {row_match.group(1)}"
        requirement_match = REQUIREMENT_ID_PATTERN.match(paragraph.strip())
        if requirement_match:
            return f"requirement {self._normalize_requirement_id(requirement_match.group(0))}"
        return f"paragraph {paragraph_counter}"

    @staticmethod
    def _build_complete_target_context(target_chunks):
        if not target_chunks:
            return "No target document content was available."
        return "\n\n".join(target_chunks)
