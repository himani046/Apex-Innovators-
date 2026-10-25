import unittest
from unittest.mock import patch
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
        self.assertEqual(len(result["workstreams"]), 3)
        self.assertEqual(result["workstreams"][-1]["id"], "portfolio-cross-contract")
        senders = {message.get("from") for message in result["agent_debate"]["messages"]}
        self.assertTrue({"Thor", "Norns", "Loki", "Heimdall", "Tyr"}.issubset(senders))
        self.assertEqual(result["company_risk_report"]["contract_count"], 2)
        self.assertEqual(result["company_risk_report"]["total_financial_exposure"], None)

    def test_uploaded_payment_ledger_reconciles_invoice_candidates_without_confirming_liability(self):
        result = analyze_custom_portfolio(
            company_context="Example Buyer manages vendor agreements and payment obligations.",
            contract_items=self.contracts,
            events=[],
            as_of="2027-03-15",
            payment_ledger=[
                {"date": "2027-03-01", "contract_id": "VENDOR_A",
                 "reference": "Invoice INV-42", "amount": "500.00",
                 "currency": "USD", "status": "overdue"},
                {"date": "2027-03-05", "contract_id": "VENDOR_A",
                 "reference": "Invoice INV-42", "amount": "500.00",
                 "currency": "USD", "status": "paid"},
            ],
        )
        finance = result["financial_reconciliation"]
        self.assertEqual(finance["payment_ledger_rows_received"], 2)
        self.assertEqual(len(finance["invoice_groups"]), 1)
        group = finance["invoice_groups"][0]
        self.assertEqual(group["invoice_id"], "INV-42")
        self.assertTrue(group["structurally_matched"])
        self.assertTrue(group["trigger_evidence_status"]["payment_trigger_candidate_found"])
        self.assertFalse(group["trigger_evidence_status"]["trigger_occurrence_verified"])
        self.assertIsNone(finance["verified_financial_exposure"])
        self.assertIsNone(result["company_risk_report"]["total_financial_exposure"])

    def test_contract_actions_have_stable_ids_and_require_human_approval(self):
        result = analyze_custom_portfolio(
            company_context="Example Buyer manages vendor agreements and renewal obligations.",
            contract_items=self.contracts,
            events=[],
            as_of="2027-03-15",
        )
        actions = [
            (report["contract_id"], action)
            for report in result["contract_reports"]
            for action in report.get("recommended_actions", [])
        ]
        self.assertTrue(actions)
        for contract_id, action in actions:
            self.assertTrue(action["action_id"].startswith(contract_id + ":action:"))
            self.assertTrue(action["human_approval_required"])
            self.assertEqual(action["status"], "draft_only_not_sent")

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

    def test_cross_contract_candidates_and_bounded_workflow_reach_reports(self):
        contracts = [
            {"id": "A", "text": "Provider shall provide written notice within 4 hours after incident awareness."},
            {"id": "B", "text": "Provider shall provide written notice within 24 hours after incident awareness."},
        ]
        result = analyze_custom_portfolio(
            company_context="Example Buyer manages provider contracts and incident notice obligations.",
            contract_items=contracts,
            events=[],
            as_of="2027-03-15",
        )
        self.assertTrue(result["cross_contract_candidates"])
        candidate = result["cross_contract_candidates"][0]
        self.assertEqual(candidate["classification"], "numeric_term_difference")
        self.assertEqual(len(candidate["evidence"]), 2)
        self.assertIn("agent_workflow", result)
        self.assertEqual(
            result["shared_state"]["execution"]["mode"],
            "bounded_deterministic_multi_agent_workflow",
        )
        self.assertTrue(any(node.get("type") == "conflict_candidate"
                            for node in result["contract_graph"]["nodes"]))
        self.assertTrue(result["company_risk_report"]["cross_contract_candidates"])
        self.assertFalse(candidate["legal_conflict_determined"])
        self.assertIn("agent_review", candidate)
        self.assertEqual(candidate["agent_review"]["loki_challenge"]["agent"], "Loki")
        self.assertEqual(candidate["agent_review"]["heimdall_verification"]["agent"], "Heimdall")
        self.assertEqual(candidate["agent_review"]["tyr_ruling"]["agent"], "Tyr")
        self.assertTrue(candidate["agent_review"]["tyr_ruling"]["human_approval_required"])
        self.assertIn("cross_contract_review", result)
        self.assertEqual(result["cross_contract_review"]["status"], "complete_with_review_items")
        self.assertTrue(any(message.get("type") == "cross_contract_review_ruling"
                            for message in result["agent_debate"]["messages"]))
        self.assertLessEqual(
            result["agent_workflow"]["agent_calls_used"],
            result["agent_workflow"]["agent_call_budget"],
        )

    def test_missing_agent_workstream_is_not_reported_complete(self):
        with patch("backend.services.custom_portfolio.run_bounded_review_cycles", return_value={
            "mode": "bounded_test_workflow",
            "workstreams": [],
            "agent_calls_used": 0,
            "agent_call_budget": 300,
            "iterations_used": 0,
            "max_iterations": 1,
            "stop_reason": "test_missing_workstream",
            "agent_messages": [],
        }):
            result = analyze_custom_portfolio(
                company_context="Example Buyer manages a supplier contract and its obligations.",
                contract_items=[{"id": "VENDOR_X", "text": (
                    "Section 1. Renewal\\nThe agreement automatically renews unless written notice is given."
                )}],
                events=[],
                as_of="2027-03-15",
            )
        stream = next(item for item in result["workstreams"] if item.get("primary_contract_id") == "VENDOR_X")
        self.assertEqual(stream["status"], "not_run_missing_workstream")
        self.assertEqual(stream["progress"]["percentage"], 83)
        self.assertFalse(stream["completion_gate"]["workflow_complete"])
        self.assertEqual(result["status"], "partial_workstream_coverage")
        self.assertTrue(all(item["status"] == "partial_workstream_coverage"
                            for item in result["shared_state"]["agent_status"].values()))

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
        self.assertTrue(any(item.get("category") == "payment_event" for item in result["alert_feed"]))


if __name__ == "__main__":
    unittest.main()
