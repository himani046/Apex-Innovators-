import unittest

from backend.services.contract_chat import build_chat_prompt, retrieve_excerpts


class ContractChatRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.contracts = [
            {
                "id": "SUPPLIER_A",
                "text": (
                    "1. Term. This agreement starts on 1 January 2026.\n\n"
                    "2. Termination. Either party may terminate this agreement on sixty days' written notice. "
                    "The notice must be delivered to the legal address.\n\n"
                    "3. Payment. Invoices are payable within thirty days of receipt."
                ),
            },
            {
                "id": "SUPPLIER_B",
                "text": (
                    "1. Renewal. This agreement automatically renews for one year unless either party gives "
                    "ninety days' written notice before the end of the then-current term."
                ),
            },
        ]

    def test_retrieval_prefers_relevant_contract_excerpt(self):
        excerpts = retrieve_excerpts(self.contracts, "How many days notice to terminate?", limit=4)
        self.assertTrue(excerpts)
        self.assertEqual(excerpts[0]["document_id"], "SUPPLIER_A")
        self.assertIn("sixty days", excerpts[0]["text"])

    def test_source_ids_are_stable_and_unique_in_response(self):
        excerpts = retrieve_excerpts(self.contracts, "payment invoices payable", limit=4)
        self.assertTrue(excerpts)
        self.assertEqual([f"S{i}" for i in range(1, len(excerpts) + 1)],
                         [item["source_id"] for item in excerpts])

    def test_prompt_requires_source_citations_and_explicit_uncertainty(self):
        excerpts = retrieve_excerpts(self.contracts, "renewal notice", limit=3)
        prompt = build_chat_prompt("Explain renewal.", excerpts, len(self.contracts))
        self.assertIn("[S1]", prompt)
        self.assertIn("flag the conflict", prompt)
        self.assertIn("rather than guessing", prompt)

    def test_empty_retrieval_does_not_invent_source_context(self):
        prompt = build_chat_prompt("What is the capital of France?", [], 2)
        self.assertIn("No contract excerpt was sufficiently relevant", prompt)
        self.assertIn("general knowledge", prompt)


if __name__ == "__main__":
    unittest.main()
