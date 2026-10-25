import unittest
from backend.services.document_upload import DocumentUploadError, extract_uploaded_document

class DocumentUploadTests(unittest.TestCase):
    def test_txt_upload_preserves_source_and_hash(self):
        result = extract_uploaded_document("A1.txt", b"Section 1. Notice within four hours.")
        self.assertEqual(result["format"], "TXT")
        self.assertEqual(result["filename"], "A1.txt")
        self.assertIn("four hours", result["text"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(DocumentUploadError):
            extract_uploaded_document("contract.docx", b"not supported")

    def test_rejects_empty_file(self):
        with self.assertRaises(DocumentUploadError):
            extract_uploaded_document("empty.txt", b"")

    def test_rejects_oversized_file(self):
        with self.assertRaises(DocumentUploadError):
            extract_uploaded_document("large.txt", b"x" * (15 * 1024 * 1024 + 1))

if __name__ == "__main__":
    unittest.main()
