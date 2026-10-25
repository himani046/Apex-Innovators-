import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend import app as app_module
from backend.services.event_store import EventStore


class EventAPIIntegrationTests(unittest.TestCase):
    def test_event_ingest_route_persists_and_lists_records(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = app_module.event_store
            app_module.event_store = EventStore(Path(directory) / "events.sqlite3")
            try:
                result = app_module.ingest_events(app_module.EventIngestionRequest(
                    source="integration-test",
                    events=[{"event_id": "EVT-1", "timestamp": "2027-03-10",
                             "body": "CONTRACT_A incident reported", "source_verified": True}],
                ))
                self.assertEqual(result["counts"]["inserted"], 1)
                listing = app_module.list_events(as_of=date(2027, 3, 15), limit=1000)
                self.assertEqual(listing["count"], 1)
                self.assertFalse(listing["events"][0]["source_verified"])
            finally:
                app_module.event_store = previous

    def test_portfolio_analysis_includes_durable_events_without_trusting_them(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = app_module.event_store
            app_module.event_store = EventStore(Path(directory) / "events.sqlite3")
            try:
                app_module.event_store.ingest("integration-test", [
                    {"event_id": "EVT-2", "timestamp": "2027-03-10",
                     "body": "CONTRACT_A invoice INV-22 issued for USD 100."},
                ])
                body = app_module.PortfolioAnalysisRequest(
                    company_context="A company manages a supplier contract and invoice obligations.",
                    contracts=[{"id": "CONTRACT_A", "text": (
                        "Supplier invoices are payable within 30 days after receipt. "
                        "Supplier shall provide written notice within 4 hours after incident awareness."
                    )}],
                    event_records=[],
                    as_of=date(2027, 3, 15),
                    use_claude=False,
                )
                with patch.object(app_module.audit_store, "record_run", return_value={
                    "run_id": "test-run", "created_at": "2027-03-15T00:00:00Z",
                    "input_fingerprint": "test-fingerprint",
                }):
                    result = app_module.analyze_portfolio(body)
                self.assertEqual(result["event_store_context"]["stored_events_loaded"], 1)
                self.assertFalse(result["event_store_context"]["event_source_authenticity_verified"])
                self.assertEqual(result["financial_reconciliation"]["counts"]["payment_candidates"], 1)
                self.assertIsNone(result["financial_reconciliation"]["verified_financial_exposure"])
            finally:
                app_module.event_store = previous


if __name__ == "__main__":
    unittest.main()
