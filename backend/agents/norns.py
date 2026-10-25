"""Norns: evidence-grounded timeline and conservative worst-case projection.

The generic path never assumes a contract ID, start/end date, fee, or penalty.
It normalizes dates only when they can be parsed, preserves the source citation,
and clearly distinguishes a calendar milestone from an actionable deadline.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

_DATE_PATTERNS = (
    re.compile(r"\b(?P<iso>\d{4}-\d{2}-\d{2})\b"),
    re.compile(
        r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b", re.I
    ),
    re.compile(
        r"\b(?P<day>\d{1,2})\s+(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(?P<year>\d{4})\b", re.I
    ),
)
_ACTION_TERMS = re.compile(
    r"\b(due|deadline|pay by|no later than|notify by|notice by|renewal date|expires on|termination date)\b", re.I
)
_MILESTONE_TERMS = re.compile(r"\b(effective date|commencement|expires?|expiration|term ends?|renewal)\b", re.I)
_AMOUNT = re.compile(r"(?i)(?:USD\s*)?\$\s?[\d,]+(?:\.\d{2})?|\b\d[\d,]*\.\d{2}\s*(?:U\.S\.\s*)?Dollars?\b")
_RATE = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*%\s*(?:per month|monthly|per annum|annually|per year)?")


def _parse_date(value: str) -> date | None:
    value = value.strip().replace(",", "")
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    for fmt in ("%B %d %Y", "%d %B %Y"):
        from datetime import datetime
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _candidate_dates(quote: str):
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(quote):
            if match.groupdict().get("iso"):
                raw = match.group("iso")
            elif match.groupdict().get("month") and match.groupdict().get("day"):
                raw = f"{match.group('month')} {match.group('day')}, {match.group('year')}"
            else:
                raw = f"{match.group('day')} {match.group('month')} {match.group('year')}"
            yield raw, _parse_date(raw), match.start(), match.end()


def build_timeline(extraction: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Backward-compatible general timeline builder; accepts any Thor extraction."""
    contract_id = str(extraction.get("contract_id") or "unknown")
    milestones = build_contract_timeline(contract_id, extraction, as_of)
    return {
        "agent": "Norns",
        "contract_id": contract_id,
        "as_of_date": as_of,
        "milestones": milestones,
        "status": "computed_with_review_items" if any(x.get("status") == "date_candidate" for x in milestones) else "computed",
        "worst_case_projection": build_worst_case_projection(contract_id, extraction, milestones),
        "note": "Only source-stated dates and amounts are used; a date is not an actionable deadline without a supported trigger.",
    }


