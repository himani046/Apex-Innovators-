"""Configurable multi-contract analysis for FR1.1 and FR8.

This path accepts user-supplied contract text and company context. It is intentionally
conservative: keyword-based candidate extraction is labeled as triage, not legal advice.
"""
from __future__ import annotations

import re
import hashlib
from datetime import date
from typing import Any

from backend.services.contract_graph import build_contract_graph
from backend.services.upload_analysis import extract_document_terms


DATE_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b", re.I)
RISK_RULES = [
    ("renewal", re.compile(r"\b(auto(?:matic)?[- ]renew|renewal|renew|non[- ]renewal)\b", re.I), "medium"),
    ("termination", re.compile(r"\b(termination|terminate|cure period|default)\b", re.I), "medium"),
    ("penalty_or_interest", re.compile(r"\b(penalty|liquidated damages|interest rate|late fee)\b", re.I), "high"),
    ("liability_or_indemnity", re.compile(r"\b(indemnif\w*|limitation of liability|liability cap|consequential damages)\b", re.I), "medium"),
    ("notice_obligation", re.compile(r"\b(notice period|written notice|notify within|notification within)\b", re.I), "medium"),
    ("exclusivity_or_conflict", re.compile(r"\b(exclusive|exclusivity|conflict of terms|inconsistent with)\b", re.I), "medium"),
]


def _date_status(raw: str, as_of: date) -> tuple[str, str]:
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return "date_candidate", "Date found in source; normalize and verify manually."
    return ("past" if parsed < as_of else "upcoming"), "Explicit source date compared with simulated date; legal trigger is not inferred."


def _rich_graph(contracts: dict[str, str], extractions: dict[str, dict], base_graph: dict) -> dict:
    nodes = []
    for item in base_graph.get("nodes", []):
        cid = item.get("document_id", "")
        nodes.append({**item, "id": cid, "type": "contract", "label": cid})
    edges = list(base_graph.get("edges", []))
    parties_seen: dict[str, dict] = {}
    for cid, text in contracts.items():
        lines = text.splitlines()
        for idx, raw in enumerate(lines, start=1):
            line = raw.strip()
            # Only accept explicit party labels; avoid guessing names from arbitrary prose.
            match = re.match(r"^(?:customer|client|buyer|supplier|provider|vendor|landlord|tenant|party\s+[ab])\s*:\s*(.{2,100})$", line, re.I)
            if match:
                name = match.group(1).strip().rstrip(".,;")
                key = name.casefold()
                parties_seen.setdefault(key, {"id": "party:" + key, "type": "party", "label": name, "name": name,
                                              "source_document_id": cid, "line_number": idx, "quote": raw,
                                              "verified": raw in text})
                edges.append({"source": cid, "target": "party:" + key,
                              "relation": "names_party", "status": "evidence_linked",
                              "evidence": {"document_id": cid, "line_number": idx, "quote": raw, "verified": raw in text}})
    nodes.extend(parties_seen.values())
    for cid, extraction in extractions.items():
        for index, term in enumerate(extraction.get("extracted_terms", []), start=1):
            citation = term.get("citation") or {}
            node_id = f"clause:{cid}:{index}"
            nodes.append({"id": node_id, "type": "clause", "label": term.get("category", "Clause candidate"),
                          "contract_id": cid, "category": term.get("category"),
                          "confidence": term.get("confidence"), "citation": citation})
            edges.append({"source": cid, "target": node_id, "relation": "contains_clause",
                          "status": "evidence_linked" if citation.get("verified") else "requires_review",
                          "evidence": citation})
    edges.sort(key=lambda e: (str(e.get("source")), str(e.get("target")), str(e.get("relation"))))
    return {**base_graph, "nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges),
            "mode": "evidence_grounded_contract_clause_party_graph",
            "notice": "Nodes and edges are source-backed candidates. A graph relationship is not a legal conclusion."}


