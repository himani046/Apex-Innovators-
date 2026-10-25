import unittest
from pathlib import Path

from backend.config import PACK_DIR
from backend.services.citations import verify_citation
from backend.services.ingestion import load_events, load_pack
from backend.orchestrator import run_demo


class OdinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = load_pack(PACK_DIR)

    def test_pack_contains_a1(self):
        self.assertIn("A1", self.pack["contracts"])
        self.assertIn("STD", self.pack["contracts"])

    def test_citation_exact_quote_passes(self):
        source = self.pack["contracts"]["A1"]
        self.assertTrue(verify_citation({"document_id": "A1", "clause_reference": "Section C", "quote": "  Monthly Fee:     $8,000.00 (Eight Thousand U.S. Dollars)"}, {"A1": source})["verified"])

    def test_citation_wrong_quote_fails(self):
        result = verify_citation({"document_id": "A1", "clause_reference": "Section C", "quote": "The fee is $1"}, self.pack["contracts"])
        self.assertFalse(result["verified"])

    def test_jsonl_parser_keeps_valid_events_and_reports_bad_lines(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "events.jsonl"
            path.write_text('{"event_id":"E-1"}\nnot json\n{"event_id":"E-2"}\n', encoding="utf-8")
            events, errors = load_events(path)
            self.assertEqual([e["event_id"] for e in events], ["E-1", "E-2"])
            self.assertEqual(len(errors), 1)

    def test_vertical_slice_runs_and_has_verified_citations(self):
        result = run_demo("2027-03-15", request_claude=False)
        self.assertEqual(result["status"], "complete_with_limitations")
        self.assertGreater(result["extraction"]["citation_validation"]["verified"], 0)
        self.assertTrue(all(c["verified"] for c in result["risk_finding"]["citations"]))
        self.assertTrue(result["ruling"]["action_draft"]["human_approval_required"])


if __name__ == "__main__":
    unittest.main()
