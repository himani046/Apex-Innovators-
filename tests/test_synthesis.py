import unittest
from backend.services.synthesis import build_synthesis


class SynthesisTests(unittest.TestCase):
    def test_builds_contract_reports_and_company_report_without_inventing_exposure(self):
        run = {
            "as_of_date": "2027-03-15",
            "scope": "test portfolio",
            "portfolio_extraction": {
                "contracts": {
                    "A1": {"extracted_terms": [
                        {"category": "renewal", "confidence": 0.65, "citation": {
                            "document_id": "A1", "clause_reference": "Section 2",
                            "quote": "This Agreement renews annually.", "verified": True
                        }}
                    ]},
                    "B1": {"extracted_terms": []},
                }
            },
            "workstream_analysis": {"workstreams": [], "portfolio_summary": {"potential_exclusivity_overlap": []}},
            "portfolio_operations": {"timeline": {"milestones": []},
                                     "financial_reconciliation": {"status": "needs_review"}},
            "decision_queue": {"issues": []},
            "contract_graph": {"nodes": [], "edges": []},
            "contract_reconciliation": {"resolved_changes": [], "review_items": []},
            "evidence_grounded_finding": {"contract_id": "A1", "missing_evidence": ["Notice timestamp"]},
            "ruling": {},
            "timeline": {"milestones": [], "worst_case_note": "Not calculated."},
            "collaboration": {"unresolved_questions": ["Notice timestamp"]},
        }
        result = build_synthesis(run)
        self.assertEqual(len(result["contract_reports"]), 2)
        self.assertEqual(result["contract_reports"][0]["contract_id"], "A1")
        self.assertIsNone(result["company_risk_report"]["total_financial_exposure"])
        self.assertIn("Notice timestamp", result["company_risk_report"]["unresolved_questions"])


if __name__ == "__main__":
    unittest.main()
