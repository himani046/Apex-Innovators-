"""Portfolio-wide, source-grounded contract triage for Thor.

This first pass intentionally extracts relevant source lines rather than claiming
that keyword matches are final legal interpretations. Every candidate is linked
to an exact quote for later agent review.
"""
import re

TOPIC_PATTERNS = {
    "dates_and_term": re.compile(r"\b(effective date|commencement|start date|end date|expiration|expire|term|subscription period)\b", re.I),
    "renewal": re.compile(r"\b(renew|renewal|auto.?renew|non.?renewal)\b", re.I),
    "notice": re.compile(r"\b(notice|notify|notification|within \d+ (?:hour|day)|days' notice)\b", re.I),
    "fees_and_payment": re.compile(r"\b(fee|price|payment|invoice|billing|cost|\$\s?\d|USD\s?\d)\b", re.I),
    "interest_and_late_payment": re.compile(r"\b(interest|late payment|overdue|past due)\b", re.I),
    "service_commitments": re.compile(r"\b(SLA|service level|uptime|availability|response time|resolution time|service credit)\b", re.I),
    "incident_and_security": re.compile(r"\b(incident|disruption|outage|security|breach|cyber|vulnerabilit|data loss)\b", re.I),
    "liability_and_indemnity": re.compile(r"\b(liabilit|liability cap|limitation of liability|indemnif|indemnity|damages)\b", re.I),
    "termination": re.compile(r"\b(terminat|suspend|cancellation|cancel)\b", re.I),
    "confidentiality_and_data": re.compile(r"\b(confidential|personal data|data processing|privacy|retain|delet(?:e|ion))\b", re.I),
    "incorporated_documents": re.compile(r"\b(incorporat|attached|attachment|exhibit|schedule|standard terms|STD|subject to)\b", re.I),
}

HEADING_PATTERN = re.compile(r"^\s*(?:(?:section|article|clause)\s+[A-Z0-9.IVX-]+|[A-Z][A-Z0-9 .,/()&'-]{3,})\s*[:—–.-]?\s*$", re.I)


def extract_contract_candidates(contract_id: str, source: str, max_terms: int = 40) -> dict:
    """Extract source lines that may contain important terms, with exact quotes."""
    if not isinstance(source, str) or not source.strip():
        return {
            "contract_id": contract_id,
            "summary": "No readable source text was available.",
            "extracted_terms": [],
            "ambiguities": ["Document is empty or unreadable; no terms were extracted."],
            "agent": "Thor",
            "mode": "deterministic_source_triage",
        }

    terms = []
    ambiguities = []
    current_heading = "Unlabeled clause"
    seen = set()
    lines = source.splitlines()

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if HEADING_PATTERN.match(line) and len(line) < 160:
            current_heading = line
        matched_topics = [category for category, pattern in TOPIC_PATTERNS.items() if pattern.search(line)]
        if not matched_topics:
            continue

        # A line can support more than one topic, but do not emit duplicate quotes.
        quote_key = re.sub(r"\s+", " ", line).casefold()
        if quote_key in seen:
            continue
        seen.add(quote_key)

        category = matched_topics[0]
        terms.append({
            "category": category,
            "value": line,
            "confidence": 0.65,
            "citation": {
                "document_id": contract_id,
                "clause_reference": current_heading,
                "quote": raw_line,
                "line_number": line_number,
                "verified": raw_line in source,
                "verification_note": "Exact source line matched." if raw_line in source else "Exact source line could not be verified.",
            },
            "matched_topics": matched_topics,
            "review_required": True,
        })
        if len(terms) >= max_terms:
            ambiguities.append(f"Extraction capped at {max_terms} candidate lines; later matches may remain.")
            break

    if not terms:
        ambiguities.append("No lines matched the current topic patterns; this does not mean the contract has no obligations.")
    ambiguities.append("Keyword-based candidates are not final legal interpretations and require cross-document review.")

    return {
        "contract_id": contract_id,
        "summary": f"Thor found {len(terms)} potentially relevant source lines in {contract_id}.",
        "extracted_terms": terms,
        "ambiguities": ambiguities,
        "agent": "Thor",
        "mode": "deterministic_source_triage",
    }


def extract_portfolio_candidates(contracts: dict[str, str]) -> dict:
    """Run the same bounded evidence-first extraction across every loaded contract."""
    results = {}
    for contract_id in sorted(contracts):
        results[contract_id] = extract_contract_candidates(contract_id, contracts[contract_id])
    return {
        "documents_processed": len(results),
        "contract_ids": list(results),
        "contracts": results,
        "citation_validation": {
            "total": sum(len(item["extracted_terms"]) for item in results.values()),
            "verified": sum(
                1 for item in results.values() for term in item["extracted_terms"]
                if term.get("citation", {}).get("verified")
            ),
            "failed": sum(
                1 for item in results.values() for term in item["extracted_terms"]
                if not term.get("citation", {}).get("verified")
            ),
        },
        "agent": "Thor",
        "mode": "deterministic_source_triage",
        "notice": "These are evidence-linked candidate lines, not resolved cross-contract conclusions.",
    }
