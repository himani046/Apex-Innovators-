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
                date_type = "possible_action_deadline"
            elif _MILESTONE_TERMS.search(nearby):
                date_type = "contract_milestone"
            else:
                date_type = "reference_date"
            record = {
                "id": f"{contract_id}:date:{term_index}:{start}",
                "contract_id": contract_id,
                "date": normalized or raw,
                "date_text": raw,
                "date_type": date_type,
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
