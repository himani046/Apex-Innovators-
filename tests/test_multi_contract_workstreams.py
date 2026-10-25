import unittest

from backend.config import PACK_DIR
from backend.services.contract_graph import build_contract_graph, reconcile_contracts
from backend.services.ingestion import load_pack
from backend.services.workstreams import build_workstreams
from backend.orchestrator import run_demo


class MultiContractWorkstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_pack(PACK_DIR)
        cls.contracts = cls.pack["contracts"]
        cls.graph = build_contract_graph(cls.contracts)
        cls.reconciliation = reconcile_contracts(cls.contracts, cls.graph)
        cls.result = build_workstreams(
            cls.contracts, cls.graph, cls.reconciliation,
            cls.pack["event_drops"], "2027-03-15"
        )

    def test_creates_all_contract_and_portfolio_workstreams(self):
        ids = {item["id"] for item in self.result["workstreams"]}
        self.assertEqual(ids, {
            "contract-A1", "contract-B1", "contract-B2",
            "contract-C1", "contract-D1", "portfolio-wide",
        })
        self.assertEqual(self.result["portfolio_summary"]["workstream_count"], 5)

    def test_each_contract_workstream_uses_its_own_source(self):
        by_id = {item["id"]: item for item in self.result["workstreams"]}
        for doc_id in ("A1", "B1", "B2", "C1", "D1"):
            item = by_id[f"contract-{doc_id}"]
            self.assertIn(doc_id, item["contract_ids"])
            self.assertTrue(item["extracted_obligations"])
            for term in item["extracted_obligations"]:
                citation = term["citation"]
                source_doc = citation["document_id"]
                self.assertIn(source_doc, item["source_documents_analyzed"])
                self.assertIn(citation["quote"], self.contracts[source_doc])
                self.assertTrue(citation["verified"])

    def test_b2_is_its_own_dpa_workstream_and_links_to_b1(self):
        by_id = {item["id"]: item for item in self.result["workstreams"]}
        b2 = by_id["contract-B2"]
        self.assertTrue(any("Data Processing" in term["value"] or "Personal Data" in term["value"]
                            for term in b2["extracted_obligations"]))
        self.assertTrue(any(item["document_id"] == "B1" for item in b2["related_documents"]))

    def test_financial_amounts_are_source_grounded_not_falsely_aggregated(self):
        for item in self.result["workstreams"]:
            if item["id"] == "portfolio-wide":
                continue
            exposure = item["financial_exposure"]
            self.assertIsNone(exposure["calculated_total_usd"])
            for amount in exposure["amounts_found"]:
                self.assertTrue(amount["evidence"]["verified"])
                self.assertIn(amount["evidence"]["quote"], self.contracts[amount["evidence"]["document_id"]])

    def test_deadlines_are_explicit_dates_with_verified_evidence(self):
        for item in self.result["workstreams"]:
            for milestone in item["deadlines"]:
                self.assertTrue(milestone["evidence"]["verified"])
                self.assertIn(milestone["evidence"]["quote"], self.contracts[milestone["evidence"]["document_id"]])

    def test_portfolio_summary_flags_exclusivity_for_review_not_as_proven_conflict(self):
        portfolio = self.result["portfolio_summary"]
        self.assertIn("exclusivity-scope-review", [risk["signal_id"] for risk in portfolio["shared_risk_signals"]])
        self.assertTrue(all(action["human_approval_required"] for action in portfolio["recommended_actions"]))

    def test_orchestrator_returns_multi_contract_analysis(self):
        result = run_demo("2027-03-15", request_claude=False)
        self.assertEqual(len(result["workstream_analysis"]["workstreams"]), 6)
        self.assertEqual(result["portfolio_summary"]["workstream_count"], 5)
        self.assertEqual(result["workstream_analysis"]["status"], "complete_with_review_items")


if __name__ == "__main__":
    unittest.main()
