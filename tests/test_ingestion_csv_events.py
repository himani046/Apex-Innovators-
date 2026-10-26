import json
import tempfile
import unittest
from pathlib import Path

from backend.services.ingestion import load_pack


class CsvEventIngestionTests(unittest.TestCase):
    def test_pack_loads_csv_event_feed_and_normalizes_common_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            (bundle / "contracts").mkdir(parents=True)
            (bundle / "company").mkdir()
            (bundle / "data").mkdir()
            (bundle / "events").mkdir()
            (bundle / "contracts" / "A1.txt").write_text("Agreement source", encoding="utf-8")
            (bundle / "company" / "context.txt").write_text("Company context", encoding="utf-8")
            (bundle / "manifest.json").write_text("{}", encoding="utf-8")
            (root / "clock.json").write_text('{"as_of":"2027-03-15"}', encoding="utf-8")
            (bundle / "data" / "payments_ledger.csv").write_text("id,amount\n", encoding="utf-8")
            (bundle / "data" / "holidays.csv").write_text("date,name\n", encoding="utf-8")
            (bundle / "events" / "events_drop1.jsonl").write_text(
                '{"event_id":"E-1","timestamp":"2027-03-01","body":"Existing JSONL event"}\n',
                encoding="utf-8",
            )
            (bundle / "events" / "incident_feed.csv").write_text(
                "Event ID,Event Date,Description,Contract Ref,Source\n"
                'CSV-7,2027-03-02,"Reported outage",A1,operations-log\n',
                encoding="utf-8",
            )

            pack = load_pack(root)

            self.assertIn("events_drop1.jsonl", pack["event_drops"])
            self.assertIn("incident_feed.csv", pack["event_drops"])
            csv_events = pack["event_drops"]["incident_feed.csv"]
            self.assertEqual(len(csv_events), 1)
            self.assertEqual(csv_events[0]["event_id"], "CSV-7")
            self.assertEqual(csv_events[0]["timestamp"], "2027-03-02")
            self.assertEqual(csv_events[0]["body"], "Reported outage")
            self.assertEqual(csv_events[0]["contract_id"], "A1")
            self.assertEqual(csv_events[0]["source_file"], "incident_feed.csv")
            self.assertEqual(csv_events[0]["ingestion_format"], "csv")
            self.assertEqual(pack["parse_errors"]["incident_feed.csv"], [])


if __name__ == "__main__":
    unittest.main()
