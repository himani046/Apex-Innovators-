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

    def test_targeted_extraction_scans_only_requested_section(self):
        source = (
            "Section 1. Term\nThe agreement has a duration of twelve months.\n"
            "Section 4. Renewal\nThe agreement automatically renews for one year.\n"
            "Section 8. Payment\nCustomer shall pay USD 500 monthly.\n"
        )
        result = extract_document_terms(source, "VENDOR_X", "Section 4")
        self.assertEqual(result["mode"], "targeted_clause_scan")
        self.assertTrue(result["target_clause_found"])
        self.assertTrue(result["extracted_terms"])
        self.assertTrue(all("renew" in term["citation"]["quote"].casefold() for term in result["extracted_terms"]))
        self.assertTrue(all(term["citation"]["line_number"] == 4 for term in result["extracted_terms"]))

    def test_missing_targeted_section_does_not_fall_back_to_full_document(self):
        source = "Section 1. Term\nThe agreement has a duration of twelve months.\n"
        result = extract_document_terms(source, "VENDOR_X", "Section 99")
        self.assertFalse(result["target_clause_found"])
        self.assertEqual(result["extracted_terms"], [])
        self.assertIn("no whole-document fallback", result["summary"])

if __name__ == "__main__":
    unittest.main()
