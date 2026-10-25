"""Tyr: evidence arbitration and human-approved contract action drafting.

Rulings are evidence-qualified, not legal determinations. Consequential drafts are
never sent or executed by this module; a human must review and approve them.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _citation_records(finding: dict[str, Any], verification: dict[str, Any]) -> list[dict[str, Any]]:
    checks = verification.get("citation_results") or []
    source_by_quote = {_text(item.get("quote")): item for item in checks if isinstance(item, dict)}
    result = []
    for item in finding.get("citations") or []:
        if not isinstance(item, dict):
            continue
        quote = _text(item.get("quote"))
        check = source_by_quote.get(quote, {})
        result.append({
            "document_id": _text(item.get("document_id") or check.get("document_id")),
            "clause_reference": _text(item.get("clause_reference") or check.get("clause_reference")),
            "quote": quote,
            "verified": bool(check.get("verified", item.get("verified", False))),
            "verification_note": _text(check.get("verification_note")),
        })
    return result


def _action_for_finding(finding: dict[str, Any]) -> tuple[str, str]:
    category = _text(finding.get("category")).casefold()
    title = _text(finding.get("title") or category.replace("_", " ").title())
    if "renew" in category:
        return "renewal_notice", "Renewal / non-renewal notice — review required"
    if "terminat" in category or "cure" in category or "default" in category:
        return "termination_notice", "Termination / cure notice — review required"
    if any(word in category for word in ("incident", "notice_obligation", "security", "privacy", "breach")):
        return "potential_breach_notice", "Potential breach / incident notice — facts must be verified"
    if any(word in category for word in ("ambigu", "unilateral", "exclusivity", "conflict", "liability", "indemn")):
        return "amendment_proposal", "Proposed contractual amendment — negotiation draft"
    if any(word in category for word in ("penalty", "interest", "financial", "payment", "compliance")):
        return "escalation_memo", "Internal escalation memo — review required"
    return "escalation_memo", f"Internal review memo: {title}"


def _render_action_body(
    contract_id: str, finding: dict[str, Any], citations: list[dict[str, Any]],
    gaps: list[Any], verification: dict[str, Any], action_type: str,
) -> str:
    title = _text(finding.get("title") or finding.get("category") or "contractual issue")
    verified = [c for c in citations if c.get("verified") and c.get("quote")]
    clause_lines = []
    for c in citations:
        reference = " ".join(part for part in (c.get("document_id") or contract_id, c.get("clause_reference") or "clause reference not identified") if part)
        quote = c.get("quote") or "[Exact clause quotation not available]"
        state = "EXACT QUOTE VERIFIED" if c.get("verified") else "UNVERIFIED — DO NOT RELY ON THIS QUOTE"
        clause_lines.append(f'- {reference} [{state}]: “{quote}”')
    clause_block = "\n".join(clause_lines) if clause_lines else f"- {contract_id}: [Exact clause reference and quote must be added before sending]"
    gap_text = "\n".join(f"- {str(gap)}" for gap in gaps[:8]) or "- Confirm operative version, trigger, dates, exceptions, and supporting records."
    events = verification.get("mapped_events") or []
    event_lines = "\n".join(
        f'- {_text(e.get("event_id") or "Event")} ({_text(e.get("timestamp") or "date not supplied")}): {_text(e.get("body") or e.get("event_quote"))}'
        for e in events[:5] if isinstance(e, dict)
    ) or "- No corroborating event was mapped in the supplied feed."
    if action_type == "renewal_notice":
        opening = (
            "To: [Counterparty notice recipient]\n"
            "Subject: [Renewal / non-renewal] notice regarding [Agreement name]\n\n"
            "Dear [Counterparty],\n\n"
            "We are writing regarding the agreement identified below. Subject to confirmation of the operative agreement, "
            "notice period, delivery method, and authorized signatory, [Company] intends to [renew / not renew] the agreement "
            "effective [date]. Please confirm receipt and the resulting term dates.\n\n"
        )
    elif action_type == "termination_notice":
        opening = (
            "To: [Contractually designated recipient]\n"
            "Subject: Notice concerning [Agreement name] — proposed action subject to review\n\n"
            "Dear [Counterparty],\n\n"
            "We request your attention to the issue described below. Before this notice is sent, counsel must confirm the "
            "operative termination/cure clause, required notice method, cure period, trigger facts, and any amendment or waiver. "
            "The current draft does not itself exercise a termination right. [Insert verified facts, dates, and requested cure.]\n\n"
        )
    elif action_type == "potential_breach_notice":
        opening = (
            "To: [Contractually designated recipient]\n"
            "Subject: Request for information regarding a potential contractual issue under [Agreement name]\n\n"
            "Dear [Counterparty],\n\n"
            "We are reviewing a reported matter that may relate to the agreement. Based on the records currently available, "
            "we have not concluded that a breach occurred. Please provide the following information and relevant records by "
            "[proposed date, subject to contractual and legal review]: [insert verified event facts and specific request].\n\n"
        )
    elif action_type == "amendment_proposal":
        opening = (
            "NON-BINDING NEGOTIATION DRAFT — NOT AN EXECUTED AMENDMENT\n"
            "To: [Counterparty contact]\n"
            "Subject: Proposed amendment to [Agreement name]\n\n"
            "Dear [Counterparty],\n\n"
            "To improve clarity and reduce operational uncertainty, we propose discussing the following changes, subject to "
            "mutual agreement and legal review: (1) define [ambiguous term / trigger]; (2) specify objective notice, cure, "
            "and response periods; (3) clarify exceptions, responsibilities, and evidence requirements; and (4) state the "
            "order of precedence with existing amendments. No change is effective unless documented and signed by authorized parties.\n\n"
        )
    else:
        opening = (
            "INTERNAL — PRIVILEGED STATUS NOT IMPLIED; HANDLE UNDER COMPANY POLICY\n"
            f"To: [Legal / Contract Owner / Finance]\nSubject: Escalation memo — {title}\n\n"
            "Decision requested: review the evidence and determine the appropriate next step. Do not assert breach, liability, "
            "or a payable amount solely from automated matching.\n\n"
        )
    body = (
        opening
        + f"Agreement / contract ID: {contract_id}\nIssue under review: {title}\n\n"
        + "Relevant source clauses (citation status shown per quotation):\n" + clause_block + "\n\n"
        + "Current evidence / event records (provenance may be unverified):\n" + event_lines + "\n\n"
        + "Open facts and checks required before approval:\n" + gap_text + "\n\n"
        + "Requested review: confirm the operative clause and amendment precedence, validate all dates and event sources, "
        "check contractual notice requirements and exceptions, complete placeholders, and approve the final text before use.\n"
        "Prepared by Tyr as a draft only. Human approval is mandatory. This draft has not been sent."
    )
    # A sendable notice must not masquerade as verified when its clause citation is missing.
    if not verified:
        body += "\n\nBLOCKER: No exact contractual quotation has passed verification. Do not send until corrected."
    return body


def arbitrate_contract_finding(
    contract_id: str, finding: dict[str, Any], verification: dict[str, Any]
) -> dict[str, Any]:
    """Resolve Loki/Heimdall disagreement and create a cited, approval-gated draft."""
    citations = _citation_records(finding, verification)
    has_citations = bool(citations)
    all_quotes_verified = has_citations and all(c.get("verified") and c.get("quote") for c in citations)
    supports = list(verification.get("supports") or [])
    challenges = list(verification.get("challenges") or [])
    gaps = list(dict.fromkeys(
        list(finding.get("evidence_gaps") or []) + list(verification.get("evidence_gaps") or [])
    ))
    event_evidence = list(verification.get("mapped_events") or verification.get("event_evidence") or [])
    has_events = bool(event_evidence)
    if not has_citations or not all_quotes_verified:
        decision = "challenged_insufficient_citation_evidence"
        rationale = "Heimdall could not verify every cited clause against canonical contract text. Loki's interpretation remains unsubstantiated until exact source wording is corrected."
        gaps.append("Verify the exact quotation and operative clause reference against the canonical agreement.")
    elif has_events and supports:
        decision = "partially_supported_unresolved"
        rationale = "The clause quotation is verified and related event text exists, but event authenticity, contractual trigger, causation, exceptions, and breach are not established by the match. Treat Loki's claim as a qualified risk requiring human review."
    else:
        decision = "insufficient_evidence"
        rationale = "The contractual wording is verifiable, but the current evidence does not establish the relevant event or trigger. Preserve the risk as a hypothesis; do not assert breach or liability."
        if not has_events:
            gaps.append("Obtain event, delivery, performance, or notice records that can confirm whether the contractual trigger occurred.")
    gaps = list(dict.fromkeys(str(g) for g in gaps if str(g).strip()))
    action_type, subject = _action_for_finding(finding)
    confidence = 0.88 if all_quotes_verified and has_events and supports and not gaps else 0.72 if all_quotes_verified and has_events else 0.55 if all_quotes_verified else 0.30
    confidence = max(0.0, min(0.99, confidence - min(0.20, max(0, len(gaps) - 1) * 0.025)))
    finding_id = _text(finding.get("id") or finding.get("finding_id")) or f"{contract_id}:finding"
    action_id = f"{contract_id}:action:" + hashlib.sha256(f"{contract_id}|{finding_id}|{action_type}".encode("utf-8")).hexdigest()[:16]
    body = _render_action_body(contract_id, finding, citations, gaps, verification, action_type)
    draft = {
        "id": action_id, "action_id": action_id, "type": action_type, "subject": subject,
        "title": subject, "body": body, "citations": citations, "clause_references": [
            {"document_id": c.get("document_id"), "clause_reference": c.get("clause_reference"),
             "quote": c.get("quote"), "verified": bool(c.get("verified"))} for c in citations
        ],
        "evidence_gaps": gaps, "confidence": round(confidence, 2),
        "confidence_label": "high" if confidence >= 0.8 else "moderate" if confidence >= 0.55 else "low",
        "human_approval_required": True, "approval_status": "pending_human_approval",
        "status": "draft_only_not_sent", "finding_id": finding_id,
        "blockers": ["Unverified or missing source citation"] if not all_quotes_verified else [],
        "consequential_action_executed": False,
    }
    return {
        "agent": "Tyr", "contract_id": contract_id, "finding_id": finding_id,
        "decision": decision, "rationale": rationale, "approved_facts": supports if all_quotes_verified else [],
        "unproven_claims": [_text(finding.get("claim") or finding.get("reason")) or "The risk interpretation remains unproven."],
        "evidence_gaps": gaps, "verification_status": verification.get("status", "unknown"),
        "disagreement": {
            "loki_claim": finding.get("claim") or finding.get("reason"),
            "loki_severity": finding.get("severity", "unknown"),
            "loki_likelihood": finding.get("likelihood", "indeterminate"),
            "heimdall_supports": supports, "heimdall_challenges": challenges,
            "citation_checks": citations, "event_evidence": event_evidence,
            "resolved_by_tyr": decision,
        },
        "confidence": round(confidence, 2), "confidence_label": draft["confidence_label"],
        "action_draft": draft, "human_approval_required": True,
        "approval_status": "pending_human_approval",
        "notice": "Tyr's ruling is a qualified evidence assessment, not legal advice or a determination of breach.",
    }


def arbitrate(finding: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    ruling = arbitrate_contract_finding(str(finding.get("contract_id") or "A1"), finding, verification)
    ruling["ruling_id"] = finding.get("finding_id") or "ruling-" + str(ruling.get("contract_id", "unknown"))
    ruling["rejected_or_unproven_claims"] = ruling.get("unproven_claims", [])
    return ruling


def arbitrate_contract_review(contract_id: str, findings: list[dict[str, Any]],
                              verification: dict[str, Any]) -> dict[str, Any]:
    """Produce stable per-finding rulings and approval-gated actions."""
    verified_by_id = {item.get("finding_id"): item for item in verification.get("findings", [])}
    rulings = [
        arbitrate_contract_finding(contract_id, finding, verified_by_id.get(finding.get("id"), {
            "status": "unverified", "supports": [],
            "challenges": ["No matching verification record was returned for this finding."],
            "evidence_gaps": ["Heimdall verification result missing."],
        }))
        for finding in findings
    ]
    return {
        "agent": "Tyr", "contract_id": contract_id, "rulings": rulings,
        "status": "complete_with_human_review" if rulings else "no_ruling_candidates",
        "summary": {
            "rulings": len(rulings),
            "supported_or_partial": sum(item["decision"] == "partially_supported_unresolved" for item in rulings),
            "challenged": sum(item["decision"] != "partially_supported_unresolved" for item in rulings),
            "actions_pending_approval": sum(item["human_approval_required"] for item in rulings),
            "low_confidence": sum(item["confidence"] < 0.55 for item in rulings),
        },
    }
