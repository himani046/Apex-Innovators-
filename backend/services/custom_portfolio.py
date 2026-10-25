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
from backend.services.portfolio_intelligence import detect_cross_contract_candidates, reconcile_payment_events, review_cross_contract_candidates, run_bounded_review_cycles
from backend.services.amendment_resolution import analyze_amendment_lineage


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
                             events: list[dict[str, Any]] | None, as_of: str,
                             use_llm: bool = False,
                             payment_ledger: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    clock = date.fromisoformat(as_of)
    contracts = {item["id"].strip(): item["text"] for item in contract_items}
    source_fingerprint = hashlib.sha256((company_context + chr(10) + chr(10).join(cid + chr(10) + text for cid, text in sorted(contracts.items())) + chr(10) + json.dumps(events or [], sort_keys=True, ensure_ascii=False, default=str) + chr(10) + json.dumps(payment_ledger or [], sort_keys=True, ensure_ascii=False, default=str)).encode("utf-8")).hexdigest()
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
    verification_records = []
    alerts = []
    events = events or []
    def event_is_visible(event: dict[str, Any]) -> bool:
        timestamp = str(event.get("timestamp", event.get("date", ""))).strip()
        if not timestamp:
            return True
        try:
            return date.fromisoformat(timestamp[:10]) <= clock
        except ValueError:
            # Keep malformed timestamps visible to the ingestion validator so they
            # are reported as rejected instead of disappearing silently.
            return True

    visible_events = [event for event in events if isinstance(event, dict) and event_is_visible(event)]
    for cid, source in contracts.items():
        extraction = extractions[cid]
        citations = [term.get("citation") or {} for term in extraction.get("extracted_terms", []) if term.get("citation")]
        contract_timeline = build_contract_timeline(cid, extraction, as_of)
        timeline.extend(contract_timeline)
        loki_result = review_contract_candidates(cid, source, extraction)
        contract_risks = loki_result.get("findings", [])
        heimdall_result = verify_contract_review(cid, source, contract_risks, visible_events)
        verification_records.append({"contract_id": cid, **heimdall_result})
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
        for mapped in mapped_events:
            event_body = str(mapped.get("body", ""))
            event_category = None
            if re.search(r"\b(invoice|payment|remittance|refund|credit|billing|paid|overdue)\b", event_body, re.I):
                event_category = "payment_event"
            elif re.search(r"\b(renewal|renew|termination|notice|deadline|expiry|expires)\b", event_body, re.I):
                event_category = "contract_milestone_event"
            elif re.search(r"\b(outage|incident|breach|disruption|failure|complaint|delay|shipment|delivery)\b", event_body, re.I):
                event_category = "operational_incident"
            if event_category is None and mapped.get("matched_clauses"):
                event_category = "contract_clause_trigger_candidate"
            if event_category:
                alerts.append({
                    "id": str(mapped.get("event_id") or "event") + ":" + cid,
                    "contract_id": cid, "category": event_category,
                    "title": "Review event against " + str(len(mapped.get("matched_clauses", []))) + " candidate clause(s)" if mapped.get("matched_clauses") else "Review supplied " + event_category.replace("_", " "),
                    "severity": "medium", "priority": "medium",
                    "status": "event_clause_mapping_candidate_requires_review" if mapped.get("matched_clauses") else "event_candidate_requires_review",
                    "reason": "Event-to-contract link method: " + str((mapped.get("contract_link") or {}).get("method", "unknown")) + ". Candidate event families: " + ", ".join(mapped.get("event_families", [])) + ". Clause-family mapping is heuristic; verify event authenticity, timing, operative wording, exceptions, amendments, and trigger facts before treating this as a breach or financial obligation.",
                    "date": mapped.get("timestamp"),
                    "candidate_deadline_dates": mapped.get("candidate_deadline_dates", []),
                    "contract_link": mapped.get("contract_link", {}),
                    "event_families": mapped.get("event_families", []),
                    "evidence": {"document_id": str(mapped.get("event_id") or "supplied event"),
                                 "quote": event_body, "verified": False,
                                 "verification_note": "User-supplied event record; source authenticity not independently verified."},
                    "matched_clauses": mapped.get("matched_clauses", []),
                    "recommended_next_step": "Verify the source, determine whether the matched clause applies, check trigger timing and exceptions, then obtain human approval for any action.",
                    "human_review_required": True,
                    "source_authenticity_verified": False,
                    "breach_determined": False,
                })
        confidence = [float(t["confidence"]) for t in extraction.get("extracted_terms", [])
                      if isinstance(t.get("confidence"), (int, float))]
        gaps = list(dict.fromkeys(list(extraction.get("ambiguities", []) or []) + [gap for item in heimdall_result.get("findings", []) for gap in (item.get("evidence_gaps", []) or [])]))
        actions = [item.get("action_draft") for item in tyr_result.get("rulings", []) if item.get("action_draft")]
        report = {"contract_id": cid, "status": "complete_with_review_items" if contract_risks or gaps else "source_triage_complete",
                  "key_terms": extraction.get("extracted_terms", []), "obligations": extraction.get("extracted_terms", []),
                  "timeline": [t for t in timeline if t["contract_id"] == cid], "risks": contract_risks,
                  "mapped_events": mapped_events,
                  "event_clause_mapping": {
                      "events_mapped": len(mapped_events),
                      "events_with_clause_candidates": sum(bool(item.get("matched_clauses")) for item in mapped_events),
                      "events_linked_by_explicit_id": sum((item.get("contract_link") or {}).get("method") == "explicit_contract_identifier" for item in mapped_events),
                      "events_linked_by_party_candidate": sum((item.get("contract_link") or {}).get("method") == "contract_party_name_candidate" for item in mapped_events),
                      "source_authenticity_verified": False,
                  }, "citations": citations,
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
    # Run a bounded second-pass collaboration cycle. This is deterministic and
    # evidence-preserving; it never claims an LLM debate or a legal conclusion.
    portfolio_call_budget = max(450, len(contracts) * 13 + 150)
    agent_workflow = run_bounded_review_cycles(
        contracts=contracts, extractions=extractions, events=visible_events,
        as_of=as_of, max_iterations=1, max_agent_calls=portfolio_call_budget, use_llm=use_llm,
    )
    ledger_events = []
    for index, row in enumerate(payment_ledger or []):
        if not isinstance(row, dict):
            continue
        timestamp = str(row.get("date") or row.get("timestamp") or "").strip()
        reference = str(row.get("reference") or row.get("invoice_id") or "").strip()
        status_text = str(row.get("status") or row.get("payment_status") or "unknown").strip().casefold()
        counterparty_text = " ".join(str(row.get(key, "")) for key in ("from", "to", "counterparty", "vendor"))
        body = " ".join(part for part in (reference, counterparty_text, status_text) if part).strip()
        if re.search(r"\b(credit|refund|refunded)\b", body, re.I):
            event_type = "credit"
        elif status_text in {"paid", "settled", "remitted"}:
            event_type = "payment"
        elif status_text in {"pending", "overdue", "unpaid", "outstanding"} or re.search(r"\b(invoice|inv[- #])\b", body, re.I):
            event_type = "invoice"
        else:
            event_type = "unknown"
        ledger_events.append({
            "event_id": str(row.get("event_id") or f"payment-ledger:{index + 1}"),
            "timestamp": timestamp or None,
            "body": body or "Payment ledger row requires review",
            "contract_id": row.get("contract_id") if str(row.get("contract_id") or "") in contracts else None,
            "invoice_id": row.get("invoice_id"),
            "event_type": event_type,
            "payment_status": status_text,
            "amount": row.get("amount"),
            "currency": row.get("currency"),
            "event_source": str(row.get("source") or "uploaded_payment_ledger"),
            "source_type": "user_supplied_payment_ledger",
            "source_verified": False,
        })
    financial_reconciliation = reconcile_payment_events(visible_events + ledger_events, contracts, as_of)
    financial_reconciliation["payment_ledger_rows_received"] = len(payment_ledger or [])
    financial_reconciliation["payment_ledger_rows_normalized"] = len(ledger_events)
    financial_reconciliation["source_authenticity_verified"] = False

    # Promote reconciliation outcomes into the shared action feed so the
    # dashboard, company report, and decision queue expose the same financial
    # blockers. These are review actions, never confirmed liabilities.
    for group in financial_reconciliation.get("invoice_groups", []):
        balance = group.get("candidate_ledger_balance")
        balance_status = str(group.get("candidate_balance_status") or "insufficient_reconciliation_evidence")
        if balance_status == "candidate_fully_offset_requires_verification":
            priority = "low"
            title = "Verify invoice appears fully offset"
        elif balance_status == "candidate_outstanding_balance_requires_verification":
            priority = "high"
            title = "Verify candidate outstanding invoice balance"
        elif balance_status == "candidate_overpayment_or_excess_credit_requires_review":
            priority = "high"
            title = "Review possible overpayment or excess credit"
        else:
            priority = "medium"
            title = "Resolve invoice reconciliation blocker"
        alerts.append({
            "id": f"invoice-reconciliation:{group.get('contract_id')}:{group.get('invoice_id')}",
            "contract_id": group.get("contract_id"),
            "category": "invoice_payment_reconciliation",
            "title": title,
            "severity": priority,
            "priority": priority,
            "status": balance_status,
            "candidate_balance": balance,
            "candidate_balance_currency": group.get("candidate_balance_currency"),
            "invoice_id": group.get("invoice_id"),
            "evidence": {
                "event_ids": group.get("event_ids", []),
                "invoice_amount_candidate": group.get("invoice_amount_candidate"),
                "payment_amount_candidates": group.get("payment_amount_candidates", []),
                "credit_amount_candidates": group.get("credit_amount_candidates", []),
                "due_date_candidates": group.get("due_date_candidates", []),
                "source_verified": False,
            },
            "reason": "Arithmetic candidate from supplied invoice/payment/credit rows; it is not confirmed exposure or a legal conclusion.",
            "recommended_next_step": "Match the original invoice and payment/credit confirmations to the contractual billing trigger, period, currency, and due date.",
            "human_review_required": True,
            "confirmed_liability": False,
        })
    cross_contract_candidates = detect_cross_contract_candidates(contracts)
    # Amendment lineage and precedence are resolved before cross-contract review.
    amendment_resolution = analyze_amendment_lineage(contracts, cross_contract_candidates)
    amendment_review_by_id = {item.get('candidate_id'): item for item in amendment_resolution.get('candidate_reviews', []) if item.get('candidate_id')}
    for candidate in cross_contract_candidates:
        amendment_review = amendment_review_by_id.get(candidate.get('id'))
        if amendment_review:
            candidate['amendment_resolution'] = amendment_review
            candidate['precedence_context_status'] = amendment_review.get('status')
            candidate['legal_conflict_determined'] = False
            candidate['human_review_required'] = True
    for edge in amendment_resolution.get('lineage_edges', []):
        graph.setdefault('edges', []).append({'source': edge['source'], 'target': edge['target'], 'relation': edge['relation'], 'status': edge['status'], 'evidence': edge.get('evidence', {}), 'amendment_validity_confirmed': False})
        graph.setdefault('nodes', []).append({'id': edge['id'], 'type': 'amendment_lineage_candidate', 'label': 'Possible amendment link', 'contract_ids': [edge['source'], edge['target']], 'evidence': edge.get('evidence', {}), 'status': edge['status'], 'human_review_required': True})
        agent_messages.append({'from': 'Thor', 'to': 'Odin', 'type': 'amendment_lineage_candidate', 'status': edge['status'], 'source_contract_id': edge['source'], 'target_contract_id': edge['target']})
    for missing in amendment_resolution.get('missing_document_requests', []):
        alerts.append({'id': 'missing-document:' + str(missing.get('document_id')) + ':' + str(missing.get('line_number', 0)) + ':' + str(missing.get('type')), 'contract_id': missing.get('document_id'), 'category': 'amendment_or_incorporated_document_gap', 'title': 'Resolve missing amendment or incorporated document', 'severity': 'medium', 'priority': 'medium', 'status': missing.get('status', 'manual_review_required'), 'reason': missing.get('reason', 'A referenced document could not be linked to supplied sources.'), 'evidence': {}, 'recommended_next_step': 'Upload the referenced base agreement, amendment, order form, schedule, exhibit, or statement of work and confirm its effective version.', 'human_review_required': True, 'legal_conflict_determined': False})
    cross_review_budget = max(
        0, portfolio_call_budget - int(agent_workflow.get("agent_calls_used", 0))
    )
    cross_contract_review = review_cross_contract_candidates(
        cross_contract_candidates, contracts, visible_events, as_of,
        max_agent_calls=cross_review_budget,
    )
    cross_review_by_id = {
        trace.get("candidate_id"): trace
        for trace in cross_contract_review.get("traces", [])
        if trace.get("candidate_id")
    }
    for candidate in cross_contract_candidates:
        if candidate.get("id") in cross_review_by_id:
            candidate["agent_review"] = cross_review_by_id[candidate["id"]]
        else:
            candidate["agent_review"] = {
                "status": "not_reviewed_budget_or_candidate_limit",
                "human_review_required": True,
                "legal_conflict_determined": False,
            }
    agent_workflow["agent_calls_used"] = int(agent_workflow.get("agent_calls_used", 0)) + int(
        cross_contract_review.get("agent_calls_used", 0)
    )
    agent_workflow["cross_contract_review"] = {
        key: value for key, value in cross_contract_review.items()
        if key not in {"traces", "agent_messages", "event_ingestion"}
    }
    if str(cross_contract_review.get("status", "")).startswith("partial_"):
        agent_workflow["partial_completion"] = True
        agent_workflow["stop_reason"] = (
            "cross_contract_review_budget_exhausted"
            if cross_contract_review.get("status") == "partial_budget_exhausted"
            else "cross_contract_candidate_limit_reached"
        )
        if cross_contract_review.get("status") == "partial_budget_exhausted":
            agent_workflow["budget_exhausted"] = True
    for candidate in cross_contract_candidates:
        ids = candidate.get("contract_ids", [])
        if len(ids) != 2:
            continue
        left, right = ids
        evidence = candidate.get("evidence", [])
        edge = {
            "source": left, "target": right, "relation": "potential_inconsistency",
            "status": "candidate_requires_human_review", "candidate_id": candidate.get("id"),
            "topic": candidate.get("topic"), "classification": candidate.get("classification"),
            "evidence": evidence, "legal_conflict_determined": False,
        }
        graph.setdefault("edges", []).append(edge)
        graph.setdefault("nodes", []).append({
            "id": candidate.get("id"), "type": "conflict_candidate",
            "label": "Potential " + str(candidate.get("topic", "term")) + " inconsistency",
            "contract_ids": ids, "status": candidate.get("status"),
            "evidence": evidence, "human_review_required": True,
        })
        cross_contract_edges.append(edge)
        risks.append({
            "id": candidate.get("id"), "category": "cross_contract_inconsistency_candidate",
            "title": "Potential cross-contract " + str(candidate.get("topic", "term")) + " inconsistency",
            "contract_ids": ids, "severity": candidate.get("severity", "medium"),
            "status": candidate.get("status"), "claim": candidate.get("explanation"),
            "citations": evidence, "evidence": evidence,
            "evidence_gaps": candidate.get("unresolved_questions", []),
            "legal_conflict_determined": False, "human_review_required": True,
        })
        alerts.append({
            "id": candidate.get("id"), "contract_id": left,
            "contract_ids": ids, "category": "cross_contract_inconsistency_candidate",
            "title": "Review potential cross-contract " + str(candidate.get("topic", "term")) + " difference",
            "severity": candidate.get("severity", "medium"), "priority": "medium",
            "status": candidate.get("status"), "reason": candidate.get("explanation"),
            "evidence": evidence, "recommended_next_step": "Compare parties, scope, amendments, precedence, and incorporated terms.",
        })
    graph["node_count"] = len(graph.get("nodes", []))
    graph["edge_count"] = len(graph.get("edges", []))
    agent_messages.extend(agent_workflow.get("agent_messages", []))
    agent_messages.extend(cross_contract_review.get("agent_messages", []))
    debate_traces.append({"workflow": agent_workflow.get("mode"),
                          "loop_traces": agent_workflow.get("loop_traces", []),
                          "stop_reason": agent_workflow.get("stop_reason")})
    debate_traces.append({
        "workflow": cross_contract_review.get("mode"),
        "traces": cross_contract_review.get("traces", []),
        "stop_reason": cross_contract_review.get("stop_reason"),
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
            "progress": {"completed_stages": 5, "total_stages": 6, "percentage": 83},
            "extracted_obligations": report.get("obligations", []),
            "timeline_candidates": report.get("timeline", []),
            "risk_findings": report.get("risks", []),
            "open_questions": gaps,
            "completion_gate": {"workflow_complete": False, "evidence_gaps_remaining": bool(gaps),
                                "human_review_required": True,
                                "legal_outcome_resolved": False,
                                "note": "Source triage ran; bounded agent review must be confirmed before this workstream can be marked workflow-complete."},
            "completion_note": "Source triage is complete; bounded agent review has not yet been confirmed."
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
        "completion_gate": {"workflow_complete": True, "evidence_gaps_remaining": bool(cross_contract_edges),
                            "human_review_required": bool(cross_contract_edges), "legal_outcome_resolved": False},
        "completion_note": "The relationship scan completed; absence of an edge is not proof that no legal dependency exists."
    })

    # Keep progress truthful: source-triage stages can finish while legal review
    # remains open, and a budget-exhausted agent cycle must not show as complete.
    workflow_by_contract = {
        item.get("contract_id"): item
        for item in agent_workflow.get("workstreams", [])
        if item.get("contract_id")
    }
    for stream in workstreams:
        cid = stream.get("primary_contract_id")
        if cid not in workflow_by_contract:
            if cid is not None:
                stream["status"] = "not_run_missing_workstream"
                stream["progress"] = {"completed_stages": 5, "total_stages": 6, "percentage": 83}
                stream["completion_gate"] = {
                    "workflow_complete": False,
                    "evidence_gaps_remaining": bool(stream.get("open_questions")),
                    "human_review_required": True,
                    "legal_outcome_resolved": False,
                    "agent_review_stop_reason": "missing_workstream",
                    "note": "No bounded agent-workflow result was returned for this contract; it must not be marked complete.",
                }
                stream["completion_note"] = "Agent review did not return a result for this contract. Re-run or inspect the workflow before treating it as complete."
            continue
        workflow = workflow_by_contract[cid]
        ran = bool(workflow.get("status")) and workflow.get("status") not in {
            "not_run_budget_exhausted", "not_run_missing_workstream", "failed", "error", "not_run"
        }
        stream["progress"] = {
            "completed_stages": 6 if ran else 5,
            "total_stages": 6,
            "percentage": 100 if ran else 83,
        }
        review_needed = bool(workflow.get("unresolved_questions") or stream.get("open_questions") or stream.get("risk_findings"))
        stream["status"] = ("not_run_budget_exhausted" if not ran else "complete_with_review_items" if review_needed else "complete")
        stream["completion_gate"] = {
            "workflow_complete": ran,
            "evidence_gaps_remaining": bool(workflow.get("unresolved_questions") or stream.get("open_questions")),
            "human_review_required": bool(workflow.get("human_review_required", True) or review_needed),
            "legal_outcome_resolved": False,
            "agent_review_iterations": workflow.get("iterations_used", 0),
            "agent_review_stop_reason": workflow.get("stop_reason", "not_run"),
            "note": "A completed workflow is not a legal-completeness guarantee; source and event gaps remain explicit.",
        }
        stream["open_questions"] = list(dict.fromkeys(
            list(stream.get("open_questions", []) or []) + list(workflow.get("unresolved_questions", []) or [])
        ))
        stream["completion_note"] = (
            "Bounded agent review ran; unresolved evidence and human review are still visible."
            if ran else "Agent review did not run because the configured call budget was exhausted."
        )
    alerts.sort(key=lambda item: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(item.get("severity", "")).lower(), 4),
                                  str(item.get("contract_id", "")), str(item.get("id", ""))))
    contract_reports.sort(key=lambda item: item["contract_id"])
    exposure = {"status": "not_calculated", "value": None,
                "candidate_count": financial_reconciliation.get("counts", {}).get("payment_candidates", 0),
                "reason": "Custom portfolio intake does not aggregate exposure from unverified invoice/payment candidates."}
    company_report = {"title": "Company Risk Report", "company_context": company_context, "as_of_date": as_of,
                      "amendment_resolution": amendment_resolution,
                      "amendment_resolution_summary": amendment_resolution.get("summary", {}),
                      "status": "complete_with_limitations", "contract_count": len(contracts),
                      "contract_reports": len(contract_reports), "cross_contract_relationships": cross_contract_edges, "cross_contract_candidates": cross_contract_candidates,
                      "total_financial_exposure": None, "financial_exposure_status": exposure["status"], "financial_reconciliation": financial_reconciliation,
                      "prioritized_action_list": alerts, "worst_case_projection": {
                          "timeline": timeline, "note": "A defensible worst-case financial projection requires verified triggers, amounts, and periods."},
                      "references": [c for report in contract_reports for c in report["citations"]] + [e for item in cross_contract_candidates for e in item.get("evidence", [])],
                      "unresolved_questions": [q for report in contract_reports for q in report["unresolved_questions"]] + [q for item in cross_contract_candidates for q in item.get("unresolved_questions", [])],
                      "limitations": ["Keyword-based extraction is triage, not complete semantic interpretation.",
                                      "Events are mapped only by explicit contract ID; no event means no evidence, not proof of no incident.",
                                      "Financial exposure is not calculated without reconciliation evidence.",
                                      "Every proposed action requires human review."]}
    # Stable action IDs let reviewers approve/reject one contract action at a time.
    for report in contract_reports:
        for index, action in enumerate(report.get("recommended_actions", []) or [], start=1):
            action.setdefault("action_id", f"{report['contract_id']}:action:{index}")
            action.setdefault("human_approval_required", True)
            action.setdefault("status", "draft_only_not_sent")

    shared_state = {"schema_version": "1.0", "company_context": company_context, "as_of_date": as_of,
                    "contracts_and_relationships": {"contract_ids": sorted(contracts), "graph": graph},
                    "amendment_resolution": amendment_resolution,
                    "workstreams": workstreams,
                    "extracted_clauses": [term for item in extractions.values() for term in item.get("extracted_terms", [])],
                    "timeline_events": timeline, "financial_calculations": financial_reconciliation.get("payment_candidates", []), "financial_reconciliation": financial_reconciliation, "risk_claims": risks,
                    "evidence_references": [c for report in contract_reports for c in report["citations"]],
                    "verification_outcomes": verification_records,
                    "unresolved_questions": company_report["unresolved_questions"],
                    "recommended_actions": [action for report in contract_reports for action in report["recommended_actions"]],
                    "agent_status": {name: {"status": "complete_with_limitations", "mode": "deterministic_source_triage"}
                                     for name in ["Odin", "Thor", "Norns", "Loki", "Heimdall", "Tyr"]},
                    "agent_messages": agent_messages,
                    "execution": {"mode": agent_workflow.get("mode", "bounded_deterministic_multi_agent_workflow"), "max_iterations": agent_workflow.get("max_iterations", 1), "iterations_used": agent_workflow.get("iterations_used", 0),
                                  "agent_calls_used": agent_workflow.get("agent_calls_used", 0), "agent_call_budget": agent_workflow.get("agent_call_budget", 300),
                                  "stop_reason": agent_workflow.get("stop_reason"), "note": agent_workflow.get("notice")}}
    coverage_incomplete = any(
        stream.get("primary_contract_id") is not None
        and not (stream.get("completion_gate") or {}).get("workflow_complete", False)
        for stream in workstreams
    )
    for name, status in shared_state.get("agent_status", {}).items():
        status["mode"] = agent_workflow.get("mode", "bounded_deterministic_multi_agent_workflow")
        status["status"] = (
            "partial_budget_exhausted" if agent_workflow.get("budget_exhausted")
            else "partial_review_limit_reached" if agent_workflow.get("partial_completion")
            else "partial_workstream_coverage" if coverage_incomplete
            else "complete_with_limitations"
        )
    final_status = (
        "partial_budget_exhausted" if agent_workflow.get("budget_exhausted")
        else "partial_review_limit_reached" if agent_workflow.get("partial_completion")
        else "partial_workstream_coverage" if coverage_incomplete
        else "complete_with_limitations"
    )
    company_report["status"] = final_status
    return {"status": final_status, "scope": "custom_contract_portfolio", "as_of_date": as_of,
            "source_fingerprint": source_fingerprint,
            "company_context": company_context, "contracts": [{"id": cid, "characters": len(text)} for cid, text in sorted(contracts.items())],
            "contract_graph": graph, "workstreams": workstreams, "timeline": {"as_of_date": as_of, "milestones": timeline},
            "risk_signals": risks, "alert_feed": alerts, "exposure": exposure, "financial_reconciliation": financial_reconciliation,
            "agent_debate": {"messages": agent_messages, "traces": debate_traces, "note": "Bounded deterministic challenge/verification/ruling cycles; this is not a live LLM debate."},
            "agent_workflow": agent_workflow, "cross_contract_candidates": cross_contract_candidates,
            "amendment_resolution": amendment_resolution,
            "cross_contract_review": cross_contract_review,
            "contract_reports": contract_reports, "company_risk_report": company_report,
            "shared_state": shared_state, "limitations": company_report["limitations"]}
