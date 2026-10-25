import unittest
from backend.services.upload_analysis import extract_document_terms

class UploadAnalysisTests(unittest.TestCase):
    def test_only_returns_verbatim_source_excerpts(self):
        source = "Section 4. Payment\nCustomer shall pay the monthly fee within 30 days of invoice."
        result = extract_document_terms(source, "B2")
        self.assertGreaterEqual(len(result["extracted_terms"]), 1)
        for term in result["extracted_terms"]:
            self.assertIn(term["citation"]["quote"], source)
            self.assertEqual(term["citation"]["document_id"], "B2")

    def test_irrelevant_text_does_not_create_contract_claims(self):
        result = extract_document_terms("The sky is blue. A quiet garden.", "other.txt")
        self.assertEqual(result["extracted_terms"], [])

if __name__ == "__main__":
    unittest.main()
