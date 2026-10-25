"""Phase 4: deterministic, evidence-grounded portfolio decision queue.

Ranks review work by explicit date/status and evidence linkage. It does not
infer breach, damages, or legal outcomes, and every item remains human-reviewed.
"""
from __future__ import annotations

from typing import Any


def build_decision_queue(portfolio_operations: dict[str, Any],
                         workstream_analysis: dict[str, Any]) -> dict[str, Any]:
    timeline = (portfolio_operations.get("timeline") or {}).get("milestones", [])
    finance = portfolio_operations.get("financial_reconciliation") or {}
    ledger = finance.get("payment_ledger_candidates", [])
    issues: list[dict[str, Any]] = []

    for item in timeline:
        if not item.get("action_required_by_date"):
            continue
        status = item.get("status")
        if status not in {"overdue", "due_today", "upcoming"}:
            continue
        priority = "high" if status == "overdue" else "medium" if status == "due_today" else "low"
        evidence = item.get("evidence") or {}
        issues.append({
            "issue_id": f"timeline:{item.get('contract_id')}:{item.get('date')}:{len(issues) + 1}",
            "category": "contract_deadline",
            "title": item.get("title") or "Explicit source deadline",
            "contract_id": item.get("contract_id"),
            "priority": priority,
            "status": status,
            "date": item.get("date"),
            "evidence_strength": "verified_source_quote" if evidence.get("verified") else "source_quote_unverified",
            "evidence": evidence,
            "reason": item.get("classification_note", ""),
            "recommended_next_step": "Confirm owner, trigger, and completion evidence; escalate only after validating applicability.",
            "human_review_required": True,
        })

    for group in finance.get("invoice_reconciliation_candidates", []) or []:
        disagreement = not bool(group.get("amounts_consistent", True))
        issues.append({
            "issue_id": f"invoice-reconciliation:{group.get('contract_id')}:{group.get('invoice_reference')}",
            "category": "invoice_payment_reconciliation",
            "title": "Reconcile invoice " + str(group.get("invoice_reference") or "reference"),
            "contract_id": group.get("contract_id"),
            "priority": "high" if disagreement else "medium",
            "status": "amount_disagreement_requires_review" if disagreement else group.get("status", "linked_candidate_requires_human_review"),
            "date": None,
            "amounts_found": group.get("amount_candidates", []),
            "evidence_strength": "explicit_invoice_reference_candidate",
            "evidence": {
                "invoice_reference": group.get("invoice_reference"),
                "source_event_ids": group.get("source_event_ids", []),
                "candidate_kinds": group.get("candidate_kinds", []),
                "amounts_consistent": group.get("amounts_consistent"),
                "confirmed_liability": False,
            },
            "reason": group.get("note", "Invoice linkage is a candidate and does not establish a confirmed liability."),
            "recommended_next_step": "Compare the invoice, contract billing trigger and period, payment confirmation, and credits before calculating exposure.",
            "human_review_required": True,
        })

    for item in ledger:
        payment_status = str(item.get("payment_status") or item.get("transaction_signal") or "").casefold()
        match_status = item.get("contract_match_status", "")
        if payment_status == "overdue":
            priority, status = "high", "ledger_marked_overdue"
            reason = "Source ledger marks this row overdue; verify the invoice, contractual due date, and current status."
        elif item.get("contract_id") is None:
            priority, status = "medium", "contract_link_unresolved"
            reason = "A transaction row exists but its contract could not be linked uniquely."
        elif payment_status in {"pending", "unpaid"}:
            priority, status = "medium", "ledger_marked_pending"
            reason = "Source ledger marks this row pending; confirm whether this is still current and what payment trigger applies."
        else:
            # Paid rows remain visible in reconciliation but don't crowd the action queue.
            continue
        issues.append({
            "issue_id": f"ledger:{item.get('event_id')}",
            "category": "financial_reconciliation",
            "title": item.get("summary") or "Payment ledger row requires review",
            "contract_id": item.get("contract_id"),
            "priority": priority,
            "status": status,
            "date": item.get("timestamp"),
            "amounts_found": item.get("amounts_found", []),
            "evidence_strength": "source_ledger_row",
            "evidence": {
                "source": item.get("event_source"),
                "event_id": item.get("event_id"),
                "text": item.get("evidence_text") or item.get("summary", ""),
                "contract_match_status": match_status,
                "payment_status": payment_status,
            },
            "reason": reason,
            "recommended_next_step": "Match against the invoice and payment/credit proof before recording exposure or sending a notice.",
            "human_review_required": True,
        })

    priority_order = {"high": 0, "medium": 1, "low": 2}
    category_order = {"contract_deadline": 0, "financial_reconciliation": 1, "invoice_payment_reconciliation": 2}
    issues.sort(key=lambda item: (
        priority_order.get(item["priority"], 9),
        item.get("date") or "",
        category_order.get(item["category"], 9),
        item["issue_id"],
    ))
    counts = {
        "total": len(issues),
        "high": sum(item["priority"] == "high" for item in issues),
        "medium": sum(item["priority"] == "medium" for item in issues),
        "low": sum(item["priority"] == "low" for item in issues),
        "deadline_issues": sum(item["category"] == "contract_deadline" for item in issues),
        "financial_issues": sum(item["category"] in {"financial_reconciliation", "invoice_payment_reconciliation"} for item in issues),
    }
    return {
        "status": "prioritized_for_human_review",
        "as_of_date": portfolio_operations.get("as_of_date"),
        "counts": counts,
        "issues": issues,
        "decision_policy": [
            "Only explicitly worded due dates can be marked overdue.",
            "Effective dates, historical references, and term milestones are not overdue action items by themselves.",
            "Financial status comes from source ledger/event evidence and must be reconciled to invoice and trigger evidence.",
            "Invoice-reference groups are review candidates only; inconsistent amounts are escalated without calculating a liability or exposure total.",
            "No breach, damages, or aggregate exposure is inferred by this queue.",
        ],
        "notice": "Deterministic triage queue for human review; not legal, accounting, or breach determinations.",
    }
