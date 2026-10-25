import unittest

from backend.agents.thor_portfolio import extract_contract_candidates, extract_portfolio_candidates
from backend.config import PACK_DIR
from backend.services.ingestion import load_pack


class ThorPortfolioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_pack(PACK_DIR)

    def test_extracts_relevant_lines_with_verbatim_quotes(self):
        source = (
            "SECTION 4 — FEES\n"
            "Monthly Fee: $8,000 per month.\n"
            "Provider must notify Customer within four hours of awareness.\n"
        )
        result = extract_contract_candidates("TEST", source)
        self.assertGreaterEqual(len(result["extracted_terms"]), 2)
        for term in result["extracted_terms"]:
            citation = term["citation"]
            self.assertEqual(citation["document_id"], "TEST")
            self.assertIn(citation["quote"], source)
            self.assertTrue(citation["verified"])
            self.assertTrue(term["review_required"])

    def test_empty_document_is_reported_without_inventing_terms(self):
        result = extract_contract_candidates("EMPTY", "   \n")
        self.assertEqual(result["extracted_terms"], [])
        self.assertTrue(result["ambiguities"])

    def test_portfolio_extraction_covers_every_loaded_contract(self):
        result = extract_portfolio_candidates(self.pack["contracts"])
        self.assertEqual(set(result["contract_ids"]), set(self.pack["contracts"]))
        self.assertEqual(result["documents_processed"], len(self.pack["contracts"]))
        self.assertEqual(result["citation_validation"]["failed"], 0)
        for contract_id, contract_result in result["contracts"].items():
            for term in contract_result["extracted_terms"]:
                self.assertEqual(term["citation"]["document_id"], contract_id)
                self.assertTrue(term["citation"]["verified"])


if __name__ == "__main__":
    unittest.main()
