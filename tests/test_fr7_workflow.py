import unittest
from unittest.mock import patch

from backend.services.portfolio_intelligence import run_bounded_review_cycles


class FR7WorkflowTests(unittest.TestCase):
    def test_loki_clarifies_with_thor_and_heimdall_disagreement_reaches_tyr(self):
        source = "Payment shall be made within 30 days."
        finding = {
            "id": "A1:payment:1", "contract_id": "A1", "category": "payment",
            "title": "Payment", "claim": "Potential payment risk",
            "severity": "medium", "evidence_gaps": ["Verify exact trigger evidence"],
            "citations": [{"document_id": "A1", "clause_reference": "line 1",
                           "quote": source, "verified": True}],
            "evidence": {"document_id": "A1", "clause_reference": "line 1",
                         "quote": source, "verified": True},
        }
        verification = {
            "agent": "Heimdall", "status": "unverified", "evidence_gaps": ["citation verification failed"],
            "findings": [{
                "finding_id": "A1:payment:1", "status": "unverified",
                "citation_checks_passed": False, "claim_assessment": "challenged_insufficient_event_or_citation_evidence",
                "supports": [], "challenges": ["The citation could not be verified."],
                "evidence_gaps": ["citation verification failed"], "mapped_events": [],
            }],
        }
        with patch("backend.agents.loki.review_contract_candidates", return_value={"findings": [finding]}), \
             patch("backend.agents.heimdall.verify_contract_review", return_value=verification), \
             patch("backend.agents.norns.build_contract_timeline", return_value=[]), \
             patch("backend.services.upload_analysis.extract_document_terms", return_value={"extracted_terms": []}):
            result = run_bounded_review_cycles(
                contracts={"A1": source}, extractions={"A1": {"extracted_terms": []}},
                events=[], as_of="2027-03-15", max_iterations=1, max_agent_calls=20,
            )

        types = [(m.get("from"), m.get("to"), m.get("type")) for m in result["agent_messages"]]
        self.assertIn(("Loki", "Thor", "targeted_reextraction_request"), types)
        self.assertIn(("Thor", "Loki", "targeted_extraction_result"), types)
        self.assertIn(("Heimdall", "Tyr", "evidence_disagreement"), types)
        self.assertIn(("Tyr", "Odin", "qualified_ruling"), types)
        self.assertEqual(result["loop_traces"][0]["iterations_used"], 1)
        self.assertEqual(result["loop_traces"][0]["stop_reason"], "iteration_limit_reached")
        self.assertTrue(result["human_review_required"])

    def test_call_budget_prevents_workstream_from_starting(self):
        result = run_bounded_review_cycles(
            contracts={"A1": "Payment shall be made within 30 days."},
            extractions={}, events=[], as_of="2027-03-15",
            max_iterations=2, max_agent_calls=4,
        )
        self.assertTrue(result["budget_exhausted"])
        self.assertEqual(result["stop_reason"], "agent_call_budget_exhausted")
        self.assertEqual(result["not_run_contract_ids"], ["A1"])
        self.assertEqual(result["agent_calls_used"], 0)

    def test_verified_citations_stop_repeated_reads_but_preserve_open_questions(self):
        source = "Payment shall be made within 30 days."
        result = run_bounded_review_cycles(
            contracts={"A1": source}, extractions={}, events=[],
            as_of="2027-03-15", max_iterations=3, max_agent_calls=20,
        )
        trace = result["loop_traces"][0]
        self.assertIn(trace["stop_reason"], {
            "evidence_threshold_met", "evidence_threshold_met_with_open_questions",
            "no_clarification_needed",
        })
        self.assertLessEqual(trace["iterations_used"], 3)
        self.assertLessEqual(result["agent_calls_used"], result["agent_call_budget"])


if __name__ == "__main__":
    unittest.main()
