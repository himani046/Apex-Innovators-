import unittest

from backend.agents.norns import build_contract_timeline, build_timeline
from backend.agents.heimdall import verify_contract_review
from backend.agents.tyr import arbitrate_contract_finding
from backend.agents.thor_portfolio import extract_contract_candidates


class GeneralizedAgentTests(unittest.TestCase):
    def test_norns_does_not_assume_a1_dates_or_amounts(self):
        extraction = {
            "contract_id": "VENDOR_X",
            "extracted_terms": [{"category": "term", "citation": {
                "document_id": "VENDOR_X", "clause_reference": "Section 2",
                "quote": "Effective Date: January 15, 2027. The agreement expires on January 14, 2028.",
                "verified": True,
            }}],
        }
        result = build_timeline(extraction, "2027-03-15")
        self.assertEqual(result["contract_id"], "VENDOR_X")
        self.assertEqual(len(result["milestones"]), 2)
        self.assertIsNone(result["worst_case_projection"]["total_exposure"])
        self.assertNotIn("8000", str(result))

    def test_timeline_keeps_relative_notice_unresolved(self):
        extraction = {
            "contract_id": "VENDOR_X",
            "extracted_terms": [{"category": "renewal", "citation": {
                "document_id": "VENDOR_X", "clause_reference": "Section 4",
                "quote": "The agreement renews on January 14, 2028 unless 60 days' notice is delivered.",
                "verified": True,
            }}],
        }
        items = build_contract_timeline("VENDOR_X", extraction, "2027-03-15")
        relative = [item for item in items if "notice" in item["title"].casefold()]
        self.assertTrue(relative)
        self.assertTrue(all(item["actionable"] is False for item in relative))

    def test_loki_heimdall_tyr_preserve_uncertainty_and_rule_from_evidence(self):
        finding = {
            "id": "VENDOR_X:notice:10", "contract_id": "VENDOR_X",
            "category": "notice_obligation", "title": "Notice obligation",
            "claim": "A notice may have been late.", "evidence_gaps": ["Notice delivery timestamp"],
            "citations": [{"document_id": "VENDOR_X", "clause_reference": "Section 4",
                           "quote": "Supplier shall notify within four hours.", "verified": True}],
        }
        source = "Section 4\nSupplier shall notify within four hours."
        verification = verify_contract_review("VENDOR_X", source, [finding], [
            {"event_id": "E1", "contract_id": "VENDOR_X", "timestamp": "2027-02-01",
             "body": "VENDOR_X experienced an outage."}
        ])
        checked = verification["findings"][0]
        ruling = arbitrate_contract_finding("VENDOR_X", finding, checked)
        self.assertIn(ruling["decision"], {"partially_supported_unresolved", "insufficient_evidence"})
        self.assertTrue(ruling["human_approval_required"])
        self.assertEqual(ruling["action_draft"]["status"], "draft_only_not_sent")
        self.assertTrue(ruling["evidence_gaps"])

    def test_thor_marks_confidence_as_heuristic(self):
        source = "\n".join(f"Section {i}\nSupplier shall pay USD {i}.00." for i in range(1, 10))
        result = extract_contract_candidates("VENDOR_X", source, max_terms=3)
        self.assertTrue(all(t["confidence_type"] == "heuristic_uncalibrated" for t in result["extracted_terms"]))
        self.assertEqual(result["completeness"]["candidates_returned"], len(result["extracted_terms"]))


if __name__ == "__main__":
    unittest.main()
