import tempfile
import unittest
from pathlib import Path

from backend.services.event_store import EventStore


class EventStoreTests(unittest.TestCase):
    def test_ingest_is_durable_deduplicated_and_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.sqlite3")
            first = store.ingest("monitor-feed", [
                {"event_id": "E1", "timestamp": "2027-03-10T09:00:00", "body": "A1 incident reported",
                 "source_verified": True},
                {"event_id": "E2", "timestamp": "2027-03-20", "body": "Future event"},
                {"event_id": "E3", "timestamp": "not-a-date", "body": "Malformed event"},
                {"event_id": "E4", "timestamp": "2027-03-10", "body": ""},
            ])
            self.assertEqual(first["counts"]["inserted"], 2)
            self.assertEqual(first["counts"]["rejected"], 2)
            self.assertFalse(first["source_authenticity_verified"])
            duplicate = store.ingest("monitor-feed", [
                {"event_id": "E1", "timestamp": "2027-03-10T09:00:00", "body": "A1 incident reported",
                 "source_verified": True},
            ])
            self.assertEqual(duplicate["counts"]["duplicates"], 1)
            loaded = store.list_events(as_of="2027-03-15")
            self.assertEqual([event["event_id"] for event in loaded["events"]], ["E1"])
            self.assertEqual(loaded["future_events_excluded"], 1)
            self.assertFalse(loaded["events"][0]["source_verified"])
            reopened = EventStore(Path(directory) / "events.sqlite3")
            self.assertEqual(reopened.list_events()["count"], 2)

    def test_changed_event_updates_existing_source_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.sqlite3")
            store.ingest("feed", [{"event_id": "E1", "body": "Original event"}])
            result = store.ingest("feed", [{"event_id": "E1", "body": "Corrected event"}])
            self.assertEqual(result["counts"]["updated"], 1)
            loaded = store.list_events()["events"][0]
            self.assertEqual(loaded["body"], "Corrected event")
            self.assertTrue(loaded["change_detected"])
            self.assertEqual(loaded["revision_count"], 1)
            history = store.list_revisions("feed", "E1")
            self.assertEqual(history["revision_count"], 1)
            self.assertEqual(history["revisions"][0]["previous_payload"]["body"], "Original event")
            self.assertEqual(history["revisions"][0]["new_payload"]["body"], "Corrected event")
            self.assertFalse(history["source_authenticity_verified"])


if __name__ == "__main__":
    unittest.main()