def analyze_custom_portfolio(company_context: str, contract_items: list[dict[str, str]],
                             events: list[dict[str, Any]] | None, as_of: str) -> dict[str, Any]:
    clock = date.fromisoformat(as_of)
    contracts = {item["id"].strip(): item["text"] for item in contract_items}
    source_fingerprint = hashlib.sha256((company_context + "\\n" + "\\n".join(cid + "\\n" + text for cid, text in sorted(contracts.items()))).encode("utf-8")).hexdigest()
    extractions = {cid: extract_document_terms(text, cid) for cid, text in contracts.items()}
    for cid, extraction in extractions.items():
        for term in extraction.get("extracted_terms", []):
            citation = term.get("citation") or {}
            citation["verified"] = bool(citation.get("quote") and citation["quote"] in contracts[cid])
            citation["document_id"] = cid
            term["citation"] = citation

    base_graph = build_contract_graph(contracts)
    graph = _rich_graph(contracts, extractions, base_graph)
    timeline = []
    risks = []
    contract_reports = []
    agent_messages = []
    alerts = []
    events = events or []
    visible_events = [e for e in events if str(e.get("timestamp", ""))[:10] <= as_of]
    for cid, source in contracts.items():
        extraction = extractions[cid]
        citations = []
        for term in extraction.get("extracted_terms", []):
            citation = term.get("citation") or {}
            citations.append(citation)
            quote = str(citation.get("quote", ""))
            if not quote:
                continue
            for match in DATE_RE.finditer(quote):
                raw_date = match.group(0)
                # Normalize only ISO dates; named dates remain candidates until normalized.
                status, note = _date_status(raw_date, clock) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) else ("date_candidate", "Named date is source-grounded but requires normalization.")
                around = quote[max(0, match.start()-90):min(len(quote), match.end()+90)]
                kind = "deadline_or_notice" if re.search(r"deadline|notice|renew|terminate|due|payable|within", around, re.I) else "reference_or_effective_date"
                item = {"contract_id": cid, "date": raw_date, "date_type": kind, "title": around[:180],
                        "status": status, "evidence": citation, "as_of_date": as_of, "note": note}
                timeline.append(item)
        contract_risks = []
        for line_no, raw in enumerate(source.splitlines(), start=1):
            for category, pattern, severity in RISK_RULES:
                if pattern.search(raw):
                    risk = {"id": f"{cid}:{category}:{line_no}", "contract_id": cid, "category": category,
                            "title": category.replace("_", " ").title(), "severity": severity,
                            "likelihood": "unassessed_source_triage", "confidence": 0.65,
                            "priority": severity, "status": "candidate_requires_review",
                            "claim": "A potentially relevant contractual provision was identified; applicability and legal effect require review.",
                            "reason": "Keyword-based source triage; this is not a finding of breach.",
                            "evidence": {"document_id": cid, "clause_reference": "line " + str(line_no),
                                         "line_number": line_no, "quote": raw, "verified": raw in source},
                            "recommended_next_step": "Review the cited provision in context and confirm applicable facts."}
                    contract_risks.append(risk)
        mapped_events = []
        for event in visible_events:
            body = str(event.get("body", event.get("text", "")))
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(cid) + r"(?![A-Za-z0-9])", body, re.I):
                mapped_events.append({"event": event, "contract_id": cid, "status": "mapped_by_explicit_id",
                                      "note": "Mapped only because event text explicitly names this contract ID."})
        risks.extend(contract_risks)
        for risk in contract_risks:
            alerts.append({**risk, "alert_source": "contract_clause_triage"})
        confidence = [float(t["confidence"]) for t in extraction.get("extracted_terms", [])
                      if isinstance(t.get("confidence"), (int, float))]
        gaps = extraction.get("ambiguities", [])
        actions = []
        for risk in contract_risks:
            category = risk["category"]
            if category == "renewal":
                action_type, subject = "renewal_review", f"Review renewal and notice requirements for {cid}"
            elif category == "termination":
                action_type, subject = "termination_review", f"Review termination and cure-period language for {cid}"
            elif category == "penalty_or_interest":
                action_type, subject = "financial_escalation_memo", f"Validate penalty or interest trigger for {cid}"
            elif category == "notice_obligation":
                action_type, subject = "evidence_request", f"Confirm notice timing and delivery evidence for {cid}"
            elif category == "liability_or_indemnity":
                action_type, subject = "legal_review_memo", f"Review liability allocation in {cid}"
            else:
                action_type, subject = "cross_contract_review", f"Review possible term interaction in {cid}"
            actions.append({"type": action_type, "subject": subject,
                            "body": "Please review the cited source language, confirm the applicable trigger and relevant facts, and determine whether a notice or other action is appropriate. This draft is not sent automatically.",
                            "citations": [risk["evidence"]], "confidence": 0.65,
                            "human_approval_required": True, "status": "draft_only_not_sent"})
        report = {"contract_id": cid, "status": "complete_with_review_items" if contract_risks or gaps else "source_triage_complete",
                  "key_terms": extraction.get("extracted_terms", []), "obligations": extraction.get("extracted_terms", []),
                  "timeline": [t for t in timeline if t["contract_id"] == cid], "risks": contract_risks,
                  "mapped_events": mapped_events, "citations": citations,
                  "citation_validation": {"total": len(citations), "verified": sum(bool(c.get("verified")) for c in citations),
                                          "failed": sum(not c.get("verified", False) for c in citations)},
                  "confidence": round(sum(confidence)/len(confidence), 3) if confidence else None,
                  "unresolved_questions": gaps,
                  "recommended_actions": actions or [{"type": "review_request", "subject": f"Review contract {cid}",
                                           "body": "Review extracted source candidates and confirm all relevant obligations before taking action.",
                                           "citations": citations[:5], "confidence": 0.65,
                                           "human_approval_required": True, "status": "draft_only_not_sent"}],
                  "notice": "Keyword-based source triage; not legal advice and not a complete semantic contract review."}
        contract_reports.append(report)
        agent_messages.extend([
            {"from": "Thor", "to": "Norns", "type": "extracted_terms", "status": "complete", "contract_id": cid,
             "count": len(extraction.get("extracted_terms", []))},
            {"from": "Norns", "to": "Loki", "type": "timeline_candidates", "status": "complete", "contract_id": cid,
             "count": len(report["timeline"])},
            {"from": "Loki", "to": "Heimdall", "type": "risk_challenge", "status": "candidate_requires_review",
             "contract_id": cid, "count": len(contract_risks)},
            {"from": "Heimdall", "to": "Tyr", "type": "evidence_verification", "status": "verified_with_limitations",
             "contract_id": cid, "event_matches": len(mapped_events)},
            {"from": "Tyr", "to": "Odin", "type": "qualified_recommendation", "status": "draft_only_not_sent",
             "contract_id": cid},
        ])

    alerts.sort(key=lambda item: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(item.get("severity", "")).lower(), 4),
                                  str(item.get("contract_id", "")), str(item.get("id", ""))))
    contract_reports.sort(key=lambda item: item["contract_id"])
    exposure = {"status": "not_calculated", "value": None,
                "reason": "Custom portfolio intake does not infer exposure from contractual rates or unlinked event amounts."}
    company_report = {"title": "Company Risk Report", "company_context": company_context, "as_of_date": as_of,
                      "status": "complete_with_limitations", "contract_count": len(contracts),
                      "contract_reports": len(contract_reports), "cross_contract_relationships": graph.get("edges", []),
                      "total_financial_exposure": None, "financial_exposure_status": exposure["status"],
                      "prioritized_action_list": alerts, "worst_case_projection": {
                          "timeline": timeline, "note": "A defensible worst-case financial projection requires verified triggers, amounts, and periods."},
                      "references": [c for report in contract_reports for c in report["citations"]],
                      "unresolved_questions": [q for report in contract_reports for q in report["unresolved_questions"]],
                      "limitations": ["Keyword-based extraction is triage, not complete semantic interpretation.",
                                      "Events are mapped only by explicit contract ID; no event means no evidence, not proof of no incident.",
                                      "Financial exposure is not calculated without reconciliation evidence.",
                                      "Every proposed action requires human review."]}
    shared_state = {"schema_version": "1.0", "company_context": company_context, "as_of_date": as_of,
                    "contracts_and_relationships": {"contract_ids": sorted(contracts), "graph": graph},
                    "extracted_clauses": [term for item in extractions.values() for term in item.get("extracted_terms", [])],
                    "timeline_events": timeline, "financial_calculations": [], "risk_claims": risks,
                    "evidence_references": [c for report in contract_reports for c in report["citations"]],
                    "verification_outcomes": [{"contract_id": r["contract_id"], "citation_validation": r["citation_validation"]}
                                              for r in contract_reports],
                    "unresolved_questions": company_report["unresolved_questions"],
                    "recommended_actions": [action for report in contract_reports for action in report["recommended_actions"]],
                    "agent_status": {name: {"status": "complete_with_limitations", "mode": "deterministic_source_triage"}
                                     for name in ["Odin", "Thor", "Norns", "Loki", "Heimdall", "Tyr"]},
                    "agent_messages": agent_messages,
                    "execution": {"mode": "bounded_single_pass", "max_iterations": 0, "iterations_used": 0,
                                  "note": "This custom-input path performs one deterministic pass; iterative LLM debate is not run for arbitrary inputs."}}
    return {"status": "complete_with_limitations", "scope": "custom_contract_portfolio", "as_of_date": as_of,
            "source_fingerprint": source_fingerprint,
            "company_context": company_context, "contracts": [{"id": cid, "characters": len(text)} for cid, text in sorted(contracts.items())],
            "contract_graph": graph, "timeline": {"as_of_date": as_of, "milestones": timeline},
            "risk_signals": risks, "alert_feed": alerts, "exposure": exposure,
            "agent_debate": {"messages": agent_messages, "note": "Messages describe deterministic handoffs; this path does not claim a live LLM debate."},
            "contract_reports": contract_reports, "company_risk_report": company_report,
            "shared_state": shared_state, "limitations": company_report["limitations"]}
