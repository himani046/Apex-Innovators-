"""Phase 3: normalized portfolio timeline and evidence-led payment ledger.

Dates are classified by their source context; historical/effective dates are not
misreported as overdue action items. Payment CSV rows and event-drop references
are surfaced as candidates with explicit linkage and review status, never as
accounting conclusions.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

MONEY_RE = re.compile(r"(?i)(?:USD\s*)?\$\s?[\d,]+(?:\.\d{2})?|\b(?:\d[\d,]*\.\d{2})\s*(?:U\.S\.\s*)?Dollars?\b")
TRANSACTION_RE = re.compile(r"\b(invoice|invoiced|payment|paid|remittance|refund|reimburse|service credit|credit memo|billing|past due|overdue|ledger|fee)\b", re.I)
CONTRACT_IDS = ("A1", "A2", "A3", "B1", "B2", "C1", "D1", "STD")
CONTRACT_REF_MAP = {
    "QH-STRATO-2026-001": "A1",
    "QH-HARBOR-2026-001": "B1",
    "QH-VANTAGE-2026-001": "C1",
    "QH-PIXEL-2026-001": "D1",
}


def _amounts(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).strip() for match in MONEY_RE.finditer(text)))


def _classify_date(title: str) -> tuple[str, str]:
    """Return (date_type, explanation) using only local source wording."""
    text = title.casefold()
    if re.search(r"\b(effective date|dated\s+|signature date|incident start|incident end|submission date)\b|date\s*:", text):
        return "historical_reference", "Source date is contextual or historical; it is not an action deadline by itself."
    if re.search(r"\b(due date|deadline|no later than|must be received by|submit by|pay by|notify by|renewal instructions by)\b", text):
        return "action_deadline", "Source explicitly describes a due date or action deadline."
    if re.search(r"\b(expir(?:y|ation)|term ends?|ending|through\s+[a-z]+\s+\d{1,2})\b", text):
        return "contract_milestone", "Contract term or expiry milestone; verify applicable notice/trigger requirements separately."
    if re.search(r"\b(non-renewal notice period|notice period|within\s+\d+)\b", text):
        return "relative_or_notice_term", "Notice window is stated, but its trigger/deadline cannot be inferred from this date alone."
    return "source_date_unclassified", "Source contains an explicit date but does not establish that it is an actionable deadline."


def _contract_link(text: str) -> tuple[str | None, str]:
    explicit_refs = [ref for ref in CONTRACT_REF_MAP if ref.casefold() in text.casefold()]
    if len(explicit_refs) == 1:
        return CONTRACT_REF_MAP[explicit_refs[0]], "explicit_contract_reference"
    ids = [cid for cid in CONTRACT_IDS if re.search(rf"(?<![A-Za-z0-9]){re.escape(cid)}(?![A-Za-z0-9])", text)]
    if len(ids) == 1:
        return ids[0], "explicit_document_id"
    return None, "ambiguous_or_missing_contract_reference"


def build_portfolio_operations(workstream_analysis: dict[str, Any],
                               event_drops: dict[str, list[dict[str, Any]]],
                               as_of: str,
                               payment_ledger: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build contextual timeline and ledger candidates as of the simulated date."""
    as_of_date = date.fromisoformat(as_of)
    workstreams = workstream_analysis.get("workstreams", [])
    deadlines: list[dict[str, Any]] = []
    contract_amounts: list[dict[str, Any]] = []
    for stream in workstreams:
        if stream.get("id") == "portfolio-wide":
            continue
        root = stream.get("primary_contract_id") or stream.get("id", "").replace("contract-", "")
        for item in stream.get("deadlines", []):
            try:
                parsed = date.fromisoformat(str(item.get("date")))
            except (ValueError, TypeError):
                continue
            title = str(item.get("title", ""))
            date_type, explanation = _classify_date(title)
            if date_type == "action_deadline":
                status = "overdue" if parsed < as_of_date else "due_today" if parsed == as_of_date else "upcoming"
            elif date_type == "historical_reference":
                status = "past_reference" if parsed < as_of_date else "today_reference" if parsed == as_of_date else "future_reference"
            elif date_type == "contract_milestone":
                status = "past_milestone" if parsed < as_of_date else "today_milestone" if parsed == as_of_date else "upcoming_milestone"
            else:
                status = "past_unclassified" if parsed < as_of_date else "today_unclassified" if parsed == as_of_date else "upcoming_unclassified"
            deadlines.append({
                "contract_id": (item.get("evidence") or {}).get("document_id") or root,
                "date": parsed.isoformat(),
                "status": status,
                "date_type": date_type,
                "action_required_by_date": date_type == "action_deadline",
                "classification_note": explanation,
                "title": title,
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
    ledger: list[dict[str, Any]] = []
    seen_events: set[str] = set()

    # Actual supplied CSV rows are a primary financial source; keep their source
    # date, counterparty, reference and status instead of relying on event keywords.
    for index, row in enumerate(payment_ledger or []):
        row_date = str(row.get("date", ""))
        if row_date[:10] and row_date[:10] > as_of:
            continue
        reference = str(row.get("reference", ""))
        combined = " ".join(str(row.get(key, "")) for key in ("from", "to", "reference", "status", "amount"))
        contract_id, match_status = _contract_link(combined)
        amount = str(row.get("amount", "")).strip()
        try:
            amount_text = f"$ {float(amount):,.2f}"
        except (TypeError, ValueError):
            amount_text = amount
        event_id = f"payment-ledger:{row_date}:{index + 1}"
        ledger.append({
            "event_id": event_id,
            "event_source": "payments_ledger.csv",
            "timestamp": row_date,
            "transaction_signal": str(row.get("status", "transaction")).lower(),
            "amounts_found": [amount_text] if amount_text else [],
            "contract_id": contract_id,
            "contract_match_status": match_status,
            "summary": reference,
            "counterparty_from": str(row.get("from", "")),
            "counterparty_to": str(row.get("to", "")),
            "payment_status": str(row.get("status", "unknown")).lower(),
            "evidence_text": combined[:1200],
            "reconciliation_status": "ledger_row_linked_for_review" if contract_id else "ledger_row_needs_contract_linkage",
            "human_review_required": True,
        })
        seen_events.add(event_id)

    # Event drops can corroborate invoices, credits and payment events. Include
    # subject/from/to as well as body because records often store the signal there.
    for drop_name, events in event_drops.items():
        for index, event in enumerate(events):
            event_id = str(event.get("event_id") or event.get("id") or f"{drop_name}:{index + 1}")
            if event_id in seen_events:
                continue
            seen_events.add(event_id)
            timestamp = str(event.get("timestamp", ""))
            if timestamp[:10] and timestamp[:10] > as_of:
                continue
            fields = ("subject", "summary", "body", "from", "to", "channel")
            text = "\n".join(str(event.get(key, "")) for key in fields).strip()
            if not TRANSACTION_RE.search(text):
                continue
            contract_id, match_status = _contract_link(text)
            amounts = _amounts(text)
            signal = TRANSACTION_RE.search(text)
            ledger.append({
                "event_id": event_id,
                "event_source": drop_name,
                "timestamp": timestamp,
                "transaction_signal": signal.group(0).lower() if signal else "transaction",
                "amounts_found": amounts,
                "contract_id": contract_id,
                "contract_match_status": match_status,
                "summary": str(event.get("subject") or event.get("summary") or ""),
                "evidence_text": text[:1200],
                "reconciliation_status": "event_candidate_needs_ledger_reconciliation" if amounts else "transaction_signal_without_explicit_amount",
                "human_review_required": True,
            })

    deadlines_counts = {
        "total": len(deadlines),
        "overdue": sum(item["status"] == "overdue" for item in deadlines),
        "due_today": sum(item["status"] == "due_today" for item in deadlines),
        "upcoming": sum(item["status"] == "upcoming" for item in deadlines),
        "historical_references": sum(item["date_type"] == "historical_reference" for item in deadlines),
        "contract_milestones": sum(item["date_type"] == "contract_milestone" for item in deadlines),
        "unclassified_dates": sum(item["date_type"] == "source_date_unclassified" for item in deadlines),
        "relative_or_notice_terms": sum(item["date_type"] == "relative_or_notice_term" for item in deadlines),
    }
    matched = sum(item["contract_id"] is not None for item in ledger)
    return {
        "as_of_date": as_of,
        "timeline": {
            "milestones": deadlines,
            "counts": deadlines_counts,
            "normalization_note": "Overdue status is reserved for explicitly worded action deadlines. Effective/signature/incident/reference dates and contract-term milestones are shown separately; relative periods are not converted without trigger evidence.",
        },
        "financial_reconciliation": {
            "contract_amounts": contract_amounts,
            "payment_ledger_candidates": ledger,
            "counts": {
                "contract_amounts": len(contract_amounts),
                "transaction_candidates": len(ledger),
                "contract_linked_candidates": matched,
                "unlinked_candidates": len(ledger) - matched,
                "payment_ledger_rows": sum(item["event_source"] == "payments_ledger.csv" for item in ledger),
            },
            "portfolio_total_usd": None,
            "status": "evidence_candidates_only",
            "reconciliation_rule": "Payment ledger rows are shown with source status and contract-link candidates. Contract-stated amounts are not treated as incurred exposure, and no aggregate total is calculated without validating invoice, contractual trigger, period, and payment/credit evidence.",
            "unresolved_questions": [
                "Do source ledger entries reconcile to the corresponding invoice and contract-specific billing period?",
                "Are entries paid, pending, overdue, disputed, credited, or contractual rates rather than transactions?",
                "What contract-specific trigger and period make each amount applicable?",
            ],
        },
        "notice": "Operational timeline and financial triage only; not accounting advice or a finding of breach or loss.",
    }
