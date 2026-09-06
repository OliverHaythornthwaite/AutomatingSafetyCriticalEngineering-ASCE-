import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from document_processing import DocumentProcessingMixin  # noqa: E402


class DocumentProcessor(DocumentProcessingMixin):
    @staticmethod
    def _normalize_requirement_id(requirement_id):
        return requirement_id.upper().replace("_", "-").replace(" ", "-")


class DocumentProcessingTests(unittest.TestCase):
    def setUp(self):
        self.processor = DocumentProcessor()

    def test_plain_text_upload_preserves_document_identity(self):
        document, error = self.processor._extract_uploaded_document(
            {
                "name": "requirements.txt",
                "document_id": "target-1",
                "content": "LLR-001 The controller shall stop.",
            },
            "target",
        )

        self.assertEqual("", error)
        self.assertEqual("target-1", document["document_id"])
        self.assertIn("LLR-001", document["content"])

    def test_invalid_base64_is_reported_without_raising(self):
        document, error = self.processor._extract_uploaded_document(
            {"name": "requirements.txt", "data_base64": "not base64"},
            "target",
        )

        self.assertIsNone(document)
        self.assertEqual("requirements.txt could not be decoded.", error)

    def test_chunk_provenance_tracks_heading_and_requirement(self):
        chunks = self.processor._chunk_documents(
            [{"name": "requirements.md", "content": "# Shutdown\nLLR-001 The controller shall stop."}],
            "TARGET",
        )

        self.assertIn("section Shutdown | heading", chunks[0])
        self.assertIn("section Shutdown | requirement LLR-001", chunks[1])


if __name__ == "__main__":
    unittest.main()
