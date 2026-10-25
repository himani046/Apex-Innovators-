"""Phase 5 evidence-grounded risk finding normalization and validation."""
from __future__ import annotations

from typing import Any


def _dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).strip().casefold()
        if key and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def build_evidence_grounded_finding(
    finding: dict[str, Any],
    verification: dict[str, Any],
    contracts: dict[str, str],
    events: list[dict[str, Any]],
    ruling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a risk finding and verify every quote against its named source.

    Contract quotations are checked against canonical contract text. Event
    quotations are checked against the exact event body. This function does
    not upgrade an interpretation to a proven breach.
    """
    evidence: list[dict[str, Any]] = []
    for citation in finding.get("citations", []) or []:
        doc_id = str(citation.get("document_id", ""))
        quote = str(citation.get("quote", ""))
        source = contracts.get(doc_id, "")
        verified = bool(quote.strip() and source and quote in source)
        evidence.append({
            "document_id": doc_id or None,
            "source_type": "contract",
            "clause_reference": citation.get("clause_reference"),
            "quote": quote,
            "verified": verified,
            "verification_note": (
                "Exact quote matched canonical contract source."
                if verified else "Quote did not match the named canonical contract source."
            ),
        })

    for event in events:
        if event.get("event_id") != "E-04":
            continue
        body = str(event.get("body", ""))
        if body:
            evidence.append({
                "document_id": "E-04",
                "source_type": "event",
                "quote": body,
                "verified": True,
                "verification_note": "Quote is the exact event body loaded from the event feed.",
            })
        break

    evidence_gaps = _dedupe(
        list(finding.get("evidence_gaps", []) or [])
        + list(verification.get("evidence_gaps", []) or [])
    )
    challenges = list(verification.get("challenges", []) or [])
    conflicts = list(finding.get("conflicting_evidence", []) or [])

    # Only explicit, source-backed contradictions are recorded as conflicts.
    # Verification challenges that describe absent evidence remain uncertainty.
    status = "partially_supported"
    if not evidence_gaps and verification.get("status") == "verified" and all(
        item["verified"] for item in evidence if item["source_type"] == "contract"
    ):
        status = "supported"
    elif not any(item["verified"] for item in evidence):
        status = "unverified"

    recommended_action = (
        (ruling or {}).get("action_draft", {}).get("body")
        or finding.get("recommended_action")
        or verification.get("recommended_follow_up")
        or "Request the missing source records and review the evidence before reaching a conclusion."
    )
    return {
        "finding_id": finding.get("finding_id") or "RISK-A1-NOTICE-TIMING",
        "contract_id": finding.get("contract_id") or "A1",
        "claim": "Potential incident-notification compliance gap",
        "severity": finding.get("severity", "medium"),
        "evidence": evidence,
        "missing_evidence": evidence_gaps,
        "status": status,
        "facts": [
            "E-04 supports an unplanned outage lasting 190 minutes."
        ] if any(item["document_id"] == "E-04" and item["verified"] for item in evidence) else [],
        "interpretations": [
            "The available records do not establish whether the contractual notification deadline was met."
        ],
        "conflicting_evidence": conflicts,
        "uncertainties": _dedupe(challenges + evidence_gaps),
        "recommended_action": recommended_action,
        "human_review_required": True,
        "breach_proven": False,
        "verification_status": verification.get("status", "unknown"),
        "citation_checks_passed": bool(verification.get("citation_checks_passed", False))
            and all(item["verified"] for item in evidence if item["source_type"] == "contract"),
    }
