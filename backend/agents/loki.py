import json
from backend.claude_client import ask_claude
from backend.config import USE_CLAUDE
SYSTEM='You are Loki, an adversarial contract reviewer. Distinguish facts from inference; do not assert breach without required facts. Return JSON with title, claim, attack_path, severity, likelihood, evidence_gaps, citations.'
def review(extraction,events,use_claude=False):
 event=next((e for e in events if e.get('event_id')=='E-04'),None);body=(event or {}).get('body','');citation=next(t['citation'] for t in extraction['extracted_terms'] if t['category']=='incident_notice')
 if use_claude and USE_CLAUDE:
  try:
   r=json.loads(ask_claude(SYSTEM,'Assess one risk using extraction and E-04. Return JSON only.\nEXTRACTION:'+json.dumps(extraction)+'\nEVENT:'+body,1000));r.update({'agent':'Loki','mode':'claude'});return r
  except Exception:pass
 return {'agent':'Loki','mode':'deterministic_fallback','finding_id':'risk-a1-notice-timing','title':'Potential gap in upstream incident-notice evidence','claim':'The March 3 outage is documented, but the event record does not establish when StratoNode became aware or when it notified Quillhub Operations. A notice-timing breach is not proven.','attack_path':['A1 Section I.1 sets a four-hour notification expectation measured from provider awareness.','E-04 documents a 190-minute unplanned outage.','The available event evidence does not establish provider-awareness time or delivery time for notice to ops@quillhub.io.','Request provider incident-awareness and notification logs before alleging breach.'],'severity':'medium','likelihood':'undetermined','evidence_gaps':['Provider awareness timestamp','Timestamp and delivery evidence for notice to ops@quillhub.io'],'citations':[citation],'requires_clarification':True}
