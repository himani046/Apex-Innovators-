import unittest

from backend.config import PACK_DIR
from backend.services.contract_graph import build_contract_graph, reconcile_contracts
from backend.services.ingestion import load_pack


class ContractGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_pack(PACK_DIR)
        cls.contracts = cls.pack["contracts"]
        cls.graph = build_contract_graph(cls.contracts)
        cls.reconciliation = reconcile_contracts(cls.contracts, cls.graph)

    def test_graph_has_every_loaded_document(self):
        self.assertEqual(
            {node["document_id"] for node in self.graph["nodes"]},
            set(self.contracts),
        )
        self.assertEqual(self.graph["node_count"], len(self.contracts))

    def test_graph_edges_have_verifiable_evidence_or_explicit_review_status(self):
        for edge in self.graph["edges"]:
            self.assertIn(edge["source"], self.contracts)
            self.assertIn(edge["target"], self.contracts)
            if edge["status"] == "evidence_linked":
                self.assertTrue(edge["evidence"]["verified"])
                self.assertIn(edge["evidence"]["quote"], self.contracts[edge["source"]])

    def test_a1_a3_relationship_is_detected(self):
        self.assertTrue(any(
            edge["source"] == "A3" and edge["target"] == "A1" and edge["relation"] == "amends"
            for edge in self.graph["edges"]
        ))

    def test_explicit_a1_notice_period_amendment_is_reconciled(self):
        matches = [
            item for item in self.reconciliation["resolved_changes"]
            if item["target_document"] == "A1" and item["provision"] == "non_renewal_notice_period"
        ]
        self.assertEqual(len(matches), 1)
        item = matches[0]
        self.assertEqual(item["original_value"], "90 days")
        self.assertEqual(item["amended_value"], "60 days")
        self.assertEqual(item["effective_date"], "2027-01-01")
        self.assertEqual(item["status"], "resolved_by_explicit_amendment")
        self.assertTrue(all(e["verified"] for e in item["evidence"]))
        self.assertIn("90 days", item["evidence"][0]["quote"])
        self.assertIn("changed from ninety", item["evidence"][1]["quote"].lower())

    def test_other_amendment_sections_remain_review_items(self):
        items = self.reconciliation["review_items"]
        self.assertTrue(any("CREDIT REQUEST PROCEDURE" in i.get("section_heading", "") for i in items))
        self.assertTrue(any("SERVICE CREDIT CALCULATION" in i.get("section_heading", "") for i in items))
        self.assertTrue(all(i["human_review_required"] for i in items))

    def test_missing_contract_text_does_not_create_edges_or_resolutions(self):
        result = build_contract_graph({"BASE": "Base agreement. No other document identifiers."})
        reconciliation = reconcile_contracts({"BASE": "Base agreement. No other document identifiers."}, result)
        self.assertEqual(result["edges"], [])
        self.assertEqual(reconciliation["resolved_changes"], [])

    def test_graph_and_reconciliation_are_deterministic(self):
        self.assertEqual(build_contract_graph(self.contracts), build_contract_graph(self.contracts))
        self.assertEqual(
            reconcile_contracts(self.contracts, self.graph),
            reconcile_contracts(self.contracts, self.graph),
        )


if __name__ == "__main__":
    unittest.main()
