import unittest

from backend.services.contract_profile import build_contract_profile


SAMPLE = """CLOUD SERVICE AGREEMENT
CONTRACT ID: QH-STRATO-2026-001
PROVIDER INFORMATION
  Legal Name: StratoNode Inc.
  Contact: Jordan Hale, VP Sales — jordan.h@stratonode.com
CUSTOMER INFORMATION
  Legal Name: Quillhub Inc.
  Contact: Dana Kowalski, Director of Engineering — dana.k@quillhub.io
Section B — Subscription Period and Renewal
  Effective Date: August 1, 2026
  Initial Subscription Period: 24 months (ending July 31, 2028)
  Renewal Period: successive 12-month periods
  The Agreement will automatically renew for successive Renewal Periods of 12 months each, unless either party delivers written notice of non-renewal at least 90 days before the end of the then-current Subscription Period.
Section C — Fees and Payment
  Monthly Fee: $8,000.00 (Eight Thousand U.S. Dollars)
  Payment Period: 30 days from invoice date.
Section F — Data and Security
  Security Incident Notification: StratoNode will notify Quillhub within 72 hours of becoming aware of a Security Incident.
"""


class ContractProfileTests(unittest.TestCase):
    def test_profile_extracts_key_dates_parties_contacts_and_nominal_value(self):
        profile = build_contract_profile("A1", "A1.txt", SAMPLE, use_claude=False)
        self.assertEqual(profile["contract_id"], "QH-STRATO-2026-001")
        self.assertIn("StratoNode Inc.", profile["counterparty"])
        self.assertIn("Quillhub Inc.", profile["counterparty"])
        self.assertEqual(profile["effective_date"], "August 1, 2026")
        self.assertEqual(profile["end_date"], "July 31, 2028")
        self.assertIn("Jordan Hale", profile["contact_person"])
        self.assertIn("Dana Kowalski", profile["contact_person"])
        self.assertIn("192,000.00", profile["contract_value"])

    def test_contract_value_is_not_reported_as_actual_revenue(self):
        profile = build_contract_profile("A1", "A1.txt", SAMPLE, use_claude=False)
        self.assertIsNone(profile["revenue_generated"])
        self.assertIsNone(profile["revenue_recognized"])
        self.assertIsNone(profile["amount_invoiced"])
        self.assertIsNone(profile["amount_collected"])
        self.assertIsNone(profile["outstanding_balance"])

    def test_clause_quotes_are_exact_source_substrings(self):
        profile = build_contract_profile("A1", "A1.txt", SAMPLE, use_claude=False)
        for clause in profile["important_clauses"]:
            self.assertIn(clause["quote"], SAMPLE)


if __name__ == "__main__":
    unittest.main()
