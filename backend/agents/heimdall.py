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


def verify_contract_review(contract_id: str, source: str, findings: list[dict[str, Any]],
                           events: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify citations and attach only conservative, explicitly linked events.

    Lexical overlap produces candidate clause associations; it never establishes
    breach or causation. Citation validity is checked against the source text.
    """
    mapped = []
    for event in events:
        if not _event_mentions_contract(event, contract_id):
            continue
        body = str(event.get("body", event.get("text", "")))
        body_terms = set(re.findall(r"[a-z]{4,}", body.casefold()))
        matched_findings = []
        for finding in findings:
            citation = finding.get("evidence") or {}
            quote_terms = set(re.findall(r"[a-z]{5,}", str(citation.get("quote", "")).casefold()))
            category_terms = set(re.findall(r"[a-z]{4,}", str(finding.get("category", "")).replace("_", " ").casefold()))
            overlap = sorted(body_terms.intersection(quote_terms | category_terms))
            if overlap:
                matched_findings.append({
                    "finding_id": finding.get("id"),
                    "category": finding.get("category"),
                    "matched_terms": overlap,
                    "clause_reference": citation.get("clause_reference"),
                    "status": "lexical_candidate_not_causation",
                })
        mapped.append({
            "event_id": event.get("event_id"), "timestamp": event.get("timestamp"),
            "body": body, "contract_id": contract_id,
            "matched_clauses": matched_findings,
            "status": "mapped_to_contract_and_candidate_clauses" if matched_findings else "mapped_to_contract_only",
            # Preserve provenance for auditability; a source label or supplied
            # boolean is not treated as independent authentication.
            "event_source": event.get("event_source", event.get("source")),
            "source_url": event.get("source_url", event.get("url")),
            "source_type": event.get("source_type"),
            "verification_method": event.get("verification_method"),
            "source_verified": False,
            "source_verification_claimed": event.get("source_verified") is True,
            "authenticity_status": "not_independently_verified",
            "note": "Explicit contract mapping only; clause matches are lexical candidates, not proof of causation. Supplied verification flags are retained as claims and are not accepted as independent authentication.",
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
            gaps.append("No event was explicitly associated with this finding; this does not prove that no event occurred.")
        results.append({
            "finding_id": finding_id, "contract_id": contract_id,
            "status": "verified_with_limitations" if all_verified and finding_events else "unverified",
            "citation_checks_passed": all_verified,
            "citation_results": checks, "mapped_events": finding_events,
            "supports": (["The cited source quotation exists in the canonical contract text."] if all_verified else [])
                       + ([f"{len(finding_events)} event(s) have lexical overlap with this clause candidate; causation is unproven."] if finding_events else []),
            "challenges": [
                "Quotation verification does not by itself establish contractual applicability, trigger, breach or damages.",
                "Event-to-clause lexical overlap is a candidate association, not proof of causation.",
            ],
            "evidence_gaps": list(dict.fromkeys(gaps)),
            "recommended_follow_up": "Confirm event authenticity, timestamps, triggering condition, exceptions, and contract precedence.",
            "agent": "Heimdall",
        })
    return {
        "agent": "Heimdall", "contract_id": contract_id, "findings": results,
        "mapped_events": mapped,
        "status": "verified_with_limitations" if results and all(item["citation_checks_passed"] for item in results) else "unverified",
    }
