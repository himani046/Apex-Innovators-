import unittest

from backend.agents.loki import review_contract_candidates
from backend.services.portfolio_intelligence import review_cross_contract_candidates


class LokiFR4Tests(unittest.TestCase):
    def test_clause_review_includes_attack_path_scoring_and_source_citation(self):
        source = (
            "Section 8. Late Payment. If an invoice remains unpaid for 30 days, "
            "the customer shall pay a late fee of 5%."
        )
        result = review_contract_candidates("A1", source, {
            "extracted_terms": [{
                "category": "late_fee",
                "confidence": 0.97,
                "citation": {
                    "document_id": "A1", "clause_reference": "Section 8",
                    "quote": source, "verified": True,
                },
            }],
        })
        finding = next(item for item in result["findings"] if item["category"] == "penalty_or_interest")
        self.assertEqual(finding["severity"], "high")
        self.assertIn(finding["likelihood"], {"elevated", "moderate", "indeterminate"})
        self.assertTrue(finding["severity_rationale"])
        self.assertTrue(finding["likelihood_rationale"])
        self.assertGreaterEqual(len(finding["attack_path"]), 3)
        self.assertTrue(finding["citations"][0]["verified"])
        self.assertFalse(finding.get("breach_proven", False))

    def test_low_confidence_requests_targeted_thor_reextraction(self):
        source = "Section 4. Written notice must be given within 10 days."
        result = review_contract_candidates("A1", source, {
            "extracted_terms": [{
                "category": "notice",
                "confidence": 0.31,
                "citation": {
                    "document_id": "A1", "clause_reference": "Section 4",
                    "quote": source, "verified": True,
                },
            }],
        })
        finding = result["findings"][0]
        self.assertTrue(finding["requires_clarification"])
        self.assertEqual(finding["likelihood"], "indeterminate")
        self.assertTrue(any(item["to"] == "Thor" for item in result["clarification_requests"]))

    def test_cross_contract_review_emits_scoring_and_clarification_context(self):
        contracts = {
            "A": "Provider shall provide written notice within 4 hours after incident awareness.",
            "B": "Provider shall provide written notice within 24 hours after incident awareness.",
        }
        candidate = {
            "id": "notice:A:B", "topic": "notice", "classification": "numeric_term_difference",
            "severity": "high", "contract_ids": ["A", "B"],
            "explanation": "Different notice thresholds may apply.",
            "evidence": [
                {"document_id": "A", "line_number": 1, "quote": contracts["A"]},
                {"document_id": "B", "line_number": 1, "quote": contracts["B"]},
            ],
            "unresolved_questions": ["Confirm amendment precedence."],
            "amendment_resolution": {
                "status": "needs_review",
                "questions_to_resolve": ["Confirm amendment precedence."],
            },
        }
        result = review_cross_contract_candidates([candidate], contracts, [], "2027-03-15")
        loki = result["traces"][0]["loki_challenge"]
        self.assertIn(loki["likelihood"], {"elevated", "moderate", "indeterminate"})
        self.assertTrue(loki["severity_rationale"])
        self.assertGreaterEqual(len(loki["attack_path"]), 3)
        self.assertTrue(loki["requires_clarification"])
        self.assertFalse(loki["legal_conflict_determined"])


if __name__ == "__main__":
    unittest.main()
