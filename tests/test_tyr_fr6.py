import unittest

from backend.agents.tyr import arbitrate_contract_finding, arbitrate_contract_review


class TyrFR6Tests(unittest.TestCase):
    def test_ruling_reconciles_loki_and_heimdall_with_rationale_and_confidence(self):
        finding = {
            "id": "A1:notice:1", "category": "notice_obligation",
            "title": "Incident notice timing", "claim": "Notice may have been late",
            "severity": "high", "likelihood": "elevated",
            "citations": [{"document_id": "A1", "clause_reference": "Section 9",
                           "quote": "Provider shall give written notice within 4 hours."}],
            "evidence_gaps": [],
        }
        verification = {
            "status": "verified_with_limitations",
            "citation_results": [{"document_id": "A1", "clause_reference": "Section 9",
                                  "quote": "Provider shall give written notice within 4 hours.",
                                  "verified": True}],
            "supports": ["The exact clause quotation exists in the source."],
            "challenges": ["Event association does not establish breach."],
            "mapped_events": [{"event_id": "EV-1", "timestamp": "2027-03-14",
                               "body": "Incident notice was recorded after the outage."}],
            "evidence_gaps": ["Confirm notice delivery timestamp."],
        }
        ruling = arbitrate_contract_finding("A1", finding, verification)
        self.assertEqual(ruling["decision"], "partially_supported_unresolved")
        self.assertTrue(ruling["rationale"])
        self.assertGreater(ruling["confidence"], 0)
        self.assertIn("loki_claim", ruling["disagreement"])
        self.assertIn("heimdall_challenges", ruling["disagreement"])
        self.assertTrue(ruling["human_approval_required"])
        self.assertEqual(ruling["approval_status"], "pending_human_approval")

    def test_unverified_citation_blocks_confident_notice_and_is_visible_in_draft(self):
        finding = {
            "id": "B1:notice:2", "category": "notice_obligation",
            "title": "Notice issue", "claim": "Potential notice failure",
            "citations": [{"document_id": "B1", "clause_reference": "Section 4",
                           "quote": "This quote is not canonical."}],
        }
        verification = {
            "citation_results": [{"document_id": "B1", "clause_reference": "Section 4",
                                  "quote": "This quote is not canonical.", "verified": False}],
            "supports": [], "challenges": ["Quote failed verification."],
            "mapped_events": [], "evidence_gaps": [],
        }
        ruling = arbitrate_contract_finding("B1", finding, verification)
        self.assertEqual(ruling["decision"], "challenged_insufficient_citation_evidence")
        self.assertEqual(ruling["confidence_label"], "low")
        self.assertIn("UNVERIFIED", ruling["action_draft"]["body"])
        self.assertIn("BLOCKER", ruling["action_draft"]["body"])
        self.assertTrue(ruling["action_draft"]["human_approval_required"])
        self.assertEqual(ruling["action_draft"]["status"], "draft_only_not_sent")

    def test_action_drafting_covers_renewal_termination_amendment_and_escalation(self):
        cases = [
            ("renewal", "renewal_notice"),
            ("termination", "termination_notice"),
            ("security_incident", "potential_breach_notice"),
            ("ambiguity", "amendment_proposal"),
            ("penalty_or_interest", "escalation_memo"),
        ]
        for category, expected_type in cases:
            with self.subTest(category=category):
                finding = {
                    "id": "A1:" + category, "category": category, "title": category,
                    "citations": [{"document_id": "A1", "clause_reference": "Section 7",
                                   "quote": "Written notice must be provided.", "verified": True}],
                }
                verification = {
                    "citation_results": [{"document_id": "A1", "clause_reference": "Section 7",
                                          "quote": "Written notice must be provided.", "verified": True}],
                    "supports": [], "challenges": [], "mapped_events": [],
                    "evidence_gaps": ["Confirm notice recipient."],
                }
                ruling = arbitrate_contract_finding("A1", finding, verification)
                draft = ruling["action_draft"]
                self.assertEqual(draft["type"], expected_type)
                self.assertIn("Section 7", draft["body"])
                self.assertIn("Written notice must be provided.", draft["body"])
                self.assertTrue(draft["human_approval_required"])
                self.assertEqual(draft["approval_status"], "pending_human_approval")
                self.assertEqual(draft["consequential_action_executed"], False)

    def test_review_matches_each_heimdall_record_to_loki_finding(self):
        finding = {"id": "C1:risk:1", "category": "renewal", "claim": "Renewal exposure",
                   "citations": [{"document_id": "C1", "clause_reference": "Section 2",
                                  "quote": "Renews automatically."}]}
        result = arbitrate_contract_review("C1", [finding], {"findings": [{
            "finding_id": "C1:risk:1", "citation_results": [{
                "document_id": "C1", "clause_reference": "Section 2",
                "quote": "Renews automatically.", "verified": True}],
            "supports": [], "challenges": [], "mapped_events": [], "evidence_gaps": [],
        }]})
        self.assertEqual(len(result["rulings"]), 1)
        self.assertEqual(result["rulings"][0]["finding_id"], "C1:risk:1")
        self.assertEqual(result["summary"]["actions_pending_approval"], 1)


if __name__ == "__main__":
    unittest.main()
