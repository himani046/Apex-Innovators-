"""Tyr: arbitration and draft-only action generation.

Tyr arbitrates the evidence actually returned by Loki and Heimdall. It does not
infer a breach from a keyword match or from the mere existence of a citation.
"""
from __future__ import annotations

from typing import Any


def arbitrate(finding: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible A1 ruling based on the generic evidence arbiter."""
    ruling = arbitrate_contract_finding(
        str(finding.get("contract_id") or "A1"), finding, verification
    )
    ruling.update({
        "ruling_id": finding.get("finding_id", "ruling-" + str(ruling.get("contract_id", "unknown"))),
        "rejected_or_unproven_claims": ruling.get("unproven_claims", []),
    })
    return ruling


def _evidence_ids(items: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("id") or item.get("finding_id") or item.get("event_id") or item.get("quote") or "")
        for item in items if isinstance(item, dict)
    }


def arbitrate_contract_finding(
    contract_id: str, finding: dict[str, Any], verification: dict[str, Any]
) -> dict[str, Any]:
    """Resolve one finding using verification status, source checks and remaining gaps."""
    citations = list(finding.get("citations") or [])
    checks = list(verification.get("citation_results") or [])
    if not checks:
        checks = [
            {"verified": bool(c.get("verified")), "quote": c.get("quote", ""),
             "document_id": c.get("document_id", contract_id)}
            for c in citations
        ]
    all_quotes_verified = bool(citations) and all(bool(item.get("verified")) for item in checks)
    supports = list(verification.get("supports") or [])
    challenges = list(verification.get("challenges") or [])
    gaps = list(dict.fromkeys(
        list(finding.get("evidence_gaps") or [])
        + list(verification.get("evidence_gaps") or [])
    ))
    has_event_evidence = bool(verification.get("mapped_events") or verification.get("event_evidence"))
    verifier_confirms_facts = bool(supports) and all_quotes_verified
    if verifier_confirms_facts and (challenges or gaps or verification.get("status") == "verified_with_limitations"):
        decision = "partially_supported_unresolved"
        rationale = (
            "The cited source and some supporting evidence are verified, but the verifier identified "
            "limitations or missing facts. Do not treat this as a proven breach."
        )
    elif verifier_confirms_facts and not challenges and not gaps:
        decision = "supported_for_human_review"
        rationale = (
            "The available evidence supports the reported facts and no unresolved challenge was returned. "
            "This is not an automatic legal conclusion; human review is still required."
        )
    elif has_event_evidence and not all_quotes_verified:
        decision = "event_supported_contract_basis_unverified"
        rationale = (
            "An event is present, but the quoted contractual basis did not pass citation verification. "
            "Request corrected source evidence before recommending a contractual conclusion."
        )
    else:
        decision = "insufficient_evidence"
        rationale = (
            "The evidence does not establish the claim to the required threshold. Preserve the uncertainty "
            "and request the specific missing source records instead of asserting breach or liability."
        )
    action_type, subject = _action_for_finding(contract_id, finding)
    body = _draft_body(contract_id, finding, verification, gaps)
    confidence = 0.85 if decision == "supported_for_human_review" else 0.65 if decision == "partially_supported_unresolved" else 0.45
    draft = {
        "type": action_type,
        "subject": subject,
        "body": body,
        "citations": citations,
        "evidence_gaps": gaps,
        "confidence": confidence,
        "human_approval_required": True,
        "status": "draft_only_not_sent",
        "finding_id": finding.get("id") or finding.get("finding_id"),
    }
    return {
        "agent": "Tyr", "contract_id": contract_id,
        "finding_id": finding.get("id") or finding.get("finding_id"),
        "decision": decision, "rationale": rationale,
        "approved_facts": supports if all_quotes_verified else [],
        "unproven_claims": [finding.get("claim", "The risk interpretation remains unproven.")],
        "evidence_gaps": gaps,
        "verification_status": verification.get("status", "unknown"),
        "disagreement": {
            "loki_claim": finding.get("claim"),
            "heimdall_supports": supports,
            "heimdall_challenges": challenges,
            "resolved_by_tyr": decision,
        },
        "confidence": confidence, "action_draft": draft,
        "human_approval_required": True,
    }


def _action_for_finding(contract_id: str, finding: dict[str, Any]) -> tuple[str, str]:
    category = str(finding.get("category", "")).casefold()
    title = str(finding.get("title", category.replace("_", " ").title()))
    if "renew" in category:
        return "renewal_review", f"Review renewal and notice requirements for {contract_id}"
    if "terminat" in category or "cure" in category:
        return "termination_review", f"Review termination and cure-period language for {contract_id}"
    if "penalty" in category or "interest" in category or "financial" in category:
        return "financial_escalation_memo", f"Validate the penalty or financial trigger in {contract_id}"
    if "notice" in category or "incident" in category:
        return "evidence_request", f"Confirm notice timing and delivery evidence for {contract_id}"
    if "liability" in category or "indemn" in category:
        return "legal_review_memo", f"Review liability allocation in {contract_id}"
    if "compliance" in category or "privacy" in category or "security" in category:
        return "compliance_review_memo", f"Review compliance obligations in {contract_id}"
    return "clause_review", f"Review {title.lower()} in {contract_id}"


def _draft_body(
    contract_id: str, finding: dict[str, Any], verification: dict[str, Any], gaps: list[Any]
) -> str:
    citations = list(finding.get("citations") or [])
    clause_refs = [
        f"{c.get('document_id', contract_id)} {c.get('clause_reference', 'source clause')}"
        for c in citations if isinstance(c, dict)
    ]
    references = ", ".join(dict.fromkeys(clause_refs)) or f"the relevant source clause in {contract_id}"
    gap_text = "; ".join(str(g) for g in gaps[:5]) or "the applicable trigger and performance evidence"
    title = str(finding.get("title") or finding.get("category") or "contractual issue")
    return (
        f"Subject to human review, please provide the records needed to assess {title.lower()} under "
        f"{references}. Specifically, please provide evidence addressing: {gap_text}. "
        "This request does not assert that a breach or liability has been established."
    )


def arbitrate_contract_review(contract_id: str, findings: list[dict[str, Any]],
                              verification: dict[str, Any]) -> dict[str, Any]:
    """Produce qualified per-contract rulings and draft-only actions."""
    verified_by_id = {item.get("finding_id"): item for item in verification.get("findings", [])}
    rulings = [
        arbitrate_contract_finding(contract_id, finding, verified_by_id.get(finding.get("id"), {
            "status": "unverified", "supports": [], "challenges": [
                "No matching verification record was returned for this finding."
            ], "evidence_gaps": ["Heimdall verification result missing."]
        }))
        for finding in findings
    ]
    return {
        "agent": "Tyr", "contract_id": contract_id, "rulings": rulings,
        "status": "complete_with_human_review" if rulings else "no_ruling_candidates",
    }
