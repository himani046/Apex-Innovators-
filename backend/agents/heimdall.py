"""Heimdall: event-to-contract mapping and evidence verification."""
from __future__ import annotations

import re
from typing import Any


def verify(finding: dict[str, Any], events: list[dict[str, Any]],
           citations: list[dict[str, Any]]) -> dict[str, Any]:
    """Backward-compatible A1-shaped verifier using generic evidence predicates."""
    relevant = []
    contract_id = str(finding.get("contract_id") or "A1")
    for event in events:
        body = str(event.get("body", event.get("text", "")))
        if _event_mentions_contract(event, contract_id):
            relevant.append({
                "event_id": event.get("event_id"),
                "timestamp": event.get("timestamp"),
                "body": body,
                "contract_id": contract_id,
            })
    verified_citations = [
        {"document_id": c.get("document_id", contract_id),
         "clause_reference": c.get("clause_reference"),
         "quote": c.get("quote", ""),
         "verified": bool(c.get("verified")),
         "verification_note": c.get("verification_note")}
        for c in citations
    ]
    source_ok = bool(verified_citations) and all(c["verified"] for c in verified_citations)
    has_events = bool(relevant)
    gaps = list(finding.get("evidence_gaps") or [])
    challenges = []
    supports = []
    if has_events:
        supports.append(f"{len(relevant)} supplied event(s) explicitly reference {contract_id}.")
    else:
        gaps.append(f"No supplied event explicitly mapped to contract {contract_id}.")
        challenges.append("No event-to-contract link was established from explicit identifiers.")
    if not source_ok:
        gaps.append("One or more contractual quotations failed or lack exact-source verification.")
        challenges.append("The contractual basis is not fully citation-verified.")
    challenges.append("An event-to-contract match does not by itself establish causation, breach, damages, or that a contractual trigger occurred.")
    return {
        "agent": "Heimdall",
        "contract_id": contract_id,
        "status": "verified_with_limitations" if source_ok and has_events else "unverified",
        "supports": supports + (["Cited clause quotation(s) exist in the source."] if source_ok else []),
        "challenges": challenges,
        "citation_checks_passed": source_ok,
        "citation_results": verified_citations,
        "mapped_events": relevant,
        "evidence_gaps": list(dict.fromkeys(gaps)),
        "recommended_follow_up": "Confirm event authenticity, timing, contractual trigger and any exceptions before alleging breach.",
    }


def _event_mentions_contract(event: dict[str, Any], contract_id: str) -> bool:
    """Map only explicit contract IDs or explicit referenced contract identifiers."""
    candidates = {
        str(event.get("contract_id", "")).strip(),
        str(event.get("document_id", "")).strip(),
        str(event.get("contract_ref", "")).strip(),
    }
    if contract_id in candidates:
        return True
    body = str(event.get("body", event.get("text", "")))
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(contract_id) + r"(?![A-Za-z0-9])", body, re.I))


