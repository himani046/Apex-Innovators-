"""Source-grounded contract quick-look profiles for the Odin dashboard."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.claude_client import ask_claude
from backend.config import USE_CLAUDE


SYSTEM = """You are Odin's contract-profile extraction agent. Extract a concise but comprehensive quick-look profile from the supplied contract text.
Return ONLY valid JSON with this schema:
{
 "contract_id": string|null,
 "counterparty": string|null,
 "contract_type": string|null,
 "contact_person": string|null,
 "contact_email": string|null,
 "contact_phone": string|null,
 "effective_date": string|null,
 "start_date": string|null,
 "end_date": string|null,
 "term": string|null,
 "renewal_terms": string|null,
 "contract_value": string|null,
 "fee_schedule": string|null,
 "payment_terms": string|null,
 "revenue_generated": string|null,
 "revenue_recognized": string|null,
 "amount_invoiced": string|null,
 "amount_collected": string|null,
 "outstanding_balance": string|null,
 "termination_terms": string|null,
 "governing_law": string|null,
 "important_clauses": [{"title":string,"summary":string,"clause_reference":string|null,"quote":string}],
 "key_obligations": [{"party":string|null,"obligation":string,"deadline":string|null,"clause_reference":string|null,"quote":string}],
 "ambiguities": [string],
 "evidence_gaps": [string]
}
Every material fact must be directly supported by the source. Every important clause and obligation must contain an exact verbatim quote copied from the supplied text. Do not invent names, contacts, dates, money, or clause numbers. Use null when not found.
Distinguish total/nominal contract value from revenue actually earned, recognized, invoiced, collected, or outstanding. Do not calculate revenue from contract value. If actual financial performance is not in the contract source, set the financial performance fields to null and add an evidence gap. If a recurring fee and term are explicit, contract_value may state a transparent derived calculation with its assumptions. Do not treat support response targets as resolution guarantees unless the text says so.
Limit important_clauses to the most decision-relevant 12 and key_obligations to 12. Keep summaries concise."""


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.casefold() in {"unknown", "n/a", "not found", "null", "none"}:
        return None
    return text[:1200]


def _section_for(source: str, quote: str) -> str:
    lines = source.splitlines()
    q = quote.strip()
    for idx, line in enumerate(lines):
        if q and q in line:
            for j in range(idx, max(-1, idx - 12), -1):
                candidate = lines[j].strip()
                if candidate and len(candidate) < 150 and (
                    re.match(r"^(section|article|clause)\s+[\w.-]+", candidate, re.I)
                    or re.match(r"^\d+(?:\.\d+)+\s+\S", candidate)
                    or (candidate == candidate.upper() and len(candidate) > 4 and any(c.isalpha() for c in candidate))
                ):
                    return candidate[:150]
            return "Source text (section heading not detected)"
    return "Source text (section heading not detected)"


def _fallback_profile(document_id: str, filename: str, source: str) -> dict[str, Any]:
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    full = "\n".join(lines)

    def first(pattern: str, flags=re.I) -> str | None:
        match = re.search(pattern, full, flags)
        return _clean(match.group(1)) if match else None

    def quote_for(pattern: str) -> str | None:
        for line in lines:
            if re.search(pattern, line, re.I):
                return line[:1000]
        return None

    email = first(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})")
    phone = first(r"(\+?\d[\d ()-]{7,}\d)")
    contact = first(r"(?:contact person|primary contact|account manager|notice contact|operations contact|attention|contact name)\s*[:\-]\s*([^,;|\n]+)")
    counterparty = first(r"(?:service provider|provider|vendor|supplier|customer|client|counterparty|contracting party)\s*[:\-]\s*([^,;|\n]+)")
    if not counterparty:
        counterparty = first(r"between\s+([A-Z][A-Za-z0-9 &.,'\-]{2,80}?)\s+and\s+", re.I)
    contract_id = first(r"(?:contract (?:id|no\.?|number)|agreement (?:id|no\.?|number))\s*[:#\-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})")
    effective = first(r"(?:effective date|effective as of|commencement date|starts on|start date)\s*[:\-]?\s*((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})")
    end_date = first(r"(?:initial subscription ends|expiration date|expires on|end date|termination date|term ends|ending on)\s*[:\-]?\s*((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})")
    monthly = first(r"((?:USD\s*)?\$\s?[\d,]+(?:\.\d{2})?\s*(?:per month|/month|monthly))")
    if not monthly:
        monthly = first(r"(?:monthly fee|monthly subscription fee|subscription fee per month|monthly charge)\s*[:\-]?\s*((?:USD\s*)?\$\s?[\d,]+(?:\.\d{2})?)")
        if monthly:
            monthly = monthly + " per month"
    fee = monthly or first(r"((?:USD\s*)?\$\s?[\d,]+(?:\.\d{2})?[^\n]{0,45}(?:per month|monthly|per year|annually|one-time))")
    term = first(r"((?:initial )?(?:term|subscription period)\s*(?:is|of|:)?\s*\d+\s*(?:months?|years?))")
    term_months = re.search(r"(\d+)\s*months?", term or "", re.I)
    if not term_months:
        term_years = re.search(r"(\d+)\s*years?", term or "", re.I)
        if term_years:
            term_months_count = int(term_years.group(1)) * 12
        else:
            term_months_count = None
    else:
        term_months_count = int(term_months.group(1))
    monthly_amount = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", monthly or "", re.I)
    contract_value = None
    if monthly_amount and term_months_count:
        amount = float(monthly_amount.group(1).replace(",", ""))
        contract_value = f"Derived nominal initial-term value: USD {amount * term_months_count:,.2f} ({term_months_count} months × USD {amount:,.2f}/month; excludes taxes, credits, usage and changes)."
    renewal = first(r"((?:auto.?renew|renewal|renew automatically)[^\n.]{0,240})")
    payment = first(r"((?:payment terms|payment period|net\s*\d+|invoice[^\n]{0,120}|payment due[^\n]{0,120})[^\n]{0,180})")
    termination = first(r"((?:termination|terminate for convenience|terminate for cause)[^\n.]{0,220})")
    law = first(r"(?:governing law|governed by the laws of)\s*[:\-]?\s*([^.;\n]{2,100})")

    important = []
    patterns = [
        ("Term and renewal", r"effective date|initial term|subscription period|auto.?renew|renewal|non.?renewal"),
        ("Fees and payment", r"monthly fee|subscription fee|payment period|invoice|late interest|late fee|service credit"),
        ("Security and incident notice", r"security incident|incident notification|notify.{0,30}(?:hours|days)|confidentiality|encryption|subprocessor"),
        ("Liability and indemnity", r"liability cap|limitation of liability|indemnif|unlimited claims"),
        ("Termination and transition", r"termination|migration assistance|transition assistance"),
        ("Service levels", r"uptime|availability|response time|resolution time|service level"),
        ("Governing law", r"governing law|jurisdiction|courts of"),
        ("Data protection", r"personal data|data location|data processing|retention|deletion"),
    ]
    seen = set()
    for title, pattern in patterns:
        q = quote_for(pattern)
        if q and q.casefold() not in seen:
            important.append({"title": title, "summary": q[:280], "clause_reference": _section_for(source, q), "quote": q})
            seen.add(q.casefold())
    obligations = []
    for pattern in [r"must ", r"shall ", r"within \d+ (?:hours?|days?)", r"no later than", r"at least \d+ days", r"notify", r"provide ", r"maintain "]:
        q = quote_for(pattern)
        if q and q.casefold() not in seen and len(obligations) < 8:
            obligations.append({"party": None, "obligation": q[:280], "deadline": None, "clause_reference": _section_for(source, q), "quote": q})
            seen.add(q.casefold())
    gaps = []
    if not contact and not email:
        gaps.append("No clearly labeled contact person or email was identified in the contract text.")
    gaps.append("Actual revenue earned/recognized, invoiced, collected, and outstanding cannot be established from contract terms alone; reconcile invoice/payment/accounting records.")
    return {
        "document_id": document_id, "filename": filename, "extraction_mode": "deterministic_fallback",
        "contract_id": contract_id or document_id, "counterparty": counterparty, "contract_type": None,
        "contact_person": contact, "contact_email": email, "contact_phone": phone,
        "effective_date": effective, "start_date": effective, "end_date": end_date, "term": term,
        "renewal_terms": renewal, "contract_value": contract_value, "fee_schedule": fee,
        "payment_terms": payment, "revenue_generated": None, "revenue_recognized": None,
        "amount_invoiced": None, "amount_collected": None, "outstanding_balance": None,
        "termination_terms": termination, "governing_law": law, "important_clauses": important,
        "key_obligations": obligations, "ambiguities": [], "evidence_gaps": gaps,
        "evidence": [],
    }


def build_contract_profile(document_id: str, filename: str, source: str, use_claude: bool = True) -> dict[str, Any]:
    """Extract a profile, reject unsupported quotes, and retain a deterministic fallback."""
    profile = _fallback_profile(document_id, filename, source)
    if not (use_claude and USE_CLAUDE):
        return profile
    try:
        prompt = (
            "DOCUMENT ID: " + document_id + "\nFILENAME: " + filename
            + "\nSOURCE TEXT (citations must be exact substrings of this text):\n"
            + source[:100_000]
        )
        raw = ask_claude(SYSTEM, prompt, 2800)
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Claude did not return a JSON object")
        data = json.loads(raw[start:end + 1])
        merged = dict(profile)
        scalar_fields = [
            "contract_id", "counterparty", "contract_type", "contact_person", "contact_email", "contact_phone",
            "effective_date", "start_date", "end_date", "term", "renewal_terms", "contract_value", "fee_schedule",
            "payment_terms", "revenue_generated", "revenue_recognized", "amount_invoiced", "amount_collected",
            "outstanding_balance", "termination_terms", "governing_law",
        ]
        for field in scalar_fields:
            value = _clean(data.get(field))
            if value:
                merged[field] = value
        if not merged.get("revenue_generated") and not merged.get("revenue_recognized") and not merged.get("amount_invoiced") and not merged.get("amount_collected") and not merged.get("outstanding_balance"):
            merged["evidence_gaps"] = list(dict.fromkeys(merged.get("evidence_gaps", []) + [
                "No actual revenue or cash-performance evidence was established by the contract text."
            ]))
        for collection in ("important_clauses", "key_obligations"):
            accepted = []
            for item in data.get(collection, []) if isinstance(data.get(collection), list) else []:
                if not isinstance(item, dict):
                    continue
                quote = str(item.get("quote") or "").strip()
                if not quote or quote not in source:
                    continue
                if collection == "important_clauses":
                    accepted.append({
                        "title": _clean(item.get("title")) or "Important clause",
                        "summary": _clean(item.get("summary")) or quote[:280],
                        "clause_reference": _clean(item.get("clause_reference")) or _section_for(source, quote),
                        "quote": quote,
                    })
                else:
                    accepted.append({
                        "party": _clean(item.get("party")),
                        "obligation": _clean(item.get("obligation")) or quote[:280],
                        "deadline": _clean(item.get("deadline")),
                        "clause_reference": _clean(item.get("clause_reference")) or _section_for(source, quote),
                        "quote": quote,
                    })
                if len(accepted) >= 12:
                    break
            if accepted:
                merged[collection] = accepted
        merged["ambiguities"] = list(dict.fromkeys(
            [_clean(x) for x in data.get("ambiguities", []) if _clean(x)]
        ))[:20]
        merged["evidence_gaps"] = list(dict.fromkeys(
            merged.get("evidence_gaps", []) + [_clean(x) for x in data.get("evidence_gaps", []) if _clean(x)]
        ))[:20]
        merged["extraction_mode"] = "claude_with_quote_validation"
        # Evidence shown in the UI is limited to exact, source-present quotes.
        merged["evidence"] = [
            {"field": key, "value": merged.get(key), "quote": quote, "clause_reference": _section_for(source, quote)}
            for key, pattern in [
                ("effective_date", r"effective date|commencement date"),
                ("end_date", r"end date|expires|expiration|term ends|initial subscription ends"),
                ("fee_schedule", r"monthly fee|subscription fee|fees"),
                ("contact_person", r"contact person|primary contact|account manager|operations contact"),
            ]
            for quote in [_first_quote(source, pattern)]
            if quote
        ]
        return merged
    except Exception as exc:
        profile["extraction_mode"] = "deterministic_fallback_after_claude_error"
        profile["claude_error"] = str(exc)[:240]
        return profile


def _first_quote(source: str, pattern: str) -> str | None:
    for line in source.splitlines():
        if re.search(pattern, line, re.I):
            return line.strip()[:1000]
    return None
