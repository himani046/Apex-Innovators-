"""Phase 3: normalized portfolio timeline and evidence-led payment ledger.

This module normalizes dates and monetary references without treating contract
price caps as incurred loss. Ledger items are evidence candidates, not accounting
entries, unless an event explicitly identifies a contract and transaction amount.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

MONEY_RE = re.compile(r"(?i)(?:USD\\s*)?\\$\\s?[\\d,]+(?:\\.\\d{2})?|\\b(?:\\d[\\d,]*\\.\\d{2})\\s*(?:U\\.S\\.\\s*)?Dollars?\\b")
TRANSACTION_RE = re.compile(r"\\b(invoice|invoiced|payment|paid|remittance|refund|reimburse|service credit|credit memo|billing|past due|overdue)\\b", re.I)
CONTRACT_IDS = ("A1", "A2", "A3", "B1", "B2", "C1", "D1", "STD")


def _amounts(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).strip() for match in MONEY_RE.finditer(text)))


def build_portfolio_operations(workstream_analysis: dict[str, Any],
                               event_drops: dict[str, list[dict[str, Any]]],
                               as_of: str) -> dict[str, Any]:
    """Build normalized deadline and payment-event views with explicit confidence."""
    as_of_date = date.fromisoformat(as_of)
    workstreams = workstream_analysis.get("workstreams", [])
    deadlines = []
    contract_amounts = []
    for stream in workstreams:
        if stream.get("id") == "portfolio-wide":
            continue
        root = stream.get("primary_contract_id") or stream.get("id", "").replace("contract-", "")
        for item in stream.get("deadlines", []):
            raw_date = item.get("date")
            try:
                parsed = date.fromisoformat(str(raw_date))
            except ValueError:
                continue
            status = "overdue" if parsed < as_of_date else "due_today" if parsed == as_of_date else "upcoming"
            deadlines.append({
                "contract_id": root,
                "date": parsed.isoformat(),
                "status": status,
                "title": item.get("title", ""),
                "evidence": item.get("evidence", {}),
            })
        for amount in (stream.get("financial_exposure") or {}).get("amounts_found", []):
            contract_amounts.append({
                "contract_id": amount.get("evidence", {}).get("document_id", root),
                "amount_text": amount.get("amount_text", ""),
                "context": amount.get("context", ""),
                "evidence": amount.get("evidence", {}),
                "classification": "contract_stated_amount_unreconciled",
                "ledger_effect": "none_without_transaction_evidence",
            })

    deadlines.sort(key=lambda item: (item["date"], item["contract_id"], item["title"]))
    ledger = []
    seen_events = set()
    for drop_name, events in event_drops.items():
        for index, event in enumerate(events):
            event_id = str(event.get("event_id") or event.get("id") or f"{drop_name}:{index + 1}")
            if event_id in seen_events:
                continue
            seen_events.add(event_id)
            timestamp = str(event.get("timestamp", ""))
            if timestamp[:10] and timestamp[:10] > as_of:
                continue
            body = str(event.get("body", ""))
            summary = str(event.get("summary", ""))
            text = (summary + "\\n" + body).strip()
            if not TRANSACTION_RE.search(text):
                continue
            ids = [cid for cid in CONTRACT_IDS if re.search(rf"(?<![A-Za-z0-9]){re.escape(cid)}(?![A-Za-z0-9])", text)]
            amounts = _amounts(text)
            ledger.append({
                "event_id": event_id,
                "event_source": drop_name,
                "timestamp": timestamp,
                "transaction_signal": TRANSACTION_RE.search(text).group(0).lower(),
                "amounts_found": amounts,
                "contract_id": ids[0] if len(ids) == 1 else None,
                "contract_match_status": "explicit_contract_id" if len(ids) == 1 else "ambiguous_or_missing_contract_id",
                "summary": summary,
                "evidence_text": text[:1200],
                "reconciliation_status": "candidate_requires_invoice_and_payment_record" if amounts else "transaction_signal_without_explicit_amount",
                "human_review_required": True,
            })

    matched = sum(item["contract_id"] is not None for item in ledger)
    return {
        "as_of_date": as_of,
        "timeline": {
            "milestones": deadlines,
            "counts": {
                "total": len(deadlines),
                "overdue": sum(item["status"] == "overdue" for item in deadlines),
                "due_today": sum(item["status"] == "due_today" for item in deadlines),
                "upcoming": sum(item["status"] == "upcoming" for item in deadlines),
            },
            "normalization_note": "Only explicit source dates are normalized. Relative periods are not converted without trigger dates.",
        },
        "financial_reconciliation": {
            "contract_amounts": contract_amounts,
            "payment_ledger_candidates": ledger,
            "counts": {
                "contract_amounts": len(contract_amounts),
                "transaction_candidates": len(ledger),
                "contract_linked_candidates": matched,
                "unlinked_candidates": len(ledger) - matched,
            },
            "portfolio_total_usd": None,
            "status": "evidence_candidates_only",
            "reconciliation_rule": "No contract amount is treated as incurred exposure. No totals are calculated without a contract-linked invoice, trigger, and payment/credit status.",
            "unresolved_questions": [
                "Which invoice or credit memo corresponds to each transaction event?",
                "Is the amount invoiced, paid, disputed, credited, capped, recurring, or merely a contractual rate?",
                "What contract-specific trigger and period make each amount applicable?",
            ],
        },
        "notice": "Operational timeline and financial triage only; not accounting advice or a finding of breach or loss.",
    }
