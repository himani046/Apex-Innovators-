import asyncio
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from fastapi import UploadFile

from backend import app as app_module
from backend.services.event_store import EventStore
from backend.services.audit_store import AuditStore


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

    def test_targeted_reextraction_updates_existing_audit_run(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = app_module.audit_store
            store = AuditStore(Path(directory) / "audit.sqlite3")
            app_module.audit_store = store
            try:
                saved = store.record_run({
                    "run_id": "reextract-run",
                    "as_of_date": "2027-03-15",
                    "status": "complete_with_limitations",
                    "shared_state": {
                        "schema_version": "1.0",
                        "extracted_clauses": [{"category": "parties", "citation": {
                            "document_id": "VENDOR_X", "clause_reference": "Section 1",
                            "quote": "Customer: Existing Buyer", "verified": True,
                        }}],
                        "evidence_references": [],
                    },
                    "ruling": {"action_draft": {"subject": "Review", "body": "Draft only"}},
                })
                source = (
                    "Section 1. Term\nThe agreement lasts twelve months.\n"
                    "Section 4. Renewal\nThe agreement automatically renews for one year.\n"
                    "Section 8. Payment\nCustomer shall pay USD 500 monthly.\n"
                )
                result = app_module.reextract_clause(app_module.ReExtractionRequest(
                    contract_id="VENDOR_X", text=source, clause_reference="Section 4",
                    shared_state={"iteration": {"current": 1, "max": 2, "stop_reason": None}},
                    run_id=saved["run_id"],
                ))
                self.assertTrue(result["persistence"]["persisted"])
                self.assertTrue(result["extracted_terms"])
                self.assertTrue(all("renew" in term["citation"]["quote"].casefold()
                                    for term in result["extracted_terms"]))
                record = store.get_run(saved["run_id"])
                self.assertEqual(len(record["payload"]["reextraction_history"]), 1)
                self.assertEqual(
                    [term["category"] for term in record["payload"]["shared_state"]["extracted_clauses"]],
                    ["parties", "renewal"],
                )
                self.assertEqual(record["payload"]["shared_state"]["iteration"]["current"], 1)
                self.assertTrue(any(event["event_type"] == "targeted_reextraction" for event in record["events"]))
            finally:
                app_module.audit_store = previous

    def test_targeted_reextraction_rejects_unknown_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = app_module.audit_store
            app_module.audit_store = AuditStore(Path(directory) / "audit.sqlite3")
            try:
                with self.assertRaises(Exception) as raised:
                    app_module.reextract_clause(app_module.ReExtractionRequest(
                        contract_id="VENDOR_X",
                        text="Section 4. Renewal\nThe agreement automatically renews for one year.",
                        clause_reference="Section 4",
                        run_id="missing-run",
                    ))
                self.assertEqual(getattr(raised.exception, "status_code", None), 404)
            finally:
                app_module.audit_store = previous

    def test_portfolio_upload_accepts_pdf_and_txt_and_preserves_pdf_page_markers(self):
        from pathlib import Path

        pdf_path = Path(__file__).resolve().parents[1] / "odin_dev_pack" / "bundle" / "contracts" / "A1.pdf"
        self.assertTrue(pdf_path.exists(), "PDF fixture should be present in the repository")
        pdf_bytes = pdf_path.read_bytes()
        text_bytes = b"Section 1. The agreement term is twelve months and renews automatically."

        files = [
            UploadFile(filename="A1.pdf", file=io.BytesIO(pdf_bytes)),
            UploadFile(filename="A2.txt", file=io.BytesIO(text_bytes)),
        ]
        with patch.object(app_module, "analyze_portfolio", side_effect=lambda body: {
            "contract_ids": [contract.id for contract in body.contracts],
            "contract_texts": [contract.text for contract in body.contracts],
        }):
            result = asyncio.run(app_module.analyze_portfolio_upload(
                company_context="A company manages supplier contracts and renewal obligations.",
                files=files,
                event_records="[]",
                payment_ledger="[]",
                as_of="2027-03-15",
                use_claude=False,
            ))

        self.assertEqual(result["uploaded_documents"][0]["format"], "PDF")
        self.assertGreater(result["uploaded_documents"][0]["pages"], 0)
        self.assertEqual(result["uploaded_documents"][1]["format"], "TXT")
        self.assertIn("A1", result["contract_ids"])
        self.assertIn("A2", result["contract_ids"])
        self.assertIn("[PDF page 1]", result["contract_texts"][0])
        self.assertIn("automatically", result["contract_texts"][1])

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
