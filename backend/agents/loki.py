import json
import re

from backend.claude_client import ask_claude
from backend.config import USE_CLAUDE

SYSTEM = (
    "You are Loki, an adversarial contract reviewer. Read each clause as the counterparty's lawyer. "
    "Distinguish source facts, legal interpretation, and unknown trigger facts. Never assert breach from "
    "keywords alone. Return JSON with title, claim, attack_path, severity, likelihood, evidence_gaps, citations."
)


def review(extraction, events, use_claude=False):
    event = next((e for e in events if e.get("event_id") == "E-04"), None)
    body = (event or {}).get("body", "")
    citation = next(
        (t.get("citation") for t in extraction.get("extracted_terms", [])
         if t.get("category") == "incident_notice" and t.get("citation")),
        None,
    )
    if use_claude and USE_CLAUDE:
        try:
            result = json.loads(ask_claude(
                SYSTEM,
                "Adversarially assess the incident-notice risk. Return JSON only.\nEXTRACTION:"
                + json.dumps(extraction) + "\nEVENT:" + body,
                1200,
            ))
            result.update({"agent": "Loki", "mode": "claude"})
            result.setdefault("severity_rationale", "LLM-proposed severity; human review required.")
            result.setdefault("likelihood_rationale", "Qualitative assessment only; not a calibrated probability.")
            result.setdefault("requires_clarification", bool(result.get("evidence_gaps")))
            return result
        except Exception:
            pass
    return {
        "agent": "Loki", "mode": "deterministic_fallback",
        "finding_id": "risk-a1-notice-timing",
        "title": "Potential gap in upstream incident-notice evidence",
        "claim": "The March 3 outage is documented, but the event record does not establish when StratoNode became aware or when it notified Quillhub Operations. A notice-timing breach is not proven.",
        "attack_path": [
            "A1 Section I.1 states a four-hour notification expectation measured from provider awareness.",
            "E-04 documents a 190-minute unplanned outage; outage duration alone does not establish provider-awareness or notice-delivery time.",
            "Compare provider awareness time and delivery/receipt time against the contractual trigger, including exceptions and counting rules.",
            "Request incident-awareness and notification delivery logs before alleging breach.",
        ],
        "severity": "medium",
        "severity_rationale": "A notice failure could affect incident response, but the supplied evidence does not establish breach or resulting loss.",
        "likelihood": "indeterminate",
        "likelihood_rationale": "Cannot estimate likelihood from outage duration alone; the two decisive timestamps are missing.",
        "evidence_gaps": [
            "Provider awareness timestamp",
            "Timestamp and delivery/receipt evidence for notice to ops@quillhub.io",
            "Any contractual exception or alternative notice method relied upon",
        ],
        "citations": [citation] if citation else [],
        "requires_clarification": True,
        "clarification_requests": [{
            "from": "Loki", "to": "Thor", "type": "targeted_reextraction_request",
            "reason": "Locate the exact notice trigger, exceptions, and source evidence for awareness and notice-delivery timestamps.",
            "requested_evidence": ["A1 Section I.1 full clause context", "incident awareness logs", "notice delivery/receipt logs"],
        }],
    }


def _likelihood_assessment(category, quote, confidence, verified):
    """Qualitative likelihood of a material dispute/risk, not a statistical probability."""
    text = quote.casefold()
    strong_trigger = bool(re.search(
        r"\b(shall not|must not|may not|penalty|liquidated damages|late fee|indemnif|automatic(?:ally)? renew|exclusive)\b",
        text,
    ))
    numeric_trigger = bool(re.search(r"\b\d+\s*(?:days?|hours?|%|months?)\b", text))
    if not verified or confidence is None or confidence < 0.55:
        return "indeterminate", "Source verification or extraction confidence is insufficient to rate likelihood."
    if strong_trigger and numeric_trigger:
        return "elevated", "The verified excerpt contains operative or consequence-bearing language and an explicit threshold; trigger facts and scope remain unverified."
    if strong_trigger:
        return "moderate", "The verified excerpt contains potentially operative risk language, but applicability and trigger facts remain unverified."
    return "indeterminate", "A topical clause mention alone does not support a defensible likelihood estimate."


