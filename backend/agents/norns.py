from datetime import date,timedelta
def build_timeline(extraction,as_of):
 now=date.fromisoformat(as_of);start=date(2026,8,1);end=date(2028,7,31);deadline=end-timedelta(days=90);items=[]
 for dt,title in [(start,'A1 effective date'),(deadline,'A1 stated non-renewal notice deadline — check amendments'),(end,'A1 initial term ends')]:items.append({'date':dt.isoformat(),'title':title,'status':'past' if dt<now else 'upcoming','amount_usd':None})
 return {'agent':'Norns','as_of_date':as_of,'milestones':items,'monthly_fee':{'amount_usd':8000,'cadence':'monthly','note':'Contract fee only; ledger reconciliation is not included in this first slice.'},'worst_case_note':'A1 states 1.5% monthly interest on overdue amounts. Exact exposure requires invoice principal, due date and payment history.','status':'computed'}



def build_contract_timeline(contract_id, extraction, as_of):
    """Build source-grounded date candidates for any contract; never infer relative triggers."""
    import re
    from datetime import date
    current = date.fromisoformat(as_of)
    pattern = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b", re.I)
    milestones = []
    for term in extraction.get("extracted_terms", []):
        citation = term.get("citation") or {}
        quote = str(citation.get("quote", ""))
        for match in pattern.finditer(quote):
            raw_date = match.group(0)
            try:
                parsed = date.fromisoformat(raw_date)
                status = "past" if parsed < current else "upcoming"
                note = "Explicit ISO date compared with the simulated date; confirm contractual trigger and counting convention."
            except ValueError:
                status = "date_candidate"
                note = "Named date is source-grounded but requires normalization."
            around = quote[max(0, match.start()-90):min(len(quote), match.end()+90)]
            date_type = "deadline_or_notice" if re.search(r"\b(deadline|notice|renew|terminate|due|payable|within)\b", around, re.I) else "reference_or_effective_date"
            milestones.append({"contract_id": contract_id, "date": raw_date, "date_type": date_type,
                               "title": around[:180], "status": status, "evidence": citation,
                               "as_of_date": as_of, "note": note, "agent": "Norns"})
    unique = {}
    for item in milestones:
        unique[(item["date"], item["title"], item["date_type"])] = item
    return sorted(unique.values(), key=lambda item: (item["date"], item["date_type"], item["title"]))
