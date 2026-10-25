import unittest

from backend.services.decision_engine import build_decision_queue


class DecisionQueueTests(unittest.TestCase):
    def test_only_explicit_action_deadlines_can_be_overdue(self):
        operations = {
            "as_of_date": "2027-03-15",
            "timeline": {"milestones": [
                {"contract_id": "A1", "date": "2026-08-01", "title": "Effective Date: August 1, 2026",
                 "date_type": "historical_reference", "action_required_by_date": False,
                 "status": "past_reference", "evidence": {"verified": True}},
                {"contract_id": "D1", "date": "2027-02-28", "title": "Due Date: February 28, 2027",
                 "date_type": "action_deadline", "action_required_by_date": True,
                 "status": "overdue", "evidence": {"verified": True}},
            ]},
            "financial_reconciliation": {"payment_ledger_candidates": []},
        }
        result = build_decision_queue(operations, {"workstreams": []})
        self.assertEqual(result["counts"]["high"], 1)
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["issues"][0]["category"], "contract_deadline")
        self.assertTrue(result["issues"][0]["human_review_required"])

    def test_unlinked_ledger_row_is_prioritized_without_claiming_loss(self):
        operations = {
            "as_of_date": "2027-03-15",
            "timeline": {"milestones": []},
            "financial_reconciliation": {"payment_ledger_candidates": [
                {"event_id": "ledger-1", "event_source": "payments_ledger.csv",
                 "timestamp": "2027-03-01", "summary": "Unknown invoice",
                 "payment_status": "paid", "transaction_signal": "paid",
                 "contract_id": None, "contract_match_status": "ambiguous_or_missing_contract_reference",
                 "amounts_found": ["$ 100.00"], "evidence_text": "source row"}
            ]},
        }
        result = build_decision_queue(operations, {"workstreams": []})
        self.assertEqual(result["counts"]["medium"], 1)
        self.assertEqual(result["issues"][0]["status"], "contract_link_unresolved")
        self.assertIn("not legal", result["notice"].lower())
        self.assertTrue(result["issues"][0]["human_review_required"])


if __name__ == "__main__":
    unittest.main()
