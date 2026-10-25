from datetime import date

from backend.config import PACK_DIR, USE_CLAUDE, MAX_AGENT_CALLS, MAX_AGENT_ITERATIONS
from backend.services.ingestion import load_pack
from backend.services.citations import verify_all
from backend.services.contract_graph import build_contract_graph, reconcile_contracts
from backend.services.workstreams import build_workstreams
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
    source = contracts.get("A1")
    if not source:
        raise RuntimeError("A1.txt missing from supplied pack")

    use = request_claude and USE_CLAUDE
    state = {
        "run_id": "odin-a1-" + as_of,
        "as_of_date": as_of,
        "scope": "Multi-contract workstreams for A1, B1, B2, C1, D1 plus portfolio-wide relationship and shared-risk review",
        "status": "running",
        "portfolio_extraction": portfolio_extraction,
        "contract_graph": contract_graph,
        "contract_reconciliation": contract_reconciliation,
        "workstream_analysis": multi_contract_analysis,
        "portfolio_summary": multi_contract_analysis["portfolio_summary"],
        "workstreams": [
            {
                **item,
                "assigned_agents": ["Thor", "Norns", "Loki", "Heimdall", "Tyr"],
            }
            for item in multi_contract_analysis["workstreams"]
        ],
        "api_usage": {"max_calls": MAX_AGENT_CALLS, "max_iterations": MAX_AGENT_ITERATIONS},
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
                "from": "Odin",
                "to": "Tyr",
                "type": "amendment_reconciliation",
                "status": contract_reconciliation["status"],
                "resolved_changes": contract_reconciliation["summary"]["resolved_changes"],
                "review_items": contract_reconciliation["summary"]["review_items"],
            },
        ],
    }

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
    state["agent_messages"].append({
        "from": "Thor", "to": "Odin", "type": "extraction_complete", "status": "complete"
    })

    state["timeline"] = build_timeline(x, as_of)
    state["agent_messages"].append({
        "from": "Norns", "to": "Odin", "type": "timeline_complete", "status": "complete"
    })

    events = [
        event for event in pack["event_drops"]["events_drop1.jsonl"]
        if event.get("timestamp", "")[:10] <= as_of
    ]
    finding = review(x, events, use)
    finding["citations"] = verify_all(finding.get("citations", []), {"A1": source})
    state["risk_finding"] = finding
    state["agent_messages"].append({
        "from": "Loki", "to": "Heimdall", "type": "risk_claim", "status": "submitted"
    })

    state["verification"] = verify(finding, events, finding.get("citations", []))
    state["agent_messages"].append({
        "from": "Heimdall", "to": "Tyr", "type": "verification",
        "status": state["verification"]["status"],
    })
    state["ruling"] = arbitrate(finding, state["verification"])
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
        "Norns, Heimdall, and Tyr use deterministic logic in this version.",
        "Draft actions require human approval and are never sent automatically.",
    ]
    return state
