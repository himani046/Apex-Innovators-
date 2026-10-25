import unittest

from backend.services.evidence_grounding import build_evidence_grounded_finding


class EvidenceGroundedFindingTests(unittest.TestCase):
    def setUp(self):
        self.contracts = {"A1": "Section I.1: notify Operations within four (4) hours."}
        self.events = [{
            "event_id": "E-04",
            "body": "Duration: 190 minutes. No Scheduled Maintenance. Unplanned outage.",
        }]
        self.finding = {
            "finding_id": "risk-a1-notice-timing",
            "claim": "A notice timing breach may have occurred.",
            "severity": "medium",
            "citations": [{
                "document_id": "A1",
                "clause_reference": "Section I.1",
                "quote": "notify Operations within four (4) hours.",
                "verified": True,
            }],
            "evidence_gaps": [
                "Provider awareness timestamp",
                "Timestamp and delivery evidence for notice to ops@quillhub.io",
            ],
        }
        self.verification = {
            "status": "verified_with_limitations",
            "citation_checks_passed": True,
            "evidence_gaps": list(self.finding["evidence_gaps"]),
            "challenges": ["Notice delivery time is not established."],
        }

    def test_normalizes_finding_and_separates_facts_from_interpretations(self):
        result = build_evidence_grounded_finding(
            self.finding, self.verification, self.contracts, self.events
        )
        self.assertEqual(result["finding_id"], "risk-a1-notice-timing")
        self.assertEqual(result["contract_id"], "A1")
        self.assertEqual(result["status"], "partially_supported")
        self.assertFalse(result["breach_proven"])
        self.assertTrue(result["human_review_required"])
        self.assertTrue(result["facts"])
        self.assertTrue(result["interpretations"])
        self.assertEqual(len(result["evidence"]), 2)
        self.assertTrue(all(item["verified"] for item in result["evidence"]))

    def test_exact_quotes_are_rechecked_against_named_contract(self):
        self.finding["citations"][0]["quote"] = "Four-hour notice was required."
        result = build_evidence_grounded_finding(
            self.finding, self.verification, self.contracts, self.events
        )
        contract_evidence = next(item for item in result["evidence"] if item["source_type"] == "contract")
        self.assertFalse(contract_evidence["verified"])
        self.assertFalse(result["citation_checks_passed"])
        self.assertFalse(result["breach_proven"])

    def test_missing_evidence_is_explicit_and_deduplicated(self):
        self.verification["evidence_gaps"] = [
            "Provider awareness timestamp",
            "Provider awareness timestamp",
        ]
        result = build_evidence_grounded_finding(
            self.finding, self.verification, self.contracts, self.events
        )
        self.assertEqual(result["missing_evidence"], [
            "Provider awareness timestamp",
            "Timestamp and delivery evidence for notice to ops@quillhub.io",
        ])

    def test_explicit_conflicting_evidence_is_preserved(self):
        self.finding["conflicting_evidence"] = [{
            "title": "Conflicting provider timestamp",
            "description": "Two source records state different awareness times.",
        }]
        result = build_evidence_grounded_finding(
            self.finding, self.verification, self.contracts, self.events
        )
        self.assertEqual(len(result["conflicting_evidence"]), 1)


if __name__ == "__main__":
    unittest.main()