def review_contract_candidates(contract_id, source, extraction):
    """Source-grounded adversarial triage with clause evidence, attack path, scoring and Thor requests."""
    rules = [
        ("renewal", r"\b(auto(?:matic)?[- ]renew|renewal|renew|non[- ]renewal)\b", "medium"),
        ("termination", r"\b(termination|terminate|cure period|default)\b", "medium"),
        ("penalty_or_interest", r"\b(penalty|liquidated damages|interest rate|late fee)\b", "high"),
        ("liability_or_indemnity", r"\b(indemnif\w*|limitation of liability|liability cap|consequential damages)\b", "medium"),
        ("notice_obligation", r"\b(notice period|written notice|notify within|notification within)\b", "medium"),
        ("exclusivity_or_conflict", r"\b(exclusive|exclusivity|conflict of terms|inconsistent with)\b", "medium"),
        ("payment", r"\b(payment terms?|invoice|billing|remittance|amounts? due|net\s+\d+|pay within|purchase order)\b", "medium"),
        ("delivery_performance", r"\b(deliver(?:y|ies)?|shipment|service level|\bSLA\b|uptime|downtime|availability|performance standard|milestone)\b", "medium"),
        ("data_security", r"\b(data breach|security incident|unauthorized access|personal data|cybersecurity|security measures|data protection)\b", "high"),
        ("confidentiality", r"\b(confidential(?:ity)?|non-disclosure|trade secret|proprietary information)\b", "medium"),
        ("force_majeure", r"\bforce majeure\b|beyond (?:a party's|either party's) reasonable control", "medium"),
        ("compliance", r"\b(comply|compliance|regulatory|applicable law|audit right)\b", "medium"),
    ]
    terms_by_quote = {
        str((term.get("citation") or {}).get("quote", "")): term
        for term in extraction.get("extracted_terms", [])
    }
    findings, clarification_requests = [], []
    for line_no, raw in enumerate(source.splitlines(), start=1):
        for category, pattern, severity in rules:
            if not re.search(pattern, raw, re.I):
                continue
            term = terms_by_quote.get(raw, {})
            supplied_citation = term.get("citation") or {}
            verified = bool(raw and raw in source and supplied_citation.get("verified", True))
            citation = dict(supplied_citation or {
                "document_id": contract_id, "clause_reference": f"line {line_no}",
                "quote": raw, "verified": verified,
                "verification_note": "Exact source line; legal effect requires review.",
            })
            citation.update({"document_id": contract_id, "line_number": line_no, "quote": citation.get("quote") or raw})
            confidence = term.get("confidence")
            if not isinstance(confidence, (int, float)):
                confidence = 0.65 if verified else 0.0
            likelihood, likelihood_rationale = _likelihood_assessment(category, raw, confidence, verified)
            gaps = [
                "Confirm operative clause context, exceptions, and amendments.",
                "Confirm the triggering facts and whether the clause applies to these parties and this transaction.",
            ]
            finding = {
                "id": f"{contract_id}:{category}:{line_no}", "contract_id": contract_id,
                "category": category, "title": category.replace("_", " ").title(),
                "severity": severity,
                "severity_rationale": (
                    "Potential financial, compliance, or operational consequence is material if the clause is triggered."
                    if severity == "high" else
                    "Potential commercial or operational impact warrants review; magnitude depends on scope and facts."
                ),
                "likelihood": likelihood, "likelihood_rationale": likelihood_rationale,
                "confidence": round(float(confidence), 3), "status": "candidate_requires_review",
                "claim": "A potentially relevant contractual provision was identified; applicability and legal effect require review.",
                "reason": "Keyword-based source triage; this is not a finding of breach.",
                "attack_path": [
                    f"Source line {line_no} contains language associated with {category.replace('_', ' ')}.",
                    "Read the full clause with definitions, exceptions, remedies, incorporated terms, and amendment/precedence provisions.",
                    "Test the counterparty's strongest defense: different scope, untriggered condition, timely cure, exception, or controlling amendment.",
                    "Verify the material facts and quantify impact only from supported contractual and transaction evidence.",
                ],
                "evidence_gaps": gaps,
                "citations": [citation], "evidence": citation,
                "agent": "Loki", "mode": "deterministic_source_triage",
                "requires_clarification": (not verified or float(confidence) < 0.55),
            }
            findings.append(finding)
            if finding["requires_clarification"]:
                clarification_requests.append({
                    "from": "Loki", "to": "Thor", "type": "targeted_reextraction_request",
                    "contract_id": contract_id, "line_number": line_no,
                    "reason": "Evidence is unverified or extraction confidence is below 0.55.",
                    "requested_evidence": ["Exact clause quotation and clause heading", "surrounding paragraph and defined terms", "related amendment/precedence text"],
                })
    return {
        "agent": "Loki", "contract_id": contract_id, "findings": findings,
        "clarification_requests": clarification_requests,
        "notice": "Severity is a triage category; likelihood is qualitative and not a calibrated probability. Findings are not proven breaches.",
    }
