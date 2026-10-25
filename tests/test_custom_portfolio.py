import unittest
from backend.services.custom_portfolio import analyze_custom_portfolio


class CustomPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.contracts = [
            {
                "id": "VENDOR_A",
                "text": (
                    "1. PARTIES\nCustomer: Example Buyer\nSupplier: Example Vendor\n"
                    "2. RENEWAL\nThis Agreement automatically renews on 2027-06-30 unless "
                    "either party provides written notice at least thirty days before renewal.\n"
                    "3. PAYMENT\nThe customer shall pay a monthly fee of USD 500."
                ),
            },
            {
                "id": "VENDOR_B",
                "text": (
                    "1. TERMINATION\nEither party may terminate this Agreement after a "
                    "material breach if the breach remains uncured for thirty days.\n"
                    "2. LIABILITY\nThe supplier's liability is subject to the limitation of liability."
                ),
            },
        ]

    def test_custom_input_builds_per_contract_and_company_reports(self):
        result = analyze_custom_portfolio(
            company_context="Example Buyer manages vendor agreements and renewal obligations.",
            contract_items=self.contracts,
            events=[],
            as_of="2027-03-15",
        )
        self.assertEqual(result["status"], "complete_with_limitations")
        self.assertEqual(len(result["contract_reports"]), 2)
        self.assertEqual(result["company_risk_report"]["contract_count"], 2)
        self.assertEqual(result["company_risk_report"]["total_financial_exposure"], None)

    def test_graph_contains_contract_clause_and_explicit_party_nodes(self):
        result = analyze_custom_portfolio(
            company_context="Example Buyer manages vendor agreements and renewal obligations.",
            contract_items=self.contracts,
            events=[],
            as_of="2027-03-15",
        )
        types = {node.get("type") for node in result["contract_graph"]["nodes"]}
        self.assertIn("contract", types)
        self.assertIn("clause", types)
        self.assertIn("party", types)
        self.assertTrue(all("source" in edge and "target" in edge for edge in result["contract_graph"]["edges"]))

    def test_alerts_are_triage_not_breach_conclusions(self):
        result = analyze_custom_portfolio(
            company_context="Example Buyer manages vendor agreements and renewal obligations.",
            contract_items=self.contracts,
            events=[{"event_id": "E1", "timestamp": "2027-03-01", "body": "VENDOR_A invoice paid"}],
            as_of="2027-03-15",
        )
        self.assertTrue(result["risk_signals"])
        self.assertTrue(all(item["status"] == "candidate_requires_review" for item in result["risk_signals"]))
        self.assertTrue(all("not a finding of breach" in item["reason"] for item in result["risk_signals"]))


if __name__ == "__main__":
    unittest.main()
