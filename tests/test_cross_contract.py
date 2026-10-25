import unittest

from backend.agents.cross_contract import detect_cross_contract_candidates


class CrossContractCandidateTests(unittest.TestCase):
    def test_numeric_difference_is_candidate_with_both_citations(self):
        contracts = {
            "SUPPLIER_A": "Section 4\nSupplier shall notify within 4 hours.",
            "SUPPLIER_B": "Section 7\nSupplier shall notify within 24 hours.",
        }
        found = detect_cross_contract_candidates(contracts)
        self.assertTrue(found)
        item = found[0]
        self.assertEqual(item["contract_ids"], ["SUPPLIER_A", "SUPPLIER_B"])
        self.assertEqual(len(item["citations"]), 2)
        self.assertTrue(all(c["verified"] for c in item["citations"]))
        self.assertEqual(item["status"], "candidate_requires_human_review")
        self.assertTrue(item["human_review_required"])

    def test_opposite_modality_is_flagged_without_claiming_legal_conflict(self):
        contracts = {
            "A": "Section 1\nThe supplier must provide exclusive service.",
            "B": "Section 2\nThe supplier may provide non-exclusive service.",
        }
        found = detect_cross_contract_candidates(contracts)
        self.assertTrue(found)
        self.assertIn("not a legal conflict determination", found[0]["notice"].lower())

    def test_same_contract_does_not_create_cross_contract_candidate(self):
        contracts = {"A": "Notify within 4 hours.\nNotify within 24 hours."}
        self.assertEqual(detect_cross_contract_candidates(contracts), [])

    def test_unrelated_contracts_return_no_candidate(self):
        contracts = {"A": "Supplier will provide the service.", "B": "The customer owns all equipment."}
        self.assertEqual(detect_cross_contract_candidates(contracts), [])


if __name__ == "__main__":
    unittest.main()
