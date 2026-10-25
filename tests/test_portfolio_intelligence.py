import unittest

from backend.services.portfolio_intelligence import (
    detect_cross_contract_candidates,
    normalize_event_records,
    run_bounded_review_cycles,
    reconcile_payment_events,
    review_cross_contract_candidates,
)
from backend.services.upload_analysis import extract_document_terms


class CrossContractIntelligenceTests(unittest.TestCase):
    def test_numeric_notice_difference_has_two_verified_citations(self):
        contracts = {
            "A": "Provider shall provide written notice within 4 hours after incident awareness.",
            "B": "Provider shall provide written notice within 24 hours after incident awareness.",
        }
        candidates = detect_cross_contract_candidates(contracts)
        self.assertTrue(candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["classification"], "numeric_term_difference")
        self.assertEqual(len(candidate["evidence"]), 2)
        self.assertTrue(all(item["verified"] for item in candidate["evidence"]))
        self.assertFalse(candidate["legal_conflict_determined"])
        self.assertTrue(candidate["human_review_required"])

    def test_opposing_modality_is_candidate_not_legal_conclusion(self):
        contracts = {
            "A": "Supplier shall provide written notice within 4 hours after incident awareness.",
            "B": "Supplier shall not provide written notice within 4 hours after incident awareness.",
        }
        candidates = detect_cross_contract_candidates(contracts)
        self.assertTrue(any(item["classification"] == "opposing_modality_candidate" for item in candidates))
        self.assertTrue(all(item["status"] == "candidate_requires_human_review" for item in candidates))

    def test_context_diagnostics_never_claim_party_scope_or_precedence_resolved(self):
        contracts = {
            "MSA-1": (
                "Supplier shall provide incident notice within 4 hours for hosted platform services.\n"
                "This Agreement incorporates the Master Services Agreement by reference."
            ),
            "SOW-2": (
                "Supplier shall provide incident notice within 24 hours for hosted platform services.\n"
                "This SOW references MSA-1 and the Master Services Agreement."
            ),
        }
        candidates = detect_cross_contract_candidates(contracts)
        self.assertTrue(candidates)
        candidate = next(item for item in candidates if item["classification"] == "numeric_term_difference")
        checks = candidate["context_checks"]
        self.assertFalse(checks["same_parties_confirmed"])
        self.assertFalse(checks["same_scope_confirmed"])
        self.assertFalse(checks["amendment_precedence_resolved"])
        self.assertFalse(checks["incorporated_terms_resolved"])
        self.assertTrue(checks["party_roles_overlap"])
        self.assertIn("MSA-1", checks["explicit_cross_references"])
        self.assertTrue(any("incorporated" in question.casefold() for question in candidate["unresolved_questions"]))

    def test_precedence_marker_is_diagnostic_not_a_resolution(self):
        contracts = {
            "A": "Notwithstanding the Master Agreement, Supplier shall provide notice within 4 hours.",
            "B": "Supplier shall provide notice within 24 hours.",
        }
        candidates = detect_cross_contract_candidates(contracts)
        self.assertTrue(candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["classification"], "precedence_or_amendment_review")
        self.assertTrue(candidate["context_checks"]["amendment_or_precedence_marker_detected"])
        self.assertFalse(candidate["context_checks"]["amendment_precedence_resolved"])
        self.assertFalse(candidate["legal_conflict_determined"])

    def test_cross_contract_review_runs_loki_heimdall_tyr_and_keeps_draft_unresolved(self):
        contracts = {
            "A": "Provider shall provide written incident notice within 4 hours after awareness.",
            "B": "Provider shall provide written incident notice within 24 hours after awareness.",
        }
        candidates = detect_cross_contract_candidates(contracts)
        result = review_cross_contract_candidates(
            candidates, contracts,
            [{"event_id": "E1", "contract_id": "A", "timestamp": "2027-03-10",
              "body": "Incident notice was sent for contract A."}],
            "2027-03-15", max_agent_calls=30,
        )
        self.assertEqual(result["mode"], "bounded_cross_contract_review")
        self.assertEqual(result["agent_calls_used"], 3 * len(result["traces"]))
        self.assertTrue(result["traces"])
        trace = result["traces"][0]
        self.assertEqual(trace["loki_challenge"]["agent"], "Loki")
        self.assertEqual(trace["heimdall_verification"]["agent"], "Heimdall")
        self.assertEqual(trace["tyr_ruling"]["agent"], "Tyr")
        self.assertFalse(trace["legal_conflict_determined"])
        self.assertTrue(trace["tyr_ruling"]["human_approval_required"])
        self.assertEqual(trace["tyr_ruling"]["action_draft"]["status"], "draft_only_not_sent")
        self.assertFalse(trace["heimdall_verification"]["event_source_authenticity_verified"])
        self.assertTrue(any(m["type"] == "cross_contract_evidence_verification"
                            for m in result["agent_messages"]))

    def test_cross_contract_review_budget_exhaustion_is_not_reported_complete(self):
        contracts = {
            "A": "Provider shall provide written incident notice within 4 hours after awareness.",
            "B": "Provider shall provide written incident notice within 24 hours after awareness.",
        }
        candidates = detect_cross_contract_candidates(contracts)
        result = review_cross_contract_candidates(candidates, contracts, [], "2027-03-15", max_agent_calls=2)
        self.assertEqual(result["status"], "partial_budget_exhausted")
        self.assertEqual(result["agent_calls_used"], 0)
        self.assertEqual(result["stop_reason"], "agent_call_budget_exhausted")
        self.assertTrue(result["human_review_required"])

    def test_does_not_compare_clauses_within_one_contract(self):
        contracts = {
            "A": "Supplier shall provide written notice within 4 hours. Supplier shall provide written notice within 24 hours."
        }
        self.assertEqual(detect_cross_contract_candidates(contracts), [])

    def test_event_ingestion_filters_future_and_rejects_malformed(self):
        result = normalize_event_records([
            {"event_id": "E1", "timestamp": "2027-03-10", "body": "A1 incident reported", "source_verified": True},
            {"event_id": "E2", "timestamp": "2027-03-20", "body": "Future event"},
            {"event_id": "E3", "timestamp": "not-a-date", "body": "Bad timestamp"},
            {"event_id": "E4", "timestamp": "2027-03-10", "body": ""},
            "not an object",
        ], "2027-03-15")
        self.assertEqual([event["event_id"] for event in result["events"]], ["E1"])
        self.assertEqual(result["counts"]["rejected"], 3)
        self.assertFalse(result["source_authenticity_verified"])
        self.assertFalse(result["events"][0]["source_verified"])
        self.assertTrue(result["events"][0]["source_verified_claimed"])

    def test_payment_records_link_by_explicit_invoice_but_never_claim_exposure(self):
        contracts = {"A1": "Customer pays invoices within 30 days."}
        events = [
            {"event_id": "INV-42", "contract_id": "A1", "invoice_id": "INV-42",
             "event_type": "invoice", "amount": 1200, "currency": "USD",
             "timestamp": "2027-03-01", "body": "Invoice INV-42 issued for USD 1,200."},
            {"event_id": "PAY-42", "contract_id": "A1", "invoice_id": "INV-42",
             "event_type": "payment", "amount": 1200, "currency": "USD",
             "timestamp": "2027-03-05", "body": "Payment INV-42 recorded for USD 1,200."},
        ]
        result = reconcile_payment_events(events, contracts, "2027-03-15")
        self.assertEqual(result["counts"]["invoice_groups"], 1)
        self.assertTrue(result["invoice_groups"][0]["structurally_matched"])
        self.assertIsNone(result["verified_financial_exposure"])
        self.assertFalse(result["invoice_groups"][0]["human_review_required"] is False)
        self.assertFalse(result["invoice_groups"][0]["status"] == "verified")

    def test_norns_normalizes_named_dates_and_preserves_source_quote(self):
        from backend.agents.norns import build_contract_timeline
        extraction = {"extracted_terms": [{
            "category": "notice",
            "citation": {"document_id": "A1", "line_number": 8,
                         "quote": "The notice deadline is March 15, 2027.",
                         "verified": True},
        }]}
        result = build_contract_timeline("A1", extraction, "2027-03-15")
        self.assertEqual(result[0]["date"], "2027-03-15")
        self.assertEqual(result[0]["raw_date"], "March 15, 2027")
        self.assertEqual(result[0]["date_type"], "deadline_or_notice")
        self.assertTrue(result[0]["evidence"]["verified"])

    def test_bounded_workflow_runs_clarification_and_keeps_gaps_visible(self):
        source = (
            "Section 1 — Incident Notice\n"
            "Provider shall provide written notice within 4 hours after incident awareness.\n"
        )
        contracts = {"A1": source}
        extractions = {"A1": extract_document_terms(source, "A1")}
        result = run_bounded_review_cycles(
            contracts, extractions, [], "2027-03-15",
            max_iterations=1, max_agent_calls=20,
        )
        self.assertEqual(result["mode"], "bounded_deterministic_multi_agent_workflow")
        self.assertLessEqual(result["agent_calls_used"], result["agent_call_budget"])
        self.assertTrue(result["loop_traces"])
        self.assertIn(result["loop_traces"][0]["stop_reason"], {
            "evidence_gap_persists_human_review_required",
            "evidence_threshold_met",
            "no_clarification_needed",
            "iteration_limit_reached",
        })
        self.assertTrue(any(message["type"] == "targeted_reextraction_request"
                            for message in result["agent_messages"]))
        self.assertFalse(result["legal_outcome_resolved"])

    def test_llm_opt_in_falls_back_cleanly_when_provider_is_not_configured(self):
        from unittest.mock import patch
        source = "Provider shall provide written notice within 4 hours after incident awareness."
        with patch("backend.config.USE_CLAUDE", False):
            result = run_bounded_review_cycles(
                {"A1": source}, {"A1": extract_document_terms(source, "A1")}, [],
                "2027-03-15", max_iterations=0, max_agent_calls=20, use_llm=True,
            )
        self.assertFalse(result["llm_enabled"])
        self.assertEqual(result["llm_provider_status"], "not_configured")
        self.assertEqual(result["mode"], "bounded_deterministic_multi_agent_workflow")

    def test_budget_exhaustion_is_explicit(self):
        source = "Supplier shall provide written notice within 4 hours after incident awareness."
        result = run_bounded_review_cycles(
            {"A1": source}, {"A1": extract_document_terms(source, "A1")}, [],
            "2027-03-15", max_iterations=1, max_agent_calls=2,
        )
        self.assertTrue(result["budget_exhausted"])
        self.assertLessEqual(result["agent_calls_used"], result["agent_call_budget"])


if __name__ == "__main__":
    unittest.main()
