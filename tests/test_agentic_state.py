import unittest

from backend.services.agentic_state import (
    ExecutionBudget,
    SharedAgentState,
    needs_follow_up,
    run_bounded_follow_up,
)


class SharedStateTests(unittest.TestCase):
    def test_shared_state_rejects_unknown_sections_and_copies_values(self):
        state = SharedAgentState()
        clauses = [{"contract_id": "A1", "value": "notice"}]
        state.update("extracted_clauses", clauses)
        clauses[0]["value"] = "mutated"
        self.assertEqual(state.snapshot()["extracted_clauses"][0]["value"], "notice")
        with self.assertRaises(KeyError):
            state.update("made_up_section", [])

    def test_agent_handoffs_are_structured(self):
        state = SharedAgentState()
        state.message("Thor", "Loki", "extracted_clause", "complete", clause_id="A1-I1")
        state.record_agent("Loki", "waiting_for_evidence", consumes=["extracted_clauses"])
        snapshot = state.snapshot()
        self.assertEqual(snapshot["agent_messages"][0]["to"], "Loki")
        self.assertEqual(snapshot["agent_status"]["Loki"]["consumes"], ["extracted_clauses"])

    def test_follow_up_loop_retries_only_to_iteration_limit(self):
        budget = ExecutionBudget(max_calls=2, max_iterations=2)
        calls = []

        def follow_up(finding, verification, iteration):
            calls.append(iteration)
            return (
                {"claim": "reviewed", "iteration": iteration},
                {"status": "unverified", "evidence_gaps": ["missing source log"]},
            )

        finding, verification, summary = run_bounded_follow_up(
            {"claim": "initial"},
            {"status": "unverified", "evidence_gaps": ["missing source log"]},
            max_iterations=2,
            budget=budget,
            targeted_follow_up=follow_up,
        )
        self.assertEqual(calls, [1, 2])
        self.assertEqual(summary["iterations_used"], 2)
        self.assertEqual(summary["stop_reason"], "iteration_limit_reached")
        self.assertTrue(summary["needs_human_follow_up"])
        self.assertEqual(budget.calls_used, 2)
        self.assertEqual(finding["iteration"], 2)

    def test_follow_up_preserves_gap_when_later_verifier_omits_it(self):
        budget = ExecutionBudget(max_calls=3, max_iterations=2)

        def follow_up(finding, verification, iteration):
            # Re-analysis did not receive any new source evidence.
            return {"claim": "rechecked"}, {
                "status": "verified_with_limitations",
                "recommended_follow_up": "Request the missing provider log",
            }

        _, verification, summary = run_bounded_follow_up(
            {"claim": "initial"},
            {"status": "unverified", "evidence_gaps": ["provider awareness timestamp"]},
            2, budget, follow_up,
        )
        self.assertEqual(verification["evidence_gaps"], ["provider awareness timestamp"])
        self.assertTrue(summary["needs_human_follow_up"])
        self.assertEqual(summary["remaining_gaps"], ["provider awareness timestamp"])
        self.assertEqual(summary["stop_reason"], "iteration_limit_reached")
        self.assertEqual(summary["iterations"][1]["remaining_gaps"], ["provider awareness timestamp"])

    def test_follow_up_closes_gap_only_when_explicitly_resolved(self):
        budget = ExecutionBudget(max_calls=3, max_iterations=2)

        def follow_up(finding, verification, iteration):
            return {"claim": "supported"}, {
                "status": "verified",
                "evidence_gaps": [],
                "resolved_evidence_gaps": ["provider awareness timestamp"],
            }

        _, verification, summary = run_bounded_follow_up(
            {"claim": "initial"},
            {"status": "unverified", "evidence_gaps": ["provider awareness timestamp"]},
            2, budget, follow_up,
        )
        self.assertEqual(verification["evidence_gaps"], [])
        self.assertFalse(summary["needs_human_follow_up"])
        self.assertEqual(summary["stop_reason"], "verification_satisfied")

    def test_follow_up_stops_when_verification_satisfied(self):
        budget = ExecutionBudget(max_calls=4, max_iterations=3)
        calls = []

        def should_not_run(finding, verification, iteration):
            calls.append(iteration)
            return finding, verification

        finding, verification, summary = run_bounded_follow_up(
            {"claim": "supported"},
            {"status": "verified", "evidence_gaps": []},
            3, budget, should_not_run,
        )
        self.assertEqual(calls, [])
        self.assertEqual(summary["stop_reason"], "verification_satisfied")
        self.assertFalse(needs_follow_up(verification))
        self.assertEqual(budget.calls_used, 0)


if __name__ == "__main__":
    unittest.main()
