from datetime import date

from backend.config import PACK_DIR, USE_CLAUDE, MAX_AGENT_CALLS, MAX_AGENT_ITERATIONS
from backend.services.agentic_state import SharedAgentState, ExecutionBudget, run_bounded_follow_up
from backend.services.ingestion import load_pack
from backend.services.citations import verify_all
from backend.services.contract_graph import build_contract_graph, reconcile_contracts
from backend.services.workstreams import build_workstreams
from backend.services.portfolio_operations import build_portfolio_operations
from backend.services.decision_engine import build_decision_queue
from backend.agents.thor import extract_a1
from backend.agents.thor_portfolio import extract_portfolio_candidates
from backend.agents.norns import build_timeline
from backend.agents.loki import review
from backend.agents.heimdall import verify
from backend.agents.tyr import arbitrate


def run_demo(as_of="2027-03-15", request_claude=True):
    date.fromisoformat(as_of)
    pack = load_pack(PACK_DIR)
    contracts = pack["contracts"]
    budget = ExecutionBudget(MAX_AGENT_CALLS, MAX_AGENT_ITERATIONS)
    shared = SharedAgentState()
    if not budget.reserve_call("Thor portfolio extraction"):
        raise RuntimeError("Agent call budget is zero; cannot begin portfolio analysis")
    portfolio_extraction = extract_portfolio_candidates(contracts)
    contract_graph = build_contract_graph(contracts)
    contract_reconciliation = reconcile_contracts(contracts, contract_graph)
    all_events = {}
    for drop_name, drop_events in pack["event_drops"].items():
        all_events[drop_name] = [
            event for event in drop_events
            if str(event.get("timestamp", ""))[:10] <= as_of
        ]
    multi_contract_analysis = build_workstreams(
        contracts, contract_graph, contract_reconciliation, all_events, as_of
    )
    portfolio_operations = build_portfolio_operations(
        multi_contract_analysis, pack["event_drops"], as_of, pack["ledger"]
    )
    decision_queue = build_decision_queue(portfolio_operations, multi_contract_analysis)
    source = contracts.get("A1")
    if not source:
        raise RuntimeError("A1.txt missing from supplied pack")

    use = request_claude and USE_CLAUDE
    shared.update("contracts_and_relationships", {
        "contracts": [{"contract_id": key, "source_characters": len(value)} for key, value in sorted(contracts.items())],
        "graph": contract_graph,
        "reconciliation": contract_reconciliation,
        "workstreams": multi_contract_analysis.get("workstreams", []),
    })
    shared.update("extracted_clauses", [
        term for contract_result in portfolio_extraction.get("contracts", {}).values()
        for term in contract_result.get("extracted_terms", [])
    ])
    shared.update("timeline_events", portfolio_operations.get("timeline", {}).get("milestones", []))
    shared.update("financial_calculations", portfolio_operations.get("financial_reconciliation", {}).get("payment_ledger_candidates", []))
    shared.update("evidence_references", [
        term.get("citation") for contract_result in portfolio_extraction.get("contracts", {}).values()
        for term in contract_result.get("extracted_terms", []) if term.get("citation")
    ])
    shared.record_agent("Thor", "complete", consumes=["contracts"], produces=["extracted_clauses", "evidence_references", "contracts_and_relationships"])
    shared.record_agent("Odin", "complete", consumes=["contracts_and_relationships"], produces=["workstream_analysis"])
    state = {
        "run_id": "odin-portfolio-" + as_of,
        "as_of_date": as_of,
        "scope": "Multi-contract workstreams for A1, B1, B2, C1, D1 plus portfolio-wide relationship and shared-risk review",
        "status": "running",
        "portfolio_extraction": portfolio_extraction,
        "contract_graph": contract_graph,
        "contract_reconciliation": contract_reconciliation,
        "workstream_analysis": multi_contract_analysis,
        "portfolio_summary": multi_contract_analysis["portfolio_summary"],
        "portfolio_operations": portfolio_operations,
        "decision_queue": decision_queue,
        "workstreams": [
            {
                **item,
                "assigned_agents": ["Thor", "Norns", "Loki", "Heimdall", "Tyr"],
            }
            for item in multi_contract_analysis["workstreams"]
        ],
        "api_usage": budget.as_dict(),
        "collaboration": {"enabled": True, "shared_state_schema_version": "1.0", "loop_status": "pending"},
        "agent_messages": [
            {
                "from": "Thor",
                "to": "Odin",
                "type": "portfolio_relationship_graph",
                "status": "complete",
                "documents": contract_graph["node_count"],
                "relationships": contract_graph["edge_count"],
            },
            {
                "from": "Odin",
                "to": "Norns",
                "type": "multi_contract_workstreams",
                "status": multi_contract_analysis["status"],
                "workstreams": len(multi_contract_analysis["workstreams"]),
                "contracts_in_scope": multi_contract_analysis["scope"],
            },
            {
                "from": "Norns",
                "to": "Odin",
                "type": "portfolio_timeline_normalization",
                "status": "complete_with_review_items",
                "milestones": portfolio_operations["timeline"]["counts"]["total"],
                "overdue": portfolio_operations["timeline"]["counts"]["overdue"],
            },
            {
                "from": "Tyr",
                "to": "Odin",
                "type": "financial_ledger_reconciliation",
                "status": portfolio_operations["financial_reconciliation"]["status"],
                "transaction_candidates": portfolio_operations["financial_reconciliation"]["counts"]["transaction_candidates"],
                "unlinked_candidates": portfolio_operations["financial_reconciliation"]["counts"]["unlinked_candidates"],
            },
            {
                "from": "Tyr",
                "to": "Odin",
                "type": "evidence_grounded_decision_queue",
                "status": decision_queue["status"],
                "prioritized_issues": decision_queue["counts"]["total"],
                "high_priority": decision_queue["counts"]["high"],
            },
            {
                "from": "Odin",
                "to": "Tyr",
                "type": "amendment_reconciliation",
                "status": contract_reconciliation["status"],
                "resolved_changes": contract_reconciliation["summary"]["resolved_changes"],
                "review_items": contract_reconciliation["summary"]["review_items"],
            },
        ],
    }

    if not budget.reserve_call("Thor A1 extraction"):
        raise RuntimeError("Agent call budget exhausted before Thor extraction")
    for message in state["agent_messages"]:
        shared.message(
            message.get("from", "Odin"), message.get("to", "Odin"),
            message.get("type", "handoff"), message.get("status", "recorded"),
            **{key: value for key, value in message.items()
               if key not in {"from", "to", "type", "status"}}
        )

    x = extract_a1(source, use)
    terms = x.get("extracted_terms", [])
    for term in terms:
        if term.get("citation"):
            term["citation"] = verify_all([term["citation"]], {"A1": source})[0]
    x["citation_validation"] = {
        "total": len(terms),
        "verified": sum(bool(t.get("citation", {}).get("verified")) for t in terms),
        "failed": sum(not t.get("citation", {}).get("verified", False) for t in terms),
    }
    state["extraction"] = x
    shared.update("extracted_clauses", shared.data["extracted_clauses"] + terms)
    shared.update("evidence_references", shared.data["evidence_references"] + [t.get("citation") for t in terms if t.get("citation")])
    shared.record_agent("Thor", "complete", consumes=["contracts_and_relationships"], produces=["extracted_clauses", "evidence_references"])
    state["agent_messages"].append({
        "from": "Thor", "to": "Odin", "type": "extraction_complete", "status": "complete"
    })

    if not budget.reserve_call("Norns timeline calculation"):
        raise RuntimeError("Agent call budget exhausted before Norns timeline calculation")
    state["timeline"] = build_timeline(x, as_of)
    shared.update("timeline_events", shared.data["timeline_events"] + state["timeline"].get("milestones", []))
    shared.record_agent("Norns", "complete", consumes=["extracted_clauses", "contracts_and_relationships"], produces=["timeline_events", "financial_calculations"])
    state["agent_messages"].append({
        "from": "Norns", "to": "Odin", "type": "timeline_complete", "status": "complete"
    })

    events = [
        event for event in pack["event_drops"]["events_drop1.jsonl"]
        if event.get("timestamp", "")[:10] <= as_of
    ]
    if not budget.reserve_call("Loki risk review"):
        raise RuntimeError("Agent call budget exhausted before Loki risk review")
    finding = review(x, events, use)
    finding["citations"] = verify_all(finding.get("citations", []), {"A1": source})
    state["risk_finding"] = finding
    shared.record_agent("Loki", "complete", consumes=["extracted_clauses", "timeline_events", "evidence_references"], produces=["risk_claims", "unresolved_questions"])
    shared.update("risk_claims", [finding])
    shared.update("unresolved_questions", finding.get("evidence_gaps", []))
    shared.record_agent("Loki", "complete", consumes=["extracted_clauses", "timeline_events", "evidence_references"], produces=["risk_claims", "unresolved_questions"])
    state["agent_messages"].append({
        "from": "Loki", "to": "Heimdall", "type": "risk_claim", "status": "submitted"
    })

    if not budget.reserve_call("Heimdall evidence verification"):
        raise RuntimeError("Agent call budget exhausted before Heimdall verification")
    state["verification"] = verify(finding, events, finding.get("citations", []))
    state["verification"]["evidence_gaps"] = finding.get("evidence_gaps", [])
    shared.update("verification_outcomes", [state["verification"]])
    shared.record_agent("Heimdall", "complete", consumes=["risk_claims", "evidence_references"], produces=["verification_outcomes", "unresolved_questions"])
    state["agent_messages"].append({
        "from": "Heimdall", "to": "Tyr", "type": "verification",
        "status": state["verification"]["status"],
    })
    def targeted_follow_up(previous_finding, previous_verification, iteration):
        # A targeted, deterministic re-analysis uses the exact verification gaps.
        # Claude is deliberately disabled in retries so the bounded loop cannot
        # create hidden model calls outside the execution budget.
        followup_extraction = extract_a1(source, False)
        relevant_events = [
            event for event in events
            if any(token.casefold() in str(event.get("body", "")).casefold()
                   for token in ("incident", "notification", "awareness", "outage", "notice"))
        ]
        revised_finding = review(followup_extraction, relevant_events, False)
        revised_finding["targeted_follow_up"] = {
            "iteration": iteration,
            "requested_gaps": previous_verification.get("evidence_gaps", []),
            "scope": "incident awareness and notice-delivery evidence",
            "note": "Re-analysis cannot manufacture missing source records; missing proof remains unresolved.",
        }
        revised_finding["citations"] = verify_all(revised_finding.get("citations", []), {"A1": source})
        # This retry only re-reads existing documents/events; it cannot resolve
        # external evidence gaps without new source records.
        revised_finding["evidence_gaps"] = list(dict.fromkeys(
            list(previous_verification.get("evidence_gaps", []) or [])
            + list(revised_finding.get("evidence_gaps", []) or [])
        ))
        revised_verification = verify(revised_finding, relevant_events, revised_finding.get("citations", []))
        revised_verification["evidence_gaps"] = list(dict.fromkeys(
            list(previous_verification.get("evidence_gaps", []) or [])
            + list(revised_verification.get("evidence_gaps", []) or [])
            + list(revised_finding.get("evidence_gaps", []) or [])
        ))
        shared.message("Odin", "Thor", "targeted_follow_up_request", "issued",
                       iteration=iteration, missing_evidence=previous_verification.get("evidence_gaps", []))
        shared.message("Thor", "Loki", "targeted_extraction", "complete", iteration=iteration,
                       terms=len(followup_extraction.get("extracted_terms", [])))
        shared.message("Loki", "Heimdall", "revised_risk_claim", "submitted", iteration=iteration)
        shared.message("Heimdall", "Odin", "follow_up_verification", revised_verification.get("status", "unknown"),
                       iteration=iteration, unresolved=previous_verification.get("evidence_gaps", []))
        return revised_finding, revised_verification

    finding, verification, loop_summary = run_bounded_follow_up(
        finding, state["verification"], MAX_AGENT_ITERATIONS, budget, targeted_follow_up
    )
    # Keep the risk claim and verifier aligned: a gap is not closed merely
    # because a later deterministic pass omitted it.
    finding["evidence_gaps"] = list(verification.get("evidence_gaps", []) or [])
    state["risk_finding"] = finding
    state["verification"] = verification
    state["collaboration"] = {
        "enabled": True,
        "shared_state_schema_version": "1.0",
        "loop_status": "needs_human_follow_up" if loop_summary["needs_human_follow_up"] else "verified_or_no_follow_up_needed",
        "loop": loop_summary,
    }
    shared.update("risk_claims", [finding])
    shared.update("verification_outcomes", [verification])
    shared.update("unresolved_questions", verification.get("evidence_gaps", finding.get("evidence_gaps", [])))
    shared.record_agent("Heimdall", "complete_with_gaps" if loop_summary["needs_human_follow_up"] else "verified",
                        iteration=budget.iterations_used, consumes=["risk_claims", "evidence_references"],
                        produces=["verification_outcomes", "unresolved_questions"])
    if not budget.reserve_call("Tyr ruling"):
        state["ruling"] = {
            "agent": "Tyr", "decision": "deferred_budget_exhausted",
            "rationale": "The configured execution budget was exhausted before a ruling could be produced.",
            "approved_facts": [], "rejected_or_unproven_claims": ["No ruling was generated."],
            "action_draft": None, "human_approval_required": True,
        }
        shared.record_agent("Tyr", "skipped_budget_exhausted", consumes=["verification_outcomes"])
    else:
        state["ruling"] = arbitrate(finding, verification)
        shared.record_agent("Tyr", "complete", iteration=budget.iterations_used,
                            consumes=["risk_claims", "verification_outcomes", "unresolved_questions"],
                            produces=["recommended_actions"])
    shared.update("recommended_actions", [state["ruling"].get("action_draft")] if state["ruling"].get("action_draft") else [])
    shared.message("Tyr", "Odin", "ruling", state["ruling"].get("decision", "complete"),
                   unresolved_questions=shared.data["unresolved_questions"])
    state["agent_messages"].append({
        "from": "Tyr", "to": "Odin", "type": "ruling", "status": "complete"
    })

    state["event_summary"] = {
        "drop1_events_available_as_of_date": len(events),
        "drop2_events_loaded": len(pack["event_drops"]["events_drop2.jsonl"]),
        "parse_errors": pack["parse_errors"],
    }
    state["status"] = "complete_with_limitations"
    state["agent_modes"] = {
        name: ("claude" if use and name in ("Thor", "Loki") else "deterministic")
        for name in ["Odin", "Thor", "Norns", "Loki", "Heimdall", "Tyr"]
    }
    state["limitations"] = [
        "Each in-scope contract has a source-specific workstream; extracted lines are candidates, not final legal interpretations.",
        "A1/A3 non-renewal notice period is explicitly reconciled; other amendment sections remain review items.",
        "Cross-contract exclusivity and shared-provider signals are potential review items, not adjudicated conflicts.",
        "Dates are extracted only when explicitly stated; relative deadlines require trigger evidence and are not guessed.",
        "Financial amounts are quoted individually; aggregate exposure is not calculated without invoice, period, and trigger evidence.",
        "Phase 3 classifies explicit dates by context and identifies payment-ledger/event candidates; rows remain unverified until reconciled to contract, invoice, trigger, and payment/credit evidence.",
        "Phase 4 ranks review tasks using deterministic evidence/status rules; prioritization is not a legal or accounting conclusion.",
        "Norns, Heimdall, and Tyr use deterministic logic in this version.",
        "Draft actions require human approval and are never sent automatically.",
    ]
    state["shared_state"] = shared.snapshot()
    state["shared_state"]["status"] = state["status"]
    state["api_usage"] = budget.as_dict()
    state["shared_state"]["api_usage"] = budget.as_dict()
    state["shared_state"]["iteration"] = {"current": budget.iterations_used, "max": budget.max_iterations, "stop_reason": loop_summary["stop_reason"]}
    state["api_usage"]["note"] = "Counts orchestrated agent/task invocations, including each bounded follow-up task; provider-internal retries are not observable here."
    # Merge handoffs emitted by the legacy pipeline into the canonical shared log.
    known = {
        (item.get("from"), item.get("to"), item.get("type"), item.get("status"))
        for item in state["shared_state"]["agent_messages"]
    }
    for message in state.get("agent_messages", []):
        key = (message.get("from"), message.get("to"), message.get("type"), message.get("status"))
        if key not in known:
            state["shared_state"]["agent_messages"].append(message)
            known.add(key)
    state["collaboration"]["agents"] = state["shared_state"]["agent_status"]
    state["collaboration"]["handoff_count"] = len(state["shared_state"]["agent_messages"])
    state["collaboration"]["unresolved_questions"] = state["shared_state"]["unresolved_questions"]
    state["collaboration"]["recommended_actions"] = state["shared_state"]["recommended_actions"]
    state["agent_messages"] = state["shared_state"]["agent_messages"]
    return state