def _normalized_words(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", str(value or "").casefold()))


def _contract_party_candidates(source: str) -> set[str]:
    """Extract conservative party-name candidates from common contract formulations."""
    candidates: set[str] = set()
    patterns = [
        r"(?is)\bbetween\s+([^,;\n]{2,100}?)\s+and\s+([^,;\n]{2,100}?)(?=\s+(?:effective|dated|as of|each party|hereinafter)|[.;\n]|$)",
        r"(?im)^\s*(?:supplier|vendor|customer|client|provider|counterparty|party\s+[ab])\s*:\s*([^\n,;]{2,100})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            for value in match.groups():
                cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n'\"()")
                cleaned = re.sub(r"^(?:the\s+)?", "", cleaned, flags=re.I).strip()
                if len(cleaned) >= 3 and _normalized_words(cleaned):
                    candidates.add(cleaned)
    for line in source.splitlines()[:40]:
        match = re.match(r"\s*(?:supplier|vendor|customer|client|provider|counterparty|company)\s*:\s*(.{3,100})", line, re.I)
        if match:
            candidates.add(re.sub(r"\s+", " ", match.group(1)).strip(" .,'\""))
    return candidates


def _event_contract_link(event: dict[str, Any], contract_id: str, source: str) -> dict[str, Any] | None:
    """Return an evidence-labelled link; explicit IDs outrank party-name candidates."""
    id_values = {str(event.get(key, "")).strip() for key in ("contract_id", "document_id", "contract_ref")}
    body = str(event.get("body", event.get("text", "")))
    if contract_id in id_values or re.search(
        r"(?<![A-Za-z0-9])" + re.escape(contract_id) + r"(?![A-Za-z0-9])", body, re.I
    ):
        return {"method": "explicit_contract_identifier", "confidence": "high"}
    event_party_values = [
        event.get(key) for key in (
            "counterparty", "party", "vendor", "supplier", "customer",
            "client", "provider", "entity_name", "organization"
        )
    ]
    event_words = _normalized_words(" ".join([body] + [str(v) for v in event_party_values if v]))
    matches = []
    generic = {"the", "company", "party", "supplier", "vendor", "customer", "client",
               "provider", "limited", "ltd", "inc", "llc", "corp", "corporation"}
    for party in _contract_party_candidates(source):
        meaningful = _normalized_words(party) - generic
        if meaningful and meaningful.issubset(event_words):
            matches.append(party)
    if len(matches) == 1:
        return {"method": "contract_party_name_candidate", "confidence": "medium", "matched_party": matches[0]}
    if len(matches) > 1:
        return {"method": "ambiguous_party_name_candidates", "confidence": "low", "matched_parties": matches}
    return None


_EVENT_CLAUSE_FAMILIES: dict[str, tuple[re.Pattern[str], set[str]]] = {
    "payment": (re.compile(r"\b(invoice|payment|paid|remittance|refund|credit note|billing|overdue|past due|purchase order|amount due)\b", re.I),
                {"payment", "invoice", "billing", "penalty_or_interest"}),
    "renewal": (re.compile(r"\b(renewal|renew|non[- ]renewal|auto[- ]renew|extension of term)\b", re.I),
                {"renewal", "notice_obligation", "termination"}),
    "termination": (re.compile(r"\b(terminate|termination|cure period|default notice|suspend service)\b", re.I),
                    {"termination", "notice_obligation", "liability_or_indemnity"}),
    "notice": (re.compile(r"\b(notice|notified|notification|informed|awareness|aware of|reported to)\b", re.I),
               {"notice_obligation", "termination", "compliance"}),
    "penalty_or_interest": (re.compile(r"\b(penalty|liquidated damages|late fee|interest|service credit|credit for downtime)\b", re.I),
                            {"penalty_or_interest", "liability_or_indemnity", "payment"}),
    "delivery_performance": (re.compile(r"\b(delivery|deliver|shipment|delay|late|milestone|service level|sla|uptime|downtime|outage|failure to perform)\b", re.I),
                             {"termination", "penalty_or_interest", "liability_or_indemnity", "compliance"}),
    "data_security": (re.compile(r"\b(data breach|security incident|unauthorized access|personal data|cyberattack|ransomware)\b", re.I),
                      {"notice_obligation", "liability_or_indemnity", "compliance"}),
    "confidentiality": (re.compile(r"\b(confidential|disclosure|non-disclosure|trade secret)\b", re.I),
                        {"liability_or_indemnity", "compliance"}),
    "force_majeure": (re.compile(r"\b(force majeure|natural disaster|government order|beyond reasonable control|extreme weather)\b", re.I),
                      {"termination", "liability_or_indemnity", "compliance"}),
    "compliance": (re.compile(r"\b(regulatory|regulation|non-compliance|audit finding|violation|license revoked)\b", re.I),
                   {"compliance", "termination", "liability_or_indemnity"}),
}


def _event_signals(body: str) -> list[str]:
    return [family for family, (pattern, _) in _EVENT_CLAUSE_FAMILIES.items() if pattern.search(body)]


def verify_contract_review(contract_id: str, source: str, findings: list[dict[str, Any]],
                           events: list[dict[str, Any]]) -> dict[str, Any]:
    """Map events to contracts and candidate clauses with explicit evidence trails.

    Contract links can come from explicit identifiers or unique party-name candidates.
    Clause-family mapping is rule-based triage, never proof of authenticity, trigger,
    causation, breach, or damages.
    """
    mapped = []
    for event in events:
        body = str(event.get("body", event.get("text", "")))
        link = _event_contract_link(event, contract_id, source)
        if not link:
            continue
        signals = _event_signals(body)
        matched_findings = []
        for finding in findings:
            category = str(finding.get("category", "")).casefold()
            citation = finding.get("evidence") or {}
            quote = str(citation.get("quote", ""))
            family_matches = [family for family in signals if category in _EVENT_CLAUSE_FAMILIES[family][1]]
            lexical_matches = sorted(_normalized_words(body).intersection(_normalized_words(quote)))
            if family_matches or len(lexical_matches) >= 2:
                matched_findings.append({
                    "finding_id": finding.get("id"), "category": category or None,
                    "title": finding.get("title"), "matched_event_families": family_matches,
                    "matched_terms": lexical_matches[:20],
                    "clause_reference": citation.get("clause_reference"),
                    "clause_quote": quote, "clause_quote_verified": bool(quote and quote in source),
                    "status": "candidate_clause_association_requires_trigger_review",
                })
        date_candidates = sorted(set(re.findall(
            r"\b(?:\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b",
            body, re.I
        )))
        mapped.append({
            "event_id": event.get("event_id"), "timestamp": event.get("timestamp"),
            "body": body, "contract_id": contract_id, "contract_link": link,
            "event_families": signals, "matched_clauses": matched_findings,
            "candidate_deadline_dates": date_candidates,
            "status": "mapped_to_contract_and_candidate_clauses" if matched_findings else "mapped_to_contract_no_clause_match",
            "event_source": event.get("event_source", event.get("source")),
            "source_url": event.get("source_url", event.get("url")),
            "source_type": event.get("source_type"),
            "verification_method": event.get("verification_method"),
            "source_verified": False,
            "source_verification_claimed": event.get("source_verified_claimed") is True or event.get("source_verified") is True,
            "authenticity_status": "not_independently_verified",
            "trigger_status": "not_determined", "causation_status": "not_determined",
            "note": "Contract and clause links are rule-based candidates. Verify source authenticity, operative clause, timing, exceptions, amendments, and trigger facts.",
        })
    results = []
    for finding in findings:
        checks = []
        for citation in finding.get("citations", []):
            quote = str(citation.get("quote", ""))
            verified = bool(quote and quote in source)
            checks.append({
                "document_id": citation.get("document_id", contract_id),
                "clause_reference": citation.get("clause_reference"),
                "quote": quote, "verified": verified,
                "verification_note": "Exact quote matched canonical source." if verified else "Quote did not match canonical source.",
            })
        all_verified = bool(checks) and all(item["verified"] for item in checks)
        finding_id = finding.get("id")
        finding_events = [
            event for event in mapped
            if any(match.get("finding_id") == finding_id for match in event.get("matched_clauses", []))
        ]
        gaps = list(finding.get("evidence_gaps", []))
        if not checks:
            gaps.append("No source citation was supplied for this finding.")
        elif not all_verified:
            gaps.append("One or more source quotations could not be verified.")
        if not finding_events:
            gaps.append("No event was associated with this clause candidate; this does not prove that no event occurred.")
        results.append({
            "finding_id": finding_id, "contract_id": contract_id,
            "status": "verified_with_limitations" if all_verified and finding_events else "unverified",
            "citation_checks_passed": all_verified,
            "citation_results": checks, "mapped_events": finding_events,
            "supports": (["The cited source quotation exists in the canonical contract text."] if all_verified else [])
                       + ([f"{len(finding_events)} event(s) have candidate overlap with this clause; trigger and causation remain unproven."] if finding_events else []),
            "challenges": [
                "Quotation verification does not by itself establish contractual applicability, trigger, breach or damages.",
                "Event-to-clause mapping is a rule-based candidate association, not proof of causation.",
            ],
            "evidence_gaps": list(dict.fromkeys(gaps)),
            "recommended_follow_up": "Confirm event authenticity, timestamps, triggering condition, exceptions, amendments, and contract precedence.",
            "agent": "Heimdall",
        })
    return {
        "agent": "Heimdall", "contract_id": contract_id, "findings": results,
        "mapped_events": mapped,
        "mapping_summary": {
            "events_mapped": len(mapped),
            "events_with_clause_candidates": sum(bool(item.get("matched_clauses")) for item in mapped),
            "events_linked_by_explicit_id": sum(item.get("contract_link", {}).get("method") == "explicit_contract_identifier" for item in mapped),
            "events_linked_by_party_candidate": sum(item.get("contract_link", {}).get("method") == "contract_party_name_candidate" for item in mapped),
            "source_authenticity_verified": False,
        },
        "status": "verified_with_limitations" if results and all(item["citation_checks_passed"] for item in results) else "unverified",
    }
