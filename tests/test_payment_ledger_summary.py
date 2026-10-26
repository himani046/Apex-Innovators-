import unittest

from backend.app import _summarize_payment_ledger


class PaymentLedgerSummaryTests(unittest.TestCase):
    def test_summarizes_paid_receipts_sent_payments_and_open_receivables(self):
        rows = [
            {"date": "2026-09-20", "from": "Harbor Retail Group LLC", "to": "Quillhub Inc.", "amount": "40000", "reference": "September platform fee - QH-HARBOR-2026-001", "status": "paid"},
            {"date": "2026-10-06", "from": "Harbor Retail Group LLC", "to": "Quillhub Inc.", "amount": "40000", "reference": "October platform fee - QH-HARBOR-2026-001", "status": "paid"},
            {"date": "2027-04-08", "from": "Harbor Retail Group LLC", "to": "Quillhub Inc.", "amount": "40000", "reference": "April platform fee - QH-HARBOR-2026-001", "status": "overdue"},
            {"date": "2026-08-05", "from": "Quillhub Inc.", "to": "StratoNode Inc.", "amount": "8000", "reference": "August hosting fee - QH-STRATO-2026-001", "status": "paid"},
            {"date": "2027-05-05", "from": "Quillhub Inc.", "to": "StratoNode Inc.", "amount": "8000", "reference": "May hosting fee - QH-STRATO-2026-001", "status": "pending"},
        ]
        summary = _summarize_payment_ledger(rows)
        self.assertEqual(summary["revenue_received"], 80000.0)
        self.assertEqual(summary["payments_sent"], 8000.0)
        self.assertEqual(summary["received_overdue"], 40000.0)
        self.assertEqual(summary["sent_pending"], 8000.0)
        self.assertEqual(summary["rows"], 5)

    def test_non_company_transfers_are_not_counted_as_company_cashflow(self):
        rows = [{"from": "Vendor A", "to": "Vendor B", "amount": "500", "status": "paid"}]
        summary = _summarize_payment_ledger(rows)
        self.assertEqual(summary["revenue_received"], 0.0)
        self.assertEqual(summary["payments_sent"], 0.0)


if __name__ == "__main__":
    unittest.main()
