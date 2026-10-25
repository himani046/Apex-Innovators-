"""Phase 2: source-grounded multi-contract workstreams.

This module deliberately avoids applying A1-specific assumptions to other
contracts. Dates, amounts, candidate obligations and risk signals are derived
from each document's own verbatim lines and are marked for human review.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from backend.agents.thor_portfolio import extract_contract_candidates
from backend.services.citations import verify_all

IN_SCOPE = ("A1", "B1", "B2", "C1", "D1")
DATE_PATTERNS = (
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b", re.I),
    re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b", re.I),
)
MONEY_RE = re.compile(r"(?i)(?:USD\s*)?\$\s?[\d,]+(?:\.\d{2})?|\b(?:\d[\d,]*\.\d{2})\s*(?:U\.S\.\s*)?Dollars?\b")
RISK_CATEGORIES = {
    "notice": re.compile(r"\b(notice|notify|notification|within \d+ (?:hours?|days?))\b", re.I),
    "security_and_privacy": re.compile(r"\b(data breach|personal data|security|subprocessor|vulnerabilit|access log|delet(?:e|ion))\b", re.I),
    "financial": re.compile(r"\b(fee|payment|invoice|interest|service credit|credit cap|reimburse|\$\s?[\d,]+)\b", re.I),
    "renewal_and_termination": re.compile(r"\b(renewal|non-renewal|terminat|expire|expiration)\b", re.I),
    "performance_and_acceptance": re.compile(r"\b(acceptance|deliverable|milestone|uptime|service level|root-cause|remediate)\b", re.I),
    "liability_and_ip": re.compile(r"\b(liabilit|indemnif|intellectual property|work product|open-source)\b", re.I),
    "exclusivity": re.compile(r"\b(exclusive|exclusivity|non-compete)\b", re.I),
}


def _citation(doc_id: str, source: str, line_no: int, quote: str, heading: str = "Source line") -> dict[str, Any]:
    return {
        "document_id": doc_id,
        "clause_reference": heading,
        "quote": quote,
        "line_number": line_no,
        "verified": bool(quote and quote in source),
        "verification_note": "Exact source line matched." if quote and quote in source else "Source line could not be verified.",
    }


def _heading_for(lines: list[str], index: int) -> str:
    for i in range(index, max(-1, index - 9), -1):
        text = lines[i].strip()
        if text and len(text) < 130 and (
            re.match(r"^(?:SECTION|Section|ARTICLE|Article|EXHIBIT|Exhibit|§|[A-H]\.\s)", text)
            or (text == text.upper() and any(ch.isalpha() for ch in text) and len(text) > 5)
        ):
            return text
    return "Source line"


def _extract_dates(doc_id: str, source: str, as_of: str) -> list[dict[str, Any]]:
    lines = source.splitlines()
    found = []
    seen = set()
    for index, raw in enumerate(lines):
        for pattern in DATE_PATTERNS:
            match = pattern.search(raw)
            if not match:
                continue
            date_text = match.group(0).replace(",", "")
            normalized = None
            for fmt in ("%Y-%m-%d", "%B %d %Y", "%d %B %Y"):
                try:
                    normalized = date.fromisoformat(date_text) if fmt == "%Y-%m-%d" else datetime.strptime(date_text, fmt).date().isoformat()
                    break
                except (ValueError, AttributeError):
                    pass
            # Only exact calendar dates are timeline milestones; relative windows
            # remain extracted obligations, not guessed dates.
            if not normalized or (doc_id, normalized, raw.strip()) in seen:
                continue
            seen.add((doc_id, normalized, raw.strip()))
            found.append({
                "date": normalized,
                "title": raw.strip(),
                "status": "past" if normalized < as_of else "upcoming" if normalized > as_of else "today",
                "evidence": _citation(doc_id, source, index + 1, raw, _heading_for(lines, index)),
            })
    return sorted(found, key=lambda item: (item["date"], item["title"]))


def _financial_exposure(doc_id: str, source: str) -> dict[str, Any]:
    amounts = []
    seen = set()
    for index, raw in enumerate(source.splitlines(), start=1):
        for match in MONEY_RE.finditer(raw):
            value = match.group(0).strip()
            if value.casefold() in seen:
                continue
            seen.add(value.casefold())
            amounts.append({
                "amount_text": value,
                "context": raw.strip(),
                "evidence": _citation(doc_id, source, index, raw, "Financial term"),
                "interpretation": "Source-stated amount; not summed into exposure because payment trigger, period, or applicability may differ.",
            })
    return {
        "amounts_found": amounts,
        "calculated_total_usd": None,
        "calculation_status": "not_calculated_without_invoice_or_trigger_evidence",
        "note": "Values are quoted from the contract. They are not additive exposure estimates.",
    }


def _risk_findings(doc_id: str, source: str, candidates: dict[str, Any]) -> list[dict[str, Any]]:
    lines = source.splitlines()
    findings = []
    seen = set()
    for term in candidates.get("extracted_terms", []):
        quote = (term.get("citation") or {}).get("quote", "")
        if not quote:
            continue
        categories = [name for name, pattern in RISK_CATEGORIES.items() if pattern.search(quote)]
        for category in categories[:2]:
            key = (category, quote)
            if key in seen:
                continue
            seen.add(key)
            citation = dict(term["citation"])
            findings.append({
                "finding_id": f"{doc_id.lower()}-{category}-{len(findings) + 1}",
                "category": category,
                "title": f"Review {category.replace('_', ' ')} provision",
                "claim": "This source line identifies a contract term requiring operational tracking or clause-level review; it does not establish breach or loss.",
                "severity": "unassessed",
                "status": "candidate_for_review",
                "evidence": citation,
                "verification_status": "verified" if citation.get("verified") else "unverified",
                "recommended_action": "Assign an owner, confirm applicability and triggering facts, and record evidence before drawing a conclusion.",
                "human_review_required": True,
            })
    return findings


def _related_documents(doc_id: str, graph: dict[str, Any], all_docs: set[str]) -> list[dict[str, str]]:
    related = []
    for edge in graph.get("edges", []):
        if edge.get("source") == doc_id:
            related.append({"document_id": edge["target"], "relationship": edge["relation"]})
        elif edge.get("target") == doc_id:
            related.append({"document_id": edge["source"], "relationship": "related_by_" + edge["relation"]})
    # A1 dependency set includes its explicit amendment and incorporated documents.
    if doc_id == "A1":
        for target in ("A2", "A3", "STD"):
            if target in all_docs and not any(r["document_id"] == target for r in related):
                related.append({"document_id": target, "relationship": "dependency_candidate_requires_review"})
    return sorted(related, key=lambda item: (item["document_id"], item["relationship"]))


def _events_for_contract(doc_id: str, customer_terms: list[str], events: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    matched = []
    terms = [x.casefold() for x in customer_terms if x]
    for event in events:
        stamp = str(event.get("timestamp", ""))
        if stamp[:10] and stamp[:10] > as_of:
            continue
        text = (str(event.get("body", "")) + " " + str(event.get("summary", ""))).casefold()
        if any(term in text for term in terms):
            matched.append(event)
    return matched


def build_workstreams(contracts: dict[str, str], graph: dict[str, Any], reconciliation: dict[str, Any],
                      event_drops: dict[str, list[dict[str, Any]]], as_of: str) -> dict[str, Any]:
    """Create independently grounded workstreams for each in-scope contract."""
    as_of_date = date.fromisoformat(as_of)
    in_scope = [doc for doc in IN_SCOPE if doc in contracts]
    # A1 workstream intentionally gathers its related dependency documents without
    # pretending the other documents share A1's terms.
    specs = [
        ("contract-A1", "A1 + related documents", ["A1"], "Analyze A1 provisions and its amendment/incorporation dependencies."),
        ("contract-B1", "B1", ["B1"], "Analyze Harbor Retail obligations, risks, deadlines, and exposure."),
        ("contract-B2", "B2", ["B2"], "Analyze the Harbor Retail data-processing and security addendum."),
        ("contract-C1", "C1", ["C1"], "Analyze Vantage Logistics obligations, risks, deadlines, and exposure."),
        ("contract-D1", "D1", ["D1"], "Analyze the independent-contractor agreement and statement-of-work milestones."),
    ]
    all_docs = set(contracts)
    all_events = []
    for events in event_drops.values():
        all_events.extend(events)
    workstreams = []
    for workstream_id, label, roots, responsibility in specs:
        root = roots[0]
        source = contracts[root]
        candidates = extract_contract_candidates(root, source, max_terms=80)
        citations = [term.get("citation", {}) for term in candidates.get("extracted_terms", [])]
        verified = sum(bool(c.get("verified")) for c in citations)
        related = _related_documents(root, graph, all_docs)
        # For B1 and B2, preserve the explicit parent/addendum relationship in both
        # workstreams while each workstream's own obligations remain source-specific.
        related_ids = [item["document_id"] for item in related]
        if root == "B1" and "B2" in all_docs and "B2" not in related_ids:
            related.append({"document_id": "B2", "relationship": "supplemented_by_addendum"})
        if root == "B2" and "B1" in all_docs and "B1" not in related_ids:
            related.append({"document_id": "B1", "relationship": "supplements_agreement"})
        customer_terms = []
        for pattern in (r"between\s+(.+?)\s+\(\"Provider\"\)\s+and\s+(.+?)\s+\(\"Customer\"\)",
                        r"between\s+(.+?)\s+and\s+(.+?)\s+\(\"Contractor\"\)"):
            match = re.search(pattern, source, re.I | re.S)
            if match:
                customer_terms.extend([part.strip().strip('"') for part in match.groups()])
        # Match event references only when the event body explicitly names a party,
        # contract ID, or document ID. No generic A1 event is copied to other deals.
        ids = [root] + [item["document_id"] for item in related]
        explicit_ids = [v for v in ids if v in all_docs]
        event_matches = _events_for_contract(root, customer_terms + explicit_ids, all_events, as_of)
        deadlines = _extract_dates(root, source, as_of_date)
        risk_findings = _risk_findings(root, source, candidates)
        workstreams.append({
            "id": workstream_id,
            "label": label,
            "contract_ids": [root],
            "related_documents": sorted(related, key=lambda item: (item["document_id"], item["relationship"])),
            "responsibility": responsibility,
            "status": "complete_with_review_items",
            "agents": {"Thor": "complete", "Norns": "source_dates_extracted", "Loki": "candidate_risks_flagged",
                       "Heimdall": "citation_and_event_evidence_checked", "Tyr": "recommendations_draft_only"},
            "extracted_obligations": candidates.get("extracted_terms", []),
            "deadlines": deadlines,
            "financial_exposure": _financial_exposure(root, source),
            "evidence_references": citations,
            "citation_verification": {"total": len(citations), "verified": verified, "failed": len(citations) - verified},
            "risk_findings": risk_findings,
            "verification": {
                "status": "verified_source_quotes_with_unassessed_legal_effect" if verified == len(citations) else "some_quotes_need_review",
                "events_matched": len(event_matches),
                "matched_events": event_matches,
                "note": "Only source quote integrity is verified here. No contract breach is inferred from absence of an event match.",
            },
            "recommended_actions": [
                {"action": "Assign an accountable owner for each extracted obligation and explicit date.", "status": "draft_recommendation", "human_approval_required": True},
                {"action": "Confirm operational records for relative deadlines and event-triggered obligations.", "status": "draft_recommendation", "human_approval_required": True},
            ],
            "unresolved_questions": [
                "Which extracted candidate lines are binding obligations after considering the full agreement and any applicable amendments?",
                "Which event, invoice, acceptance, or awareness records establish whether a deadline or payment trigger has occurred?",
            ],
            "source_notice": "Evidence triage, not legal advice. Keyword candidates are not final legal interpretations.",
        })

    portfolio = build_portfolio_summary(contracts, graph, reconciliation, workstreams)
    workstreams.append({
        "id": "portfolio-wide",
        "label": "Portfolio-wide",
        "contract_ids": sorted(set(portfolio["contracts_in_scope"])),
        "related_documents": [{"document_id": edge["target"], "relationship": edge["relation"]}
                              for edge in graph.get("edges", [])],
        "responsibility": "Identify cross-contract dependencies, shared controls, potential conflicts, and portfolio-level review questions.",
        "status": "complete_with_review_items",
        "agents": {"Thor": "portfolio_evidence_scanned", "Norns": "cross_contract_dates_not_aggregated",
                   "Loki": "potential_shared_risks_flagged", "Heimdall": "relationship_evidence_checked",
                   "Tyr": "portfolio_actions_draft_only"},
        "extracted_obligations": [],
        "deadlines": [],
        "financial_exposure": {"amounts_found": [], "calculated_total_usd": None,
                               "calculation_status": "not_calculated_without_invoice_or_trigger_evidence",
                               "note": "Portfolio totals are not calculated; contract values and periods are not directly additive."},
        "evidence_references": [edge.get("evidence", {}) for edge in graph.get("edges", [])],
        "citation_verification": graph.get("citation_validation", {"total": 0, "verified": 0, "failed": 0}),
        "risk_findings": portfolio["shared_risk_signals"],
        "verification": {"status": "source_links_checked_review_required",
                         "events_matched": 0, "matched_events": [],
                         "note": "Potential portfolio conflicts are not proven without validating facts and legal scope."},
        "recommended_actions": portfolio["recommended_actions"],
        "unresolved_questions": portfolio["unresolved_questions"],
        "source_notice": portfolio["notice"],
        "portfolio_summary": portfolio,
    })
    return {
        "as_of_date": as_of,
        "scope": in_scope,
        "workstreams": workstreams,
        "portfolio_summary": portfolio,
        "status": "complete_with_review_items",
        "notice": "Portfolio-wide findings are source-grounded review signals. They do not establish legal conflicts or breaches without human validation.",
    }


def build_portfolio_summary(contracts: dict[str, str], graph: dict[str, Any], reconciliation: dict[str, Any],
                            workstreams: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize shared risks and cross-document dependencies without asserting conflict."""
    shared_provider = []
    for doc_id, source in contracts.items():
        if re.search(r"Quillhub Inc\.", source, re.I) and doc_id in IN_SCOPE:
            shared_provider.append(doc_id)

    exclusivity = []
    for doc_id, source in contracts.items():
        if doc_id not in IN_SCOPE or not re.search(r"\b(exclusive|exclusivity)\b", source, re.I):
            continue
        for number, raw in enumerate(source.splitlines(), start=1):
            if re.search(r"\b(exclusive|exclusivity)\b", raw, re.I):
                exclusivity.append({
                    "document_id": doc_id,
                    "signal": "exclusivity_scope_review",
                    "claim": "Exclusivity language may need portfolio-level scope review; this line alone does not establish an actual conflict.",
                    "evidence": _citation(doc_id, source, number, raw, "Exclusivity"),
                    "human_review_required": True,
                })
    # A specific potential overlap is surfaced because B1 and C1 both address
    # Route Optimizer in Washington/Oregon but define different customer sectors.
    b1_text, c1_text = contracts.get("B1", ""), contracts.get("C1", "")
    potential_overlap = []
    if (re.search(r"Route Optimizer Enterprise", b1_text, re.I)
            and re.search(r"Route Optimizer platform", c1_text, re.I)
            and re.search(r"Washington and Oregon", b1_text, re.I)
            and re.search(r"Washington and Oregon", c1_text, re.I)):
        for doc_id, source in (("B1", b1_text), ("C1", c1_text)):
            for number, raw in enumerate(source.splitlines(), start=1):
                if re.search(r"exclusive|exclusivity", raw, re.I):
                    potential_overlap.append(_citation(doc_id, source, number, raw, "Exclusivity"))
                    break
    relationships = [
        {"source": edge.get("source"), "target": edge.get("target"), "relation": edge.get("relation"),
         "status": edge.get("status"), "evidence": edge.get("evidence")}
        for edge in graph.get("edges", [])
    ]
    return {
        "contracts_in_scope": [w["contract_ids"][0] for w in workstreams],
        "workstream_count": len(workstreams),
        "documents_loaded": len(contracts),
        "shared_provider_documents": shared_provider,
        "dependency_relationships": relationships,
        "amendment_reconciliation": reconciliation.get("summary", {}),
        "shared_risk_signals": [
            {
                "signal_id": "shared-provider-obligations",
                "title": "Shared provider obligations across Quillhub agreements",
                "documents": shared_provider,
                "description": "Operational controls for notices, billing, security, and delivery may be shared, but each agreement's timing and recipient requirements differ.",
                "recommended_action": "Maintain contract-specific obligation registers and validate each deadline against its own clause.",
                "evidence_status": "document_party_names_detected",
                "human_review_required": True,
            },
            {
                "signal_id": "exclusivity-scope-review",
                "title": "Route Optimizer exclusivity scope review",
                "documents": sorted({c["document_id"] for c in potential_overlap}),
                "description": "B1 and C1 contain exclusivity language involving Route Optimizer and Washington/Oregon; the defined customer sectors differ, so any overlap requires factual and legal review.",
                "evidence": potential_overlap,
                "human_review_required": True,
            } if potential_overlap else {
                "signal_id": "exclusivity-scope-review",
                "title": "Exclusivity scope review",
                "documents": [x["document_id"] for x in exclusivity],
                "description": "Exclusivity provisions were detected; portfolio-level scope and customer eligibility should be checked.",
                "evidence": exclusivity,
                "human_review_required": True,
            },
        ],
        "unresolved_questions": [
            "Do the actual customer activities and geographic facts cause any exclusivity provisions to overlap?",
            "Are event feeds, invoices, acceptance records, and security logs complete for each contract?",
            "Do any amendment or incorporated terms alter the extracted obligations or priority rules?",
        ],
        "recommended_actions": [
            {"action": "Keep separate obligation/deadline registers per contract and recipient.", "human_approval_required": True},
            {"action": "Review B1/C1 exclusivity scope against real customer-sector facts before treating it as a conflict.", "human_approval_required": True},
            {"action": "Reconcile invoice and event evidence before calculating financial exposure or alleging breach.", "human_approval_required": True},
        ],
        "notice": "Potential conflicts are flags for investigation, not adjudicated legal conclusions.",
    }
