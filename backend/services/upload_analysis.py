"""Generic evidence-first extraction for user-uploaded contracts."""
import re
from typing import Any

RULES = [
    ("payment", r"\b(fee|payment|invoice|price|cost|interest|usd|\$|payable|payment period)\b"),
    ("term_and_renewal", r"\b(term|renew|renewal|effective date|subscription period|expiration|expiry)\b"),
    ("notice_and_communications", r"\b(notice|notify|notification|written notice|business days|calendar days)\b"),
    ("liability_and_indemnity", r"\b(liability|liable|indemnif|limitation of liability|damages|cap amount)\b"),
    ("service_levels_and_incidents", r"\b(sla|service level|outage|disruption|incident|response time|resolution time)\b"),
    ("termination", r"\b(terminat|suspend|cure period|breach|default)\b"),
    ("confidentiality_and_data", r"\b(confidential|personal data|security|privacy|data protection)\b"),
    ("governing_law_and_disputes", r"\b(governing law|jurisdiction|arbitration|dispute|venue)\b"),
]

def extract_document_terms(text: str, document_id: str) -> dict[str, Any]:
    """Return source-grounded excerpts only; do not invent a legal interpretation."""
    lines = text.splitlines()
    records = []
    current_heading = "Unlabelled section"
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if len(line) < 120 and (re.match(r"^(section|article|[0-9]+(?:\.[0-9]+)*|[A-Z]\.)\b", line, re.I) or line.isupper()):
            current_heading = line[:100]
        # Split on sentence boundaries while keeping source snippets verbatim.
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9$])", line):
            quote = part.strip()
            if len(quote) < 18:
                continue
            matches = [name for name, pattern in RULES if re.search(pattern, quote, re.I)]
            if not matches:
                continue
            records.append({
                "category": matches[0],
                "value": "Source excerpt requiring review",
                "confidence": 0.65,
                "citation": {
                    "document_id": document_id,
                    "clause_reference": current_heading,
                    "quote": quote,
                    "verified": quote in text,
                    "verification_note": f"Exact source excerpt; line {line_no}. Classification is heuristic, not a legal conclusion.",
                },
            })
    # Stable de-duplication avoids repeating the same clause excerpt.
    unique = []
    seen = set()
    for record in records:
        quote = record["citation"]["quote"]
        if quote not in seen:
            unique.append(record)
            seen.add(quote)
    return {
        "contract_id": document_id,
        "summary": "Generic upload scan completed. Returned items are source excerpts classified by keywords, not legal conclusions.",
        "extracted_terms": unique[:80],
        "ambiguities": [
            "This upload scan is not cross-referenced against other contracts, amendments, event logs, or payment records.",
            "Keyword classification can miss important provisions and can flag text that is not legally operative. Human review is required.",
        ],
        "agent": "Thor",
        "mode": "deterministic_upload_scan",
    }
