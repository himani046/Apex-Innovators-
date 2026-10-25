import unittest

from backend.config import PACK_DIR
from backend.services.contract_graph import build_contract_graph, reconcile_contracts
from backend.services.ingestion import load_pack
from backend.services.workstreams import build_workstreams
from backend.services.portfolio_operations import build_portfolio_operations


class PortfolioOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_pack(PACK_DIR)
        contracts = cls.pack["contracts"]
        graph = build_contract_graph(contracts)
        reconciliation = reconcile_contracts(contracts, graph)
        cls.workstreams = build_workstreams(
            contracts, graph, reconciliation, cls.pack["event_drops"], "2027-03-15"
        )
        cls.result = build_portfolio_operations(
            cls.workstreams, cls.pack["event_drops"], "2027-03-15", cls.pack["ledger"]
        )

    def test_timeline_is_normalized_and_counts_reconcile(self):
        timeline = self.result["timeline"]
        counts = timeline["counts"]
        self.assertEqual(counts["total"], len(timeline["milestones"]))
        self.assertEqual(counts["total"], counts["overdue"] + counts["due_today"] + counts["upcoming"] +
                         counts["historical_references"] + counts["contract_milestones"] +
                         counts["unclassified_dates"] + counts["relative_or_notice_terms"])
        self.assertTrue(all("date_type" in item and "action_required_by_date" in item
                            for item in timeline["milestones"]))
        self.assertTrue(all(item["status"] not in {"overdue", "due_today"} or item["action_required_by_date"]
                            for item in timeline["milestones"]))
        self.assertTrue(any(item["date_type"] == "historical_reference" for item in timeline["milestones"]))
        self.assertTrue(any(item["date_type"] == "action_deadline" and item["title"].lower().startswith("due date")
                            for item in timeline["milestones"]))
        for item in timeline["milestones"]:
            evidence = item["evidence"]
            self.assertTrue(evidence["verified"])
            self.assertIn(evidence["quote"], self.pack["contracts"][evidence["document_id"]])

    def test_financial_amounts_are_not_misrepresented_as_exposure(self):
        reconciliation = self.result["financial_reconciliation"]
        self.assertIsNone(reconciliation["portfolio_total_usd"])
        self.assertEqual(reconciliation["status"], "evidence_candidates_only")
        for amount in reconciliation["contract_amounts"]:
            self.assertEqual(amount["classification"], "contract_stated_amount_unreconciled")
            self.assertEqual(amount["ledger_effect"], "none_without_transaction_evidence")
            self.assertTrue(amount["evidence"]["verified"])

    def test_payment_candidates_require_explicit_linkage_and_human_review(self):
        reconciliation = self.result["financial_reconciliation"]
        counts = reconciliation["counts"]
        self.assertEqual(counts["transaction_candidates"], len(reconciliation["payment_ledger_candidates"]))
        for item in reconciliation["payment_ledger_candidates"]:
            self.assertTrue(item["human_review_required"])
            self.assertIn(item["contract_match_status"],
                          {"explicit_contract_reference", "explicit_document_id", "ambiguous_or_missing_contract_reference"})
            if item["contract_id"] is None:
                self.assertEqual(item["contract_match_status"], "ambiguous_or_missing_contract_reference")

    def test_payment_csv_rows_are_included_and_future_rows_excluded(self):
        reconciliation = self.result["financial_reconciliation"]
        ledger_rows = [item for item in reconciliation["payment_ledger_candidates"]
                       if item["event_source"] == "payments_ledger.csv"]
        self.assertGreater(len(ledger_rows), 0)
        self.assertTrue(all(item["timestamp"][:10] <= "2027-03-15" for item in ledger_rows))
        self.assertTrue(any(item["contract_id"] == "A1" for item in ledger_rows))
        self.assertTrue(any(item["payment_status"] == "paid" for item in ledger_rows))
        self.assertIsNone(reconciliation["portfolio_total_usd"])

    def test_invalid_as_of_date_is_rejected(self):
        with self.assertRaises(ValueError):
            build_portfolio_operations(self.workstreams, self.pack["event_drops"], "not-a-date")


if __name__ == "__main__":
    unittest.main()
