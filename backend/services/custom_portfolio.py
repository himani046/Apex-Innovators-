"""Configurable multi-contract analysis for FR1.1 and FR8.

This path accepts user-supplied contract text and company context. It is intentionally
conservative: keyword-based candidate extraction is labeled as triage, not legal advice.
"""
from __future__ import annotations

import re
import hashlib
import json
from datetime import date
from typing import Any

from backend.services.contract_graph import build_contract_graph
from backend.services.upload_analysis import extract_document_terms
from backend.agents.norns import build_contract_timeline
from backend.agents.loki import review_contract_candidates
from backend.agents.heimdall import verify_contract_review
from backend.agents.tyr import arbitrate_contract_review


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


def build_rich_contract_graph(contracts: dict[str, str], extractions: dict[str, dict], base_graph: dict) -> dict:
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
            party_names = []
            match = re.match(r"^(?:customer|client|buyer|supplier|provider|vendor|landlord|tenant|party\s+[ab])\s*:\s*(.{2,100})$", line, re.I)
            if match:
                party_names.append(match.group(1).strip().rstrip(".,;"))
            elif re.search(r"\b(agreement|contract|parties|entered into)\b", line, re.I):
                between = re.search(r"\bbetween\s+(.{2,80}?)\s+and\s+(.{2,80}?)(?:,|;|\.|$)", line, re.I)
                if between:
                    party_names.extend([between.group(1).strip().strip(' \\"'), between.group(2).strip().strip(' \\"')])
            for name in party_names:
                if len(name) < 2 or len(name) > 100:
                    continue
                key = name.casefold()
                parties_seen.setdefault(key, {"id": "party:" + key, "type": "party", "label": name, "name": name,
                                              "confidence": 0.75, "source_document_id": cid, "line_number": idx,
                                              "quote": raw, "verified": raw in text})
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


# Backwards-compatible private alias for any older internal callers.
_rich_graph = build_rich_contract_graph


