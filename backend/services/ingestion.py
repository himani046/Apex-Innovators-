import csv,json
from pathlib import Path
def load_events(path):
 events,errors=[],[]
 for n,line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(),1):
  if not line.strip():continue
  try:
   item=json.loads(line)
   if not isinstance(item,dict):raise ValueError('JSONL record must be an object')
   events.append(item)
  except (json.JSONDecodeError,ValueError) as exc:errors.append({'line':n,'error':str(exc),'status':'parse_error'})
 return events,errors
def load_pack(root):
 root=Path(root);b=root/'bundle';contracts={p.stem:p.read_text(encoding='utf-8') for p in (b/'contracts').glob('*.txt')};drops={};errors={}
 for name in ('events_drop1.jsonl','events_drop2.jsonl'):drops[name],errors[name]=load_events(b/'events'/name)
 def rows(path):
  with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
 return {'company_context':(b/'company/context.txt').read_text(encoding='utf-8'),'contracts':contracts,'manifest':json.loads((b/'manifest.json').read_text()),'clock':json.loads((root/'clock.json').read_text()),'ledger':rows(b/'data/payments_ledger.csv'),'holidays':rows(b/'data/holidays.csv'),'event_drops':drops,'parse_errors':errors}
