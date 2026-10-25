"""Portfolio-wide, source-grounded contract triage for Thor.

Candidate lines retain exact source text, source line numbers, and section headings.
Heuristic category confidence is intentionally labeled uncalibrated. The generic
extractor reports truncation rather than presenting a capped scan as exhaustive.
"""
import re
from typing import Any

TOPIC_PATTERNS = {
    "dates_and_term": re.compile(r"\b(effective date|commencement|start date|end date|expiration|expire|term|subscription period|duration)\b", re.I),
    "renewal": re.compile(r"\b(renew|renewal|auto.?renew|non.?renewal)\b", re.I),
    "notice": re.compile(r"\b(notice|notify|notification|within \d+ (?:hour|day)|days' notice)\b", re.I),
    "fees_and_payment": re.compile(r"\b(fee|price|payment|invoice|billing|cost|\$\s?\d|USD\s?\d|payment schedule)\b", re.I),
    "interest_and_late_payment": re.compile(r"\b(interest|late payment|overdue|past due|late fee)\b", re.I),
    "service_commitments": re.compile(r"\b(SLA|service level|uptime|availability|response time|resolution time|service credit)\b", re.I),
    "incident_and_security": re.compile(r"\b(incident|disruption|outage|security|breach|cyber|vulnerabilit|data loss)\b", re.I),
    "liability_and_indemnity": re.compile(r"\b(liabilit|liability cap|limitation of liability|indemnif|indemnity|damages)\b", re.I),
    "termination": re.compile(r"\b(terminat|suspend|cancellation|cancel|cure period)\b", re.I),
    "confidentiality_and_data": re.compile(r"\b(confidential|personal data|data processing|privacy|retain|delet(?:e|ion))\b", re.I),
    "compliance": re.compile(r"\b(compliance|comply|regulat|applicable law|audit right|certification|jurisdiction|governing law|arbitration)\b", re.I),
    "obligations": re.compile(r"\b(shall|must|required to|is obligated to|undertakes to)\b", re.I),
    "incorporated_documents": re.compile(r"\b(incorporat|attached|attachment|exhibit|schedule|standard terms|STD|subject to|notwithstanding|except as provided)\b", re.I),
}

SECTION_HEADING_PATTERN = re.compile(
    r"^\s*(?:(?:section|article|clause)\s+[A-Z0-9.IVX-]+|\d+(?:\.\d+)*\s+\S+)", re.I
)


def _heading_at(lines: list[str], index: int) -> str:
    for pos in range(index, max(-1, index - 12), -1):
        candidate = lines[pos].strip()
        if not candidate or len(candidate) >= 180:
            continue
        if SECTION_HEADING_PATTERN.match(candidate) or (
            candidate == candidate.upper() and any(ch.isalpha() for ch in candidate) and len(candidate) >= 4
        ):
            return candidate
    return "Unlabeled clause"


def extract_contract_candidates(contract_id: str, source: str, max_terms: int = 200) -> dict[str, Any]:
    """Return quote-backed candidate lines and explicit completeness metadata."""
    if not isinstance(source, str) or not source.strip():
        return {
            "contract_id": contract_id, "summary": "No readable source text was available.",
            "extracted_terms": [], "ambiguities": ["Document is empty or unreadable; no terms were extracted."],
            "agent": "Thor", "mode": "deterministic_source_triage",
            "completeness": {"is_truncated": False, "source_lines": 0, "candidates_found": 0},
        }
    lines = source.splitlines()
    terms = []
    ambiguities = []
    seen = set()
    total_matches = 0
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        matched_topics = [category for category, pattern in TOPIC_PATTERNS.items() if pattern.search(line)]
        if not matched_topics:
            continue
        total_matches += 1
        quote_key = re.sub(r"\s+", " ", line).casefold()
        if quote_key in seen:
            continue
        seen.add(quote_key)
        term = {
            "id": f"{contract_id}:line:{line_number}",
            "category": matched_topics[0], "value": line, "confidence": 0.65,
            "confidence_type": "heuristic_uncalibrated",
            "matched_topics": matched_topics, "review_required": True,
            "citation": {
                "document_id": contract_id, "clause_reference": _heading_at(lines, line_number - 1),
                "quote": raw_line, "line_number": line_number,
                "verified": raw_line in source,
                "verification_note": "Exact source line matched." if raw_line in source else "Exact source line could not be verified.",
            },
        }
        terms.append(term)
    truncated = len(terms) > max_terms
    if truncated:
        terms = terms[:max_terms]
        ambiguities.append(f"Candidate output capped at {max_terms}; {total_matches - len(terms)} potential source-line matches were not returned.")
    if not terms:
        ambiguities.append("No lines matched the current topic patterns; this does not mean the contract has no obligations.")
    ambiguities.append("Keyword candidates are not final legal interpretations. Check surrounding text, defined terms, amendments and incorporated documents.")
    return {
        "contract_id": contract_id,
        "summary": f"Thor found {len(terms)} potentially relevant source lines in {contract_id}.",
        "extracted_terms": terms, "ambiguities": ambiguities,
        "agent": "Thor", "mode": "deterministic_source_triage",
        "completeness": {"is_truncated": truncated, "source_lines": len(lines),
                         "candidates_found": total_matches, "candidates_returned": len(terms)},
    }


def extract_portfolio_candidates(contracts: dict[str, str]) -> dict[str, Any]:
    results = {cid: extract_contract_candidates(cid, source) for cid, source in sorted(contracts.items())}
    total = sum(len(item["extracted_terms"]) for item in results.values())
    verified = sum(1 for item in results.values() for term in item["extracted_terms"] if term.get("citation", {}).get("verified"))
    failed = total - verified
    truncated_ids = [cid for cid, item in results.items() if item.get("completeness", {}).get("is_truncated")]
    return {
        "documents_processed": len(results), "contract_ids": list(results), "contracts": results,
        "citation_validation": {"total": total, "verified": verified, "failed": failed},
        "completeness": {"is_truncated_contracts": truncated_ids, "truncated": bool(truncated_ids)},
        "agent": "Thor", "mode": "deterministic_source_triage",
        "notice": "These are evidence-linked candidate lines, not resolved cross-contract conclusions.",
    }
