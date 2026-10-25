import unittest

from backend.services.quality_gates import apply_analysis_quality


class AnalysisQualityGateTests(unittest.TestCase):
    def test_exact_source_quote_is_labeled_as_source_fact(self):
        source = "Supplier shall provide notice within 24 hours."
        state = {
            "status": "complete_with_limitations",
            "portfolio_extraction": {"contracts": {"A": {
                "extracted_terms": [{"value": source, "citation": {
                    "document_id": "A", "quote": source, "verified": False
                }}],
                "ambiguities": [],
                "completeness": {"is_truncated": False},
            }}},
            "event_summary": {"parse_errors": {}},
            "limitations": [],
        }
        result = apply_analysis_quality(state, {"A": source})
        term = state["portfolio_extraction"]["contracts"]["A"]["extracted_terms"][0]
        self.assertEqual(result["status"], "passed")
        self.assertTrue(term["source_verified"])
        self.assertEqual(term["provenance"], "source_fact")
        self.assertTrue(term["citation"]["verified"])
        self.assertEqual(state["agent_architecture"]["pattern"], "bounded state-machine workflow")

    def test_missing_or_fabricated_citation_marks_run_partial(self):
        state = {
            "status": "complete_with_limitations",
            "portfolio_extraction": {"contracts": {"A": {
                "extracted_terms": [
                    {"value": "claim without a quote"},
                    {"value": "fabricated", "citation": {"document_id": "A", "quote": "not in source"}},
                ],
                "ambiguities": [],
                "completeness": {"is_truncated": False},
            }}},
            "event_summary": {"parse_errors": {}},
            "limitations": [],
        }
        result = apply_analysis_quality(state, {"A": "Canonical contract text."})
        self.assertEqual(result["unverified_or_uncited_terms"], 2)
        self.assertEqual(result["status"], "partial_review_required")
        self.assertEqual(state["status"], "partial_quality_review_required")
        self.assertTrue(all(not t.get("source_verified", False) for t in state["portfolio_extraction"]["contracts"]["A"]["extracted_terms"]))

    def test_truncation_and_parse_errors_are_not_reported_as_complete(self):
        state = {
            "status": "complete_with_limitations",
            "portfolio_extraction": {"contracts": {"A": {
                "extracted_terms": [],
                "ambiguities": ["Output capped."],
                "completeness": {"is_truncated": True},
            }}},
            "event_summary": {"parse_errors": {"events.jsonl": [{"line": 2, "status": "parse_error"}]}},
            "limitations": [],
        }
        result = apply_analysis_quality(state, {"A": "Canonical contract text."})
        self.assertEqual(result["status"], "partial_review_required")
        self.assertEqual(result["parse_error_count"], 1)
        self.assertEqual(result["truncated_contracts"], ["A"])
        self.assertEqual(state["status"], "partial_quality_review_required")

    def test_preexisting_budget_status_is_preserved(self):
        state = {
            "status": "partial_budget_exhausted",
            "portfolio_extraction": {"contracts": {}},
            "event_summary": {"parse_errors": {}},
            "limitations": [],
        }
        apply_analysis_quality(state, {})
        self.assertEqual(state["status"], "partial_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
