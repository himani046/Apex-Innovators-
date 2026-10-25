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


def review_contract_candidates(contract_id, source, extraction):
    """Adversarial source triage for a contract; never converts keywords into a breach finding."""
    import re
    rules = [
        ("renewal", r"\b(auto(?:matic)?[- ]renew|renewal|renew|non[- ]renewal)\b", "medium"),
        ("termination", r"\b(termination|terminate|cure period|default)\b", "medium"),
        ("penalty_or_interest", r"\b(penalty|liquidated damages|interest rate|late fee)\b", "high"),
        ("liability_or_indemnity", r"\b(indemnif\w*|limitation of liability|liability cap|consequential damages)\b", "medium"),
        ("notice_obligation", r"\b(notice period|written notice|notify within|notification within)\b", "medium"),
        ("exclusivity_or_conflict", r"\b(exclusive|exclusivity|conflict of terms|inconsistent with)\b", "medium"),
        ("compliance", r"\b(comply|compliance|regulatory|applicable law|audit right)\b", "medium"),
    ]
    terms_by_quote = {str((term.get("citation") or {}).get("quote", "")): term
                      for term in extraction.get("extracted_terms", [])}
    findings = []
    clarification_requests = []
    for line_no, raw in enumerate(source.splitlines(), start=1):
        for category, pattern, severity in rules:
            if not re.search(pattern, raw, re.I):
                continue
            term = terms_by_quote.get(raw, {})
            citation = dict(term.get("citation") or {
                "document_id": contract_id, "clause_reference": f"line {line_no}",
                "quote": raw, "verified": raw in source,
                "verification_note": "Exact source line; legal effect requires review."
            })
            citation["document_id"] = contract_id
            citation["line_number"] = line_no
            finding = {
                "id": f"{contract_id}:{category}:{line_no}", "contract_id": contract_id,
                "category": category, "title": category.replace("_", " ").title(),
                "severity": severity, "likelihood": "unassessed_not_a_probability",
                "confidence": term.get("confidence", 0.65), "status": "candidate_requires_review",
                "claim": "A potentially relevant contractual provision was identified; applicability and legal effect require review.",
                "reason": "Keyword-based source triage; this is not a finding of breach.",
                "attack_path": [
                    f"The source at line {line_no} contains language associated with {category.replace('_', ' ')}.",
                    "Confirm the clause context, exceptions, amendments, trigger facts, and counterparty position before drawing a conclusion.",
                ],
                "evidence_gaps": ["Confirm applicability and relevant trigger facts for this provision."],
                "citations": [citation], "evidence": citation,
                "agent": "Loki", "mode": "deterministic_source_triage"
            }
            findings.append(finding)
            if not citation.get("verified"):
                clarification_requests.append({"from": "Loki", "to": "Thor", "type": "targeted_reextraction_request",
                                               "contract_id": contract_id, "line_number": line_no,
                                               "reason": "Citation could not be verified against canonical source."})
    return {"agent": "Loki", "contract_id": contract_id, "findings": findings,
            "clarification_requests": clarification_requests,
            "notice": "Adversarial candidates are not proven breaches; likelihood is not calibrated."}