def analyze_custom_portfolio(company_context: str, contract_items: list[dict[str, str]],
                             events: list[dict[str, Any]] | None, as_of: str) -> dict[str, Any]:
    clock = date.fromisoformat(as_of)
    contracts = {item["id"].strip(): item["text"] for item in contract_items}
    source_fingerprint = hashlib.sha256((company_context + chr(10) + chr(10).join(cid + chr(10) + text for cid, text in sorted(contracts.items())) + chr(10) + json.dumps(events or [], sort_keys=True, ensure_ascii=False, default=str)).encode("utf-8")).hexdigest()
    extractions = {cid: extract_document_terms(text, cid) for cid, text in contracts.items()}
    for cid, extraction in extractions.items():
        for term in extraction.get("extracted_terms", []):
            citation = term.get("citation") or {}
            citation["verified"] = bool(citation.get("quote") and citation["quote"] in contracts[cid])
            citation["document_id"] = cid
            term["citation"] = citation

    base_graph = build_contract_graph(contracts)
    graph = build_rich_contract_graph(contracts, extractions, base_graph)
    cross_contract_edges = [edge for edge in graph.get("edges", []) if str(edge.get("source", "")) in contracts and str(edge.get("target", "")) in contracts]
    timeline = []
    risks = []
    contract_reports = []
    agent_messages = []
    debate_traces = []
    alerts = []
    events = events or []
    visible_events = [e for e in events if str(e.get("timestamp", ""))[:10] <= as_of]
    for cid, source in contracts.items():
        extraction = extractions[cid]
        citations = [term.get("citation") or {} for term in extraction.get("extracted_terms", []) if term.get("citation")]
        contract_timeline = build_contract_timeline(cid, extraction, as_of)
        timeline.extend(contract_timeline)
        loki_result = review_contract_candidates(cid, source, extraction)
        contract_risks = loki_result.get("findings", [])
        heimdall_result = verify_contract_review(cid, source, contract_risks, visible_events)
        tyr_result = arbitrate_contract_review(cid, contract_risks, heimdall_result)
        debate_traces.append({"contract_id": cid, "loki_attacks": loki_result.get("findings", []),
                              "heimdall_verification": heimdall_result, "tyr_rulings": tyr_result.get("rulings", [])})
        mapped_events = heimdall_result.get("mapped_events", [])
        risks.extend(contract_risks)
        agent_messages.extend(loki_result.get("clarification_requests", []))
        agent_messages.extend([
            {"from": "Thor", "to": "Norns", "type": "extracted_terms", "status": "complete",
             "contract_id": cid, "count": len(extraction.get("extracted_terms", []))},
            {"from": "Norns", "to": "Loki", "type": "timeline_candidates", "status": "complete",
             "contract_id": cid, "count": len(contract_timeline)},
            {"from": "Loki", "to": "Heimdall", "type": "risk_challenge", "status": "candidate_review",
             "contract_id": cid, "findings": len(contract_risks)},
            {"from": "Heimdall", "to": "Tyr", "type": "evidence_verification", "status": heimdall_result.get("status", "unknown"),
             "contract_id": cid, "verified_findings": sum(bool(x.get("citation_checks_passed")) for x in heimdall_result.get("findings", []))},
            {"from": "Tyr", "to": "Odin", "type": "qualified_ruling", "status": tyr_result.get("status", "unknown"),
             "contract_id": cid, "rulings": len(tyr_result.get("rulings", []))}
        ])
        for risk in contract_risks:
            alerts.append({**risk, "alert_source": "contract_clause_triage"})
        confidence = [float(t["confidence"]) for t in extraction.get("extracted_terms", [])
                      if isinstance(t.get("confidence"), (int, float))]
        gaps = list(dict.fromkeys(list(extraction.get("ambiguities", []) or []) + [gap for item in heimdall_result.get("findings", []) for gap in (item.get("evidence_gaps", []) or [])]))
        actions = [item.get("action_draft") for item in tyr_result.get("rulings", []) if item.get("action_draft")]
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

    for item in timeline:
        if item.get("date_type") == "deadline_or_notice":
            alerts.append({
                "id": f"{item.get('contract_id')}:{item.get('date')}:timeline",
                "contract_id": item.get("contract_id"),
                "category": "deadline_candidate",
                "title": "Review source-stated deadline or notice date",
                "severity": "medium",
                "priority": "medium",
                "status": "date_candidate_requires_trigger_review",
                "reason": "The source contains a date near deadline/notice language. Confirm the trigger, counting convention, amendment precedence, and whether the date is actionable before treating it as overdue.",
                "date": item.get("date"),
                "evidence": item.get("evidence"),
                "recommended_next_step": "Validate the date and triggering event with the contract owner."
            })
    workstreams = []
    for report in contract_reports:
        gaps = report.get("unresolved_questions", []) or []
        workstreams.append({
            "id": "contract-" + report["contract_id"],
            "label": "Contract " + report["contract_id"],
            "primary_contract_id": report["contract_id"],
            "contract_ids": [report["contract_id"]],
            "responsibility": "Extract source terms, classify date candidates, review risks, verify evidence, and draft review actions.",
            "assigned_agents": ["Thor", "Norns", "Loki", "Heimdall", "Tyr"],
            "status": report["status"],
            "progress": {"completed_stages": 5, "total_stages": 5, "percentage": 100},
            "extracted_obligations": report.get("obligations", []),
            "timeline_candidates": report.get("timeline", []),
            "risk_findings": report.get("risks", []),
            "open_questions": gaps,
            "completion_note": "Source-triage stages ran; unresolved questions and human review remain visible. This is not a legal-completeness guarantee."
        })
    workstreams.append({
        "id": "portfolio-cross-contract",
        "label": "Cross-contract relationship review",
        "primary_contract_id": None,
        "contract_ids": sorted(contracts),
        "responsibility": "Inspect explicit document references and possible shared-risk signals across the supplied set.",
        "assigned_agents": ["Odin", "Thor", "Loki", "Heimdall", "Tyr"],
        "status": "complete_with_review_items" if cross_contract_edges else "complete_no_evidenced_relationships",
        "progress": {"completed_stages": 1, "total_stages": 1, "percentage": 100},
        "relationship_count": len(cross_contract_edges),
        "open_questions": ["Review cross-contract effects and precedence where a sourced relationship exists."] if cross_contract_edges else [],
        "completion_note": "The relationship scan completed; absence of an edge is not proof that no legal dependency exists."
    })
    alerts.sort(key=lambda item: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(item.get("severity", "")).lower(), 4),
                                  str(item.get("contract_id", "")), str(item.get("id", ""))))
    contract_reports.sort(key=lambda item: item["contract_id"])
    exposure = {"status": "not_calculated", "value": None,
                "reason": "Custom portfolio intake does not infer exposure from contractual rates or unlinked event amounts."}
    company_report = {"title": "Company Risk Report", "company_context": company_context, "as_of_date": as_of,
                      "status": "complete_with_limitations", "contract_count": len(contracts),
                      "contract_reports": len(contract_reports), "cross_contract_relationships": cross_contract_edges,
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
                    "workstreams": workstreams,
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
            "contract_graph": graph, "workstreams": workstreams, "timeline": {"as_of_date": as_of, "milestones": timeline},
            "risk_signals": risks, "alert_feed": alerts, "exposure": exposure,
            "agent_debate": {"messages": agent_messages, "traces": debate_traces, "note": "Structured deterministic challenge/verification/ruling traces; this path does not claim a live LLM debate."},
            "contract_reports": contract_reports, "company_risk_report": company_report,
            "shared_state": shared_state, "limitations": company_report["limitations"]}
