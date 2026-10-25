import unittest
from datetime import date

from backend.agents.heimdall import verify_contract_review
from backend.services.custom_portfolio import _event_alert_level, _filter_alert_noise


class HeimdallFR5Tests(unittest.TestCase):
    def test_event_maps_to_contract_clause_and_challenges_loki_with_limits(self):
        source = "Section 9. Provider shall give written notice within 4 hours of incident awareness."
        finding = {
            "id": "A1:notice_obligation:1",
            "contract_id": "A1",
            "category": "notice_obligation",
            "title": "Notice obligation",
            "claim": "Potential notice-timing risk",
            "severity": "high",
            "likelihood": "elevated",
            "citations": [{"document_id": "A1", "clause_reference": "Section 9", "quote": source}],
            "evidence": {"quote": source, "clause_reference": "Section 9"},
            "evidence_gaps": ["Notice delivery timestamp"],
        }
        event = {
            "event_id": "EV-1", "contract_id": "A1", "timestamp": "2027-03-14",
            "body": "A1 incident awareness recorded; notice was sent after the outage.",
            "source": "test feed",
        }
        result = verify_contract_review("A1", source, [finding], [event])
        self.assertEqual(len(result["mapped_events"]), 1)
        self.assertTrue(result["mapped_events"][0]["matched_clauses"])
        verified = result["findings"][0]
        self.assertTrue(verified["citation_checks_passed"])
        self.assertEqual(verified["loki_claim"]["finding_id"], finding["id"])
        self.assertIn(verified["claim_assessment"], {
            "qualified_support", "challenged_insufficient_event_or_citation_evidence"
        })
        self.assertFalse(verified["event_support"][0]["source_authenticity_verified"])
        self.assertTrue(any("trigger" in challenge.lower() for challenge in verified["challenges"]))

    def test_deadline_severity_escalates_by_proximity_and_material_incident(self):
        self.assertEqual(_event_alert_level("payment_event", "invoice due", [], "2027-03-20", date(2027, 3, 15))[0], "high")
        self.assertEqual(_event_alert_level("payment_event", "invoice due", [], "2027-04-01", date(2027, 3, 15))[0], "medium")
        self.assertEqual(_event_alert_level("operational_incident", "data breach confirmed", [], "2027-03-15", date(2027, 3, 15))[0], "high")

    def test_alert_noise_filter_deduplicates_and_suppresses_weak_noise(self):
        alerts = [
            {"id": "A1:1", "category": "deadline_candidate", "severity": "high", "date": "2027-03-18"},
            {"id": "A1:1", "category": "deadline_candidate", "severity": "high", "date": "2027-03-18"},
            {"id": "generic", "category": "other", "severity": "low"},
        ]
        filtered, summary = _filter_alert_noise(alerts, date(2027, 3, 15))
        self.assertEqual(len(filtered), 1)
        self.assertEqual(summary["duplicates_suppressed"], 1)
        self.assertEqual(summary["low_signal_suppressed"], 1)


if __name__ == "__main__":
    unittest.main()
