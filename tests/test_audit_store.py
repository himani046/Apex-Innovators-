import tempfile
import unittest
from pathlib import Path

from backend.services.audit_store import AuditStore


class AuditStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = AuditStore(Path(self.tempdir.name) / "audit.sqlite3")

    def tearDown(self):
        self.tempdir.cleanup()

    def payload(self, run_id="run-1", claim="Potential notice gap"):
        return {
            "run_id": run_id,
            "as_of_date": "2027-03-15",
            "status": "complete_with_limitations",
            "portfolio_extraction": {"contracts": {"A1": {}}},
            "contract_graph": {"node_count": 1},
            "evidence_grounded_finding": {
                "finding_id": "RISK-001", "contract_id": "A1", "claim": claim,
                "severity": "medium", "status": "partially_supported",
                "evidence": [{"document_id": "E-04", "quote": "An outage occurred.",
                              "verified": True, "clause_reference": "event body"}],
                "missing_evidence": ["Provider awareness timestamp"],
            },
            "verification": {"evidence_gaps": ["Provider awareness timestamp"]},
            "agent_messages": [{"from": "Heimdall", "type": "verification", "status": "verified_with_limitations"}],
            "ruling": {"action_draft": {"subject": "Request incident records", "body": "Please provide records."}},
        }

    def test_run_and_exact_evidence_are_persisted(self):
        saved = self.store.record_run(self.payload())
        record = self.store.get_run(saved["run_id"])
        self.assertIsNotNone(record)
        events = record["events"]
        evidence = [event for event in events if event["event_type"] == "evidence_provenance"]
        self.assertEqual(evidence[0]["details"]["quote"], "An outage occurred.")
        self.assertTrue(evidence[0]["details"]["verified"])
        self.assertTrue(any(event["event_type"] == "evidence_gaps_recorded" for event in events))

    def test_finding_change_is_recorded_between_runs(self):
        self.store.record_run(self.payload("run-1", "Potential notice gap"))
        self.store.record_run(self.payload("run-2", "Updated notice gap"))
        record = self.store.get_run("run-2")
        changed = [event for event in record["events"] if event["event_type"] == "finding_changed"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["details"]["previous"]["claim"], "Potential notice gap")
        self.assertEqual(changed[0]["details"]["current"]["claim"], "Updated notice gap")

    def test_run_payload_update_is_persisted_and_audited(self):
        saved = self.store.record_run(self.payload())
        record = self.store.get_run(saved["run_id"])
        payload = record["payload"]
        payload["shared_state"] = {"schema_version": "1.0", "extracted_clauses": [{"category": "renewal"}]}
        update = self.store.update_run_payload(
            saved["run_id"], payload, actor="Thor", event_type="targeted_reextraction",
            details={"contract_id": "A1", "terms_returned": 1},
        )
        self.assertEqual(update["run_id"], saved["run_id"])
        refreshed = self.store.get_run(saved["run_id"])
        self.assertEqual(refreshed["payload"]["shared_state"]["extracted_clauses"][0]["category"], "renewal")
        events = [event for event in refreshed["events"] if event["event_type"] == "targeted_reextraction"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "Thor")
        self.assertEqual(events[0]["details"]["terms_returned"], 1)

    def test_run_payload_update_rejects_missing_run(self):
        with self.assertRaises(KeyError):
            self.store.update_run_payload("missing", {})

    def test_human_decision_is_timestamped_and_never_executes_action(self):
        saved = self.store.record_run(self.payload())
        result = self.store.decide(saved["run_id"], "recommended-action", "approved", "Contract Counsel", "Reviewed")
        self.assertEqual(result["decision"], "approved")
        self.assertFalse(result["consequential_action_executed"])
        record = self.store.get_run(saved["run_id"])
        self.assertEqual(record["decisions"][0]["reviewer"], "Contract Counsel")
        self.assertTrue(any(event["event_type"] == "human_decision" for event in record["events"]))

    def test_specific_portfolio_action_can_be_reviewed_without_approving_other_actions(self):
        payload = self.payload()
        payload["contract_reports"] = [
            {"contract_id": "A1", "recommended_actions": [
                {"action_id": "A1:action:1", "subject": "Review A1", "body": "Draft A1",
                 "human_approval_required": True, "status": "draft_only_not_sent"}]},
            {"contract_id": "B2", "recommended_actions": [
                {"action_id": "B2:action:1", "subject": "Review B2", "body": "Draft B2",
                 "human_approval_required": True, "status": "draft_only_not_sent"}]},
        ]
        saved = self.store.record_run(payload)
        result = self.store.decide(saved["run_id"], "B2:action:1", "rejected", "Legal Reviewer", "Needs evidence")
        self.assertEqual(result["action_id"], "B2:action:1")
        self.assertEqual(result["decision"], "rejected")
        self.assertFalse(result["consequential_action_executed"])

    def test_generic_decision_id_is_rejected_for_multiple_actions(self):
        payload = self.payload()
        payload["ruling"] = {}
        payload["contract_reports"] = [
            {"contract_id": "A1", "recommended_actions": [
                {"action_id": "A1:action:1", "subject": "Review A1", "body": "Draft A1"}]},
            {"contract_id": "B2", "recommended_actions": [
                {"action_id": "B2:action:1", "subject": "Review B2", "body": "Draft B2"}]},
        ]
        saved = self.store.record_run(payload)
        with self.assertRaisesRegex(ValueError, "explicit action_id"):
            self.store.decide(saved["run_id"], "recommended-action", "approved", "Legal Reviewer")

    def test_decision_requires_reviewer_and_existing_run(self):
        saved = self.store.record_run(self.payload())
        with self.assertRaises(ValueError):
            self.store.decide(saved["run_id"], "recommended-action", "approved", "")
        with self.assertRaises(KeyError):
            self.store.decide("missing", "recommended-action", "approved", "Reviewer")


if __name__ == "__main__":
    unittest.main()
