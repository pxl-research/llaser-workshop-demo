import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from AI.API import documents
from AI.API.exceptions import DocumentProcessingError


class ProcessUploadedDocumentsTests(unittest.TestCase):
    def test_processes_only_the_uploaded_file(self):
        upload_dir = Path("data")
        upload_dir.mkdir(exist_ok=True)
        existing = upload_dir / "existing.txt"
        uploaded = upload_dir / "new.txt"
        existing.write_text("old")
        uploaded.write_text("new")

        system = MagicMock()
        system.process_and_add_document.return_value = {
            "status": "success",
            "chunks": 2,
        }

        result = documents.process_uploaded_documents(
            system=system,
            uploaded_file_path=uploaded,
            uploaded_size=3,
        )

        system.process_and_add_document.assert_called_once_with(file_path=str(uploaded))
        self.assertEqual(result["filename"], "new.txt")
        self.assertEqual(result["chunks"], 2)
        self.assertEqual(result["message"], "Uploaded and indexed new.txt (2 chunks).")
        self.assertFalse(result["already_indexed"])
        self.assertNotIn("loader_used", result)
        self.assertTrue(uploaded.exists())

    def test_reports_already_indexed_without_chunk_count(self):
        upload_dir = Path("data")
        upload_dir.mkdir(exist_ok=True)
        uploaded = upload_dir / "existing.txt"
        uploaded.write_text("old")

        system = MagicMock()
        system.process_and_add_document.return_value = {
            "status": "success",
            "chunks": 0,
            "already_indexed": True,
        }

        result = documents.process_uploaded_documents(
            system=system,
            uploaded_file_path=uploaded,
            uploaded_size=3,
        )

        self.assertTrue(result["already_indexed"])
        self.assertEqual(result["chunks"], 0)
        self.assertEqual(result["message"], "existing.txt is already indexed.")

    def test_raises_when_processing_fails(self):
        upload_dir = Path("data")
        upload_dir.mkdir(exist_ok=True)
        uploaded = upload_dir / "broken.pdf"
        uploaded.write_bytes(b"%PDF")

        system = MagicMock()
        system.process_and_add_document.return_value = {
            "status": "error",
            "message": DocumentProcessingError.SPLIT_FAILED,
        }

        with self.assertRaises(DocumentProcessingError) as raised:
            documents.process_uploaded_documents(
                system=system,
                uploaded_file_path=uploaded,
                uploaded_size=10,
            )
        self.assertEqual(raised.exception.user_message, DocumentProcessingError.SPLIT_FAILED)
        self.assertFalse(uploaded.exists())

    def test_removes_the_uploaded_file_when_processing_raises(self):
        upload_dir = Path("data")
        upload_dir.mkdir(exist_ok=True)
        uploaded = upload_dir / "broken.pdf"
        uploaded.write_bytes(b"%PDF")

        system = MagicMock()
        system.process_and_add_document.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            documents.process_uploaded_documents(
                system=system,
                uploaded_file_path=uploaded,
                uploaded_size=10,
            )
        self.assertFalse(uploaded.exists())

    def test_replaces_uncurated_failure_message_with_generic_one(self):
        upload_dir = Path("data")
        upload_dir.mkdir(exist_ok=True)
        uploaded = upload_dir / "broken.pdf"

        for result in (
            {"status": "error", "message": "failed on /app/data/secret.pdf with sk-or-XXXX"},
            {"status": "error"},
            "not a dict",
        ):
            uploaded.write_bytes(b"%PDF")
            system = MagicMock()
            system.process_and_add_document.return_value = result

            with self.assertRaises(DocumentProcessingError) as raised:
                documents.process_uploaded_documents(
                    system=system,
                    uploaded_file_path=uploaded,
                    uploaded_size=10,
                )
            self.assertEqual(raised.exception.user_message, DocumentProcessingError.GENERIC)
            self.assertNotIn("secret.pdf", str(raised.exception))
            self.assertNotIn("sk-or-XXXX", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
