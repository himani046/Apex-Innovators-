"""FR8 report synthesis from structured, source-grounded run outputs.

This module assembles reports; it does not invent legal conclusions or financial totals.
"""
from __future__ import annotations

from typing import Any


def _unique(items: list[Any], key_fields: tuple[str, ...] = ()) -> list[Any]:
    seen: set[str] = set()
    result = []
    for item in items:
        if key_fields and isinstance(item, dict):
            key = "|".join(str(item.get(field, "")) for field in key_fields)
        else:
            key = repr(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def build_synthesis(run: dict[str, Any]) -> dict[str, Any]:
    """Build one report per known contract and one company-wide report."""
    portfolio = run.get("portfolio_extraction", {}).get("contracts", {}) or {}
    workstream_analysis = run.get("workstream_analysis", {}) or {}
    workstreams = workstream_analysis.get("workstreams", []) or []
    operations = run.get("portfolio_operations", {}) or {}
    milestones = (operations.get("timeline", {}) or {}).get("milestones", []) or []
    queue = run.get("decision_queue", {}) or {}
    issues = queue.get("issues", []) or []
    graph = run.get("contract_graph", {}) or {}
    contract_ids = set(portfolio)
    cross_contract_edges = [edge for edge in (graph.get("edges", []) or [])
                            if str(edge.get("source", "")) in contract_ids and str(edge.get("target", "")) in contract_ids]
    reconciliation = run.get("contract_reconciliation", {}) or {}
    finding = run.get("evidence_grounded_finding", {}) or {}
    ruling = run.get("ruling", {}) or {}
    financial = operations.get("financial_reconciliation", {}) or {}
    timeline = run.get("timeline", {}) or {}

    reports = []
    for contract_id, extraction in sorted(portfolio.items()):
        terms = extraction.get("extracted_terms", []) or []
        citations = [term.get("citation", {}) for term in terms if term.get("citation")]
        contract_streams = [
            stream for stream in workstreams
            if contract_id in (stream.get("contract_ids", []) or [])
            and stream.get("id") != "portfolio-shared-risk"
        ]
        stream_terms = [
            term for stream in contract_streams
            for term in (stream.get("extracted_obligations", []) or [])
        ]
        stream_dates = [
            item for stream in contract_streams
            for item in (stream.get("timeline_candidates", []) or [])
        ]
        contract_milestones = [m for m in milestones if str(m.get("contract_id", "")) == contract_id]
        contract_issues = [i for i in issues if str(i.get("contract_id", "")) == contract_id]
        if contract_id == finding.get("contract_id"):
            contract_finding = finding
            contract_ruling = ruling
        else:
            contract_finding = None
            contract_ruling = None
        gaps = _unique([
            gap for stream in contract_streams
            for gap in (stream.get("open_questions", []) or [])
        ] + (contract_finding.get("missing_evidence", []) if contract_finding else []))
        verified = sum(bool(c.get("verified")) for c in citations)
        confidence_values = [
            float(term.get("confidence"))
            for term in terms
            if isinstance(term.get("confidence"), (int, float))
        ]
        reports.append({
            "contract_id": contract_id,
            "status": "complete_with_review_items" if gaps or any(not c.get("verified") for c in citations) else "source_triage_complete",
            "key_terms": terms,
            "obligations": stream_terms,
            "timeline": _unique(contract_milestones + stream_dates, ("date", "title", "contract_id")),
            "risks": contract_issues + ([contract_finding] if contract_finding else []),
            "recommended_actions": (
                [contract_ruling.get("action_draft")]
                if contract_ruling and contract_ruling.get("action_draft") else
                [i.get("recommended_next_step") for i in contract_issues if i.get("recommended_next_step")]
            ),
            "citations": citations,
            "citation_validation": {
                "total": len(citations),
                "verified": verified,
                "failed": len(citations) - verified,
            },
            "confidence": round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None,
            "unresolved_questions": gaps,
            "notice": "Source-grounded triage, not legal advice. Extracted terms and risk signals require human review.",
        })

    overlap = (workstream_analysis.get("portfolio_summary", {}) or {}).get("potential_exclusivity_overlap", [])
    resolved_changes = reconciliation.get("resolved_changes", []) or []
    review_items = reconciliation.get("review_items", []) or []
    exposure = financial.get("aggregate_exposure")
    if not isinstance(exposure, (int, float)):
        exposure = None
    prioritized = sorted(
        issues,
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(item.get("priority", "")).lower(), 4),
            str(item.get("date", "9999-99-99")),
        ),
    )
    all_citations = []
    for report in reports:
        all_citations.extend(report["citations"])
    all_citations.extend(finding.get("evidence", []) or [])
    all_citations = _unique(all_citations, ("document_id", "clause_reference", "quote"))

    run_status = str(run.get("status") or "complete_with_limitations")
    allowed_run_statuses = {
        "running", "complete", "complete_with_review_items", "complete_with_limitations",
        "source_triage_complete", "partial_budget_exhausted", "partial_review_limit_reached",
        "failed", "not_run",
    }
    if run_status not in allowed_run_statuses:
        run_status = "complete_with_limitations"
    company_report = {
        "title": "Quillhub portfolio risk report" if run.get("scope") else "Company portfolio risk report",
        "as_of_date": run.get("as_of_date"),
        "status": run_status,
        "contract_count": len(reports),
        "contract_reports": len(reports),
        "cross_contract_relationships": cross_contract_edges,
        "resolved_amendment_changes": resolved_changes,
        "cross_contract_review_items": review_items,
        "potential_shared_risks": overlap,
        "total_financial_exposure": exposure,
        "financial_exposure_status": "calculated_from_supported_inputs" if exposure is not None else "not_calculated_insufficient_reconciliation_evidence",
        "financial_reconciliation": {
            "status": financial.get("status", "not_calculated"),
            "counts": financial.get("counts", {}),
            "invoice_reconciliation_candidates": financial.get("invoice_reconciliation_candidates", []),
            "unresolved_questions": financial.get("unresolved_questions", []),
            "confirmed_liability": False,
            "note": "Ledger and invoice links remain candidates until contract triggers, billing periods, payment/credit application, and source evidence are reconciled.",
        },
        "prioritized_action_list": prioritized,
        "worst_case_projection": {
            "timeline": timeline.get("milestones", []) or milestones,
            "note": timeline.get("worst_case_note") or (
                "A defensible portfolio-wide worst-case financial projection is unavailable until trigger dates, amounts, periods, and payment status are reconciled."
            ),
        },
        "references": all_citations,
        "unresolved_questions": _unique(
            (finding.get("missing_evidence", []) or [])
            + (run.get("collaboration", {}).get("unresolved_questions", []) or [])
            + [item.get("summary", item.get("reason", "Review required")) for item in review_items]
        ),
        "limitations": [
            "Potential relationships are review candidates, not automatically proven legal conflicts.",
            "Financial exposure is not calculated unless supported by reconciled source data.",
            "Reports are decision support and require qualified human review.",
        ],
    }
    return {
        "schema_version": "1.0",
        "contract_reports": reports,
        "company_risk_report": company_report,
        "status": run_status,
    }
