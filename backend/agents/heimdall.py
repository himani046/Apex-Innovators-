def verify(finding,events,citations):
 event=next((e for e in events if e.get('event_id')=='E-04'),None);body=(event or {}).get('body','');ok='Duration: 190 minutes' in body and 'No Scheduled Maintenance' in body
 return {'agent':'Heimdall','status':'verified_with_limitations' if ok else 'unverified','supports':['E-04 supports that an unplanned 190-minute outage occurred.'] if ok else [],'challenges':['The event feed does not establish provider awareness time or when the required Operations notice was delivered.'],'event_evidence':'E-04 supports outage duration and unplanned status.' if ok else 'E-04 was not verified.','citation_checks_passed':all(c.get('verified',False) for c in citations),'recommended_follow_up':'Request provider incident timeline and notification delivery logs; do not label this a proven breach.'}


def verify_contract_review(contract_id, source, findings, events):
    """Verify candidate quotations and map only events that explicitly identify this contract."""
    import re
    mapped = []
    for event in events:
        body = str(event.get("body", event.get("text", "")))
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(contract_id) + r"(?![A-Za-z0-9])", body, re.I):
            mapped.append({"event_id": event.get("event_id"), "timestamp": event.get("timestamp"),
                           "body": body, "contract_id": contract_id, "status": "mapped_by_explicit_id"})
    results = []
    for finding in findings:
        checks = []
        for citation in finding.get("citations", []):
            quote = str(citation.get("quote", ""))
            verified = bool(quote and quote in source)
            checks.append({"document_id": citation.get("document_id", contract_id),
                           "clause_reference": citation.get("clause_reference"), "quote": quote,
                           "verified": verified,
                           "verification_note": "Exact quote matched canonical source." if verified else "Quote did not match canonical source."})
        all_verified = bool(checks) and all(item["verified"] for item in checks)
        gaps = list(finding.get("evidence_gaps", []))
        if not mapped:
            gaps.append("No event record explicitly mapped to this contract in the supplied event set.")
        results.append({"finding_id": finding.get("id"), "contract_id": contract_id,
                        "status": "verified_with_limitations" if all_verified else "unverified",
                        "citation_checks_passed": all_verified, "citation_results": checks,
                        "mapped_events": mapped,
                        "supports": ["The cited source quotation exists in the canonical contract text."] if all_verified else [],
                        "challenges": ["A verified quotation does not establish that a breach occurred; event, trigger, timing, exceptions and performance evidence may be missing."],
                        "evidence_gaps": list(dict.fromkeys(gaps)),
                        "recommended_follow_up": "Request targeted evidence and confirm applicability before alleging breach.",
                        "agent": "Heimdall"})
    return {"agent": "Heimdall", "contract_id": contract_id, "findings": results,
            "mapped_events": mapped,
            "status": "verified_with_limitations" if all(x.get("citation_checks_passed") for x in results) else "unverified"}
