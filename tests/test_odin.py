import unittest,tempfile
from pathlib import Path
from backend.config import PACK_DIR
from backend.services.ingestion import load_pack,load_events
from backend.services.citations import verify_citation
from backend.orchestrator import run_demo
class OdinTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.pack=load_pack(PACK_DIR)
 def test_pack_has_a1_and_std(self):self.assertIn('A1',self.pack['contracts']);self.assertIn('STD',self.pack['contracts'])
 def test_exact_quote_passes(self):self.assertTrue(verify_citation({'document_id':'A1','quote':'  Monthly Fee:     $8,000.00 (Eight Thousand U.S. Dollars)'},self.pack['contracts'])['verified'])
 def test_bad_quote_fails(self):self.assertFalse(verify_citation({'document_id':'A1','quote':'The fee is $1'},self.pack['contracts'])['verified'])
 def test_malformed_jsonl_is_reported(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.jsonl';p.write_text('{"event_id":"E1"}\nnot json\n{"event_id":"E2"}\n');events,errors=load_events(p);self.assertEqual(len(events),2);self.assertEqual(len(errors),1)
 def test_vertical_slice(self):
  r=run_demo('2027-03-15',False);self.assertEqual(r['status'],'complete_with_limitations');self.assertGreater(r['extraction']['citation_validation']['verified'],0);self.assertTrue(r['ruling']['action_draft']['human_approval_required'])
if __name__=='__main__':unittest.main()
