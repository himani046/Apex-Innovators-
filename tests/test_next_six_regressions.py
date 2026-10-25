import unittest

from backend.agents.heimdall import verify_contract_review
from backend.services.portfolio_operations import build_portfolio_operations
from backend.services.synthesis import build_synthesis


class NextSixRegressionTests(unittest.TestCase):
    def test_custom_contract_ids_are_used_for_ledger_linking(self):
        result = build_portfolio_operations(
            {
                "workstreams": [{
                    "id": "contract-VENDOR_X",
                    "primary_contract_id": "VENDOR_X",
                    "contract_ids": ["VENDOR_X"],
                    "deadlines": [],
                    "financial_exposure": {"amounts_found": []},
                }]
            },
            {},
            "2027-03-15",
            payment_ledger=[{
                "date": "2027-03-10",
                "from": "Customer",
                "to": "VENDOR_X",
                "reference": "INV-123",
                "status": "paid",
                "amount": "125.00",
            }],
        )
        row = result["financial_reconciliation"]["payment_ledger_candidates"][0]
        self.assertEqual(row["contract_id"], "VENDOR_X")
        self.assertEqual(row["contract_match_status"], "explicit_document_id")
        self.assertEqual(row["reconciliation_status"], "ledger_row_linked_for_review")
        self.assertIsNone(result["financial_reconciliation"]["portfolio_total_usd"])

    def test_future_events_are_excluded_from_as_of_financial_review(self):
        result = build_portfolio_operations(
            {
                "workstreams": [{
                    "id": "contract-VENDOR_X",
                    "primary_contract_id": "VENDOR_X",
                    "contract_ids": ["VENDOR_X"],
                    "deadlines": [],
                    "financial_exposure": {"amounts_found": []},
                }]
            },
            {
                "events.jsonl": [{
                    "event_id": "future-invoice",
                    "timestamp": "2027-03-16T09:00:00Z",
                    "contract_id": "VENDOR_X",
                    "body": "Invoice for USD $500.00",
                }]
            },
            "2027-03-15",
            payment_ledger=[],
        )
        self.assertEqual(result["financial_reconciliation"]["payment_ledger_candidates"], [])

    def test_event_provenance_is_retained_without_claiming_authenticity(self):
        source = "Section 4. Supplier shall notify within four hours."
        result = verify_contract_review(
            "VENDOR_X",
            source,
            [{
                "id": "finding-1",
                "category": "notice_obligation",
                "citations": [{
                    "document_id": "VENDOR_X",
                    "clause_reference": "Section 4",
                    "quote": "Section 4. Supplier shall notify within four hours.",
                }],
                "evidence_gaps": [],
            }],
            [{
                "event_id": "event-1",
                "contract_id": "VENDOR_X",
                "timestamp": "2027-03-10T10:00:00Z",
                "body": "Supplier sent a notice.",
                "event_source": "events.jsonl",
                "source_url": "https://example.invalid/event-1",
                "source_type": "customer_report",
                "verification_method": "not_checked",
                "source_verified": False,
            }],
        )
        event = result["mapped_events"][0]
        self.assertEqual(event["event_source"], "events.jsonl")
        self.assertEqual(event["source_type"], "customer_report")
        self.assertEqual(event["authenticity_status"], "not_independently_verified")
        self.assertFalse(event["source_verified"])

    def test_synthesis_does_not_hide_incomplete_workflow_status(self):
        result = build_synthesis({"status": "partial_budget_exhausted"})
        self.assertEqual(result["status"], "partial_budget_exhausted")
        self.assertEqual(
            result["company_risk_report"]["status"],
            "partial_budget_exhausted",
        )


if __name__ == "__main__":
    unittest.main()