def build_contract_timeline(contract_id: str, extraction: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Extract explicit dates from citation text for a contract of any ID."""
    current = date.fromisoformat(as_of)
    milestones: dict[tuple[str, str, str], dict[str, Any]] = {}
    for term_index, term in enumerate(extraction.get("extracted_terms", [])):
        citation = term.get("citation") or {}
        quote = str(citation.get("quote", ""))
        if not quote:
            continue
        for raw, parsed, start, end in _candidate_dates(quote):
            nearby = quote[max(0, start - 100):min(len(quote), end + 100)]
            if parsed is None:
                status, normalized = "date_candidate", None
                note = "Date-like text is present but could not be normalized; no deadline calculation was performed."
            else:
                normalized = parsed.isoformat()
                status = "past" if parsed < current else "today" if parsed == current else "upcoming"
                note = "Explicit date compared with the selected simulated date; contractual trigger and counting convention still need verification."
            if _ACTION_TERMS.search(nearby):
                date_type = "deadline_or_notice"
            elif _MILESTONE_TERMS.search(nearby):
                date_type = "contract_milestone"
            else:
                date_type = "reference_date"
            record = {
                "id": f"{contract_id}:date:{term_index}:{start}",
                "contract_id": contract_id,
                "date": normalized or raw,
                "date_text": raw,
                "raw_date": raw,
                "date_type": date_type,
                "date_classification": "possible_action_deadline" if date_type == "deadline_or_notice" else date_type,
                "title": nearby.strip()[:240],
                "status": status,
                "evidence": {**citation, "verified": bool(citation.get("verified") and citation.get("quote") in str(extraction.get("source_text", citation.get("quote", ""))))},
                "as_of_date": as_of,
                "note": note,
                "agent": "Norns",
                "actionable": False,
            }
            key = (str(normalized or raw), date_type, record["title"])
            milestones[key] = record
    return sorted(milestones.values(), key=lambda x: (str(x.get("date", "")), x["date_type"], x["title"]))


def build_worst_case_projection(
    contract_id: str, extraction: dict[str, Any], milestones: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Summarize supported downside terms without inventing exposure totals."""
    quotes = [
        str((term.get("citation") or {}).get("quote", ""))
        for term in extraction.get("extracted_terms", [])
    ]
    financial_terms = []
    for term in extraction.get("extracted_terms", []):
        quote = str((term.get("citation") or {}).get("quote", ""))
        amounts = [m.group(0).strip() for m in _AMOUNT.finditer(quote)]
        rates = [m.group(0).strip() for m in _RATE.finditer(quote)]
        if amounts or rates or re.search(r"\b(penalty|interest|late fee|liquidated damages|service credit)\b", quote, re.I):
            financial_terms.append({
                "category": term.get("category"),
                "amounts_as_written": amounts,
                "rates_as_written": rates,
                "evidence": term.get("citation"),
                "calculation_status": "not_calculated_without_trigger_principal_period_and_payment_status",
            })
    return {
        "contract_id": contract_id,
        "milestones": milestones or [],
        "financial_terms": financial_terms,
        "total_exposure": None,
        "status": "source_grounded_candidates",
        "assumptions": [],
        "limitations": [
            "Relative deadlines are not converted to calendar dates without a verified trigger date.",
            "Financial amounts and rates are not summed or applied without the relevant trigger, principal, period, and payment status.",
            "No source evidence is not evidence that no obligation exists.",
        ],
    }


def project_at_date(extraction: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Recompute a contract's date classification for a simulated clock position."""
    return build_timeline(extraction, as_of)


def build_portfolio_timeline(workstream_analysis: dict[str, Any], portfolio_operations: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Build FR3's unified simulated timeline and conservative no-action exposure.

    The result is a planning projection, not a legal/accounting conclusion. Only
    source-stated dates, transaction statuses, amounts, and penalty triggers are
    used; unlinked or ambiguous records remain review items.
    """
    current = date.fromisoformat(as_of)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    ops_timeline = (portfolio_operations or {}).get("timeline", {})
    for item in ops_timeline.get("milestones", []):
        raw_date = str(item.get("date") or "")[:10]
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            parsed = None
        title = str(item.get("title") or "Contract milestone")
        date_type = str(item.get("date_type") or "source_date_unclassified")
        status = str(item.get("status") or "needs_review")
        action_deadline = bool(item.get("action_required_by_date") or date_type == "action_deadline")
        if parsed and action_deadline:
            status = "overdue" if parsed < current else "due_today" if parsed == current else "upcoming"
        elif parsed and not action_deadline:
            status = "past_reference" if parsed < current else "today_reference" if parsed == current else "future_reference"
        key = (str(item.get("contract_id") or "unknown"), raw_date, title)
        if key in seen:
            continue
        seen.add(key)
        rows.append({**item, "status": status, "action_required_by_date": action_deadline,
                     "days_from_as_of": (parsed-current).days if parsed else None,
                     "timeline_source": "contract_extraction",
                     "next_action": ("Escalate to the contract owner; verify notice/cure periods and required delivery method."
                                     if status == "overdue" and action_deadline else
                                     "Complete or confirm the obligation and retain evidence."
                                     if action_deadline else
                                     "Review as a contract milestone; do not treat it as overdue without an action trigger.")})

    reconciliation = (portfolio_operations or {}).get("financial_reconciliation", {})
    for item in reconciliation.get("payment_ledger_candidates", []):
        source_date = str(item.get("timestamp") or "")[:10]
        try:
            parsed = date.fromisoformat(source_date)
        except ValueError:
            parsed = None
        status_text = str(item.get("transaction_signal") or "unknown").casefold()
        summary = str(item.get("summary") or "Payment ledger entry")
        if any(word in status_text for word in ("paid", "settled", "completed", "cleared")):
            payment_status = "recorded_paid"
        elif any(word in status_text for word in ("unpaid", "pending", "outstanding", "overdue", "failed", "returned")):
            payment_status = "payment_status_requires_review"
        else:
            payment_status = "transaction_status_unconfirmed"
        key = (str(item.get("contract_id") or "unlinked"), source_date, summary)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "id": item.get("event_id"), "contract_id": item.get("contract_id"),
            "date": source_date or None, "title": summary, "date_type": "payment_record",
            "status": payment_status, "action_required_by_date": False,
            "days_from_as_of": (parsed-current).days if parsed else None,
            "timeline_source": item.get("event_source", "payment_ledger"),
            "amounts_found": item.get("amounts_found", []),
            "contract_match_status": item.get("contract_match_status"),
            "next_action": ("Match to invoice and bank/ledger evidence before marking paid."
                            if payment_status == "recorded_paid" else
                            "Reconcile invoice, ledger, credits, and contract; confirm whether payment is outstanding."),
            "evidence": {"summary": summary, "source": item.get("event_source"),
                         "timestamp": source_date or None},
        })
    rows.sort(key=lambda x: (str(x.get("date") or "9999-99-99"), str(x.get("contract_id") or ""), str(x.get("title") or "")))

    overdue = [x for x in rows if x.get("status") == "overdue" and x.get("action_required_by_date")]
    due_today = [x for x in rows if x.get("status") == "due_today" and x.get("action_required_by_date")]
    upcoming = [x for x in rows if x.get("status") == "upcoming" and x.get("action_required_by_date")]
    review_items = [x for x in rows if x.get("status") in {"payment_status_requires_review", "transaction_status_unconfirmed"}]
    scenarios = []
    known_total = 0.0
    known_count = 0
    unknown_penalties = []
    for stream in workstream_analysis.get("workstreams", []):
        if stream.get("id") == "portfolio-wide":
            continue
        contract_id = str(stream.get("primary_contract_id") or stream.get("id", "").replace("contract-", "") or "unknown")
        terms = stream.get("extracted_obligations", []) or []
        amounts = (stream.get("financial_exposure") or {}).get("amounts_found", []) or []
        for term in terms:
            citation = term.get("citation") or term.get("evidence") or {}
            quote = str(citation.get("quote") or "")
            category = str(term.get("category") or "")
            if not re.search(r"penalt|late fee|liquidated damages|default interest|interest on overdue|service credit", category + " " + quote, re.I):
                continue
            amount_matches = list(_AMOUNT.finditer(quote))
            fixed_amounts = []
            for match in amount_matches:
                raw = match.group(0)
                number = re.search(r"[\d,]+(?:\.\d{2})?", raw)
                if number:
                    try:
                        fixed_amounts.append(float(number.group(0).replace(",", "")))
                    except ValueError:
                        pass
            explicit_trigger = bool(re.search(r"overdue|late|failure to pay|fails to pay|after the due date|per day|per month|per annum|daily|monthly", quote, re.I))
            record = {"contract_id": contract_id, "term": category or "Penalty / interest clause",
                      "trigger_supported": explicit_trigger, "amounts_as_written": [m.group(0) for m in amount_matches],
                      "evidence": citation, "calculation_status": "needs_review",
                      "projected_amount": None, "note": "Confirm due invoice, trigger date, grace period, principal, and applicable period before treating as payable."}
            # Only fixed amounts with an explicit penalty context and a source-stated trigger
            # can contribute to the known floor; rates/principal are never guessed.
            if fixed_amounts and explicit_trigger and re.search(r"penalt|late fee|liquidated damages|service credit|charge", quote, re.I):
                record["projected_amount"] = max(fixed_amounts)
                record["calculation_status"] = "source_stated_fixed_amount_conditional"
                known_total += max(fixed_amounts)
                known_count += 1
            else:
                unknown_penalties.append(record)
            scenarios.append(record)
    projection = {
        "as_of_date": as_of, "scenario": "No action taken after the selected simulated date",
        "known_conditional_fixed_penalty_total": round(known_total, 2) if known_count else None,
        "known_conditional_items": known_count, "items": scenarios,
        "unknown_or_unquantified_items": len(unknown_penalties),
        "status": "partial_source_backed_projection" if known_count else "quantification_requires_verified_inputs",
        "limitations": [
            "Conditional amounts are not proof that a penalty is legally due or has been incurred.",
            "Percentage/rate-based charges are not calculated without a verified principal, trigger, grace period, and elapsed period.",
            "Unpaid status must be reconciled against invoice, bank, and credit evidence; contract-stated values are not summed as losses.",
        ],
    }
    return {
        "as_of_date": as_of,
        "items": rows,
        "counts": {"total": len(rows), "overdue": len(overdue), "due_today": len(due_today),
                   "upcoming_action_deadlines": len(upcoming), "payment_records_needing_review": len(review_items)},
        "worst_case_projection": projection,
        "clock": {"selected_date": as_of, "recomputed": True, "date_basis": "explicit source dates only"},
    }
