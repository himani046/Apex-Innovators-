"""Generic evidence-first extraction for user-uploaded contracts."""
import re
from typing import Any

RULES = [
    ("parties", r"\b(between the parties|customer:|client:|buyer:|supplier:|provider:|vendor:|landlord:|tenant:|party a|party b)\b"),
    ("duration_and_term", r"\b(term of (?:this )?agreement|initial term|for a period of|commences on|expires on|effective date|duration)\b"),
    ("renewal", r"\b(auto(?:matic)?[- ]renew|renewal|renew|non[- ]renewal|renewal date)\b"),
    ("payment_schedule", r"\b(fee|payment|invoice|price|cost|interest|usd|\$|payable|payment period|monthly|quarterly|annually|net \d+)\b"),
    ("obligations", r"\b(shall|must|required to|will provide|undertakes to|is obligated to)\b"),
    ("penalty_and_liquidated_damages", r"\b(penalty|liquidated damages|late fee|interest rate|service credit|damages)\b"),
    ("compliance_and_regulatory", r"\b(comply|compliance|regulation|regulatory|applicable law|audit right|certification|data protection)\b"),
    ("notice_and_communications", r"\b(notice|notify|notification|written notice|business days|calendar days)\b"),
    ("liability_and_indemnity", r"\b(liability|liable|indemnif|limitation of liability|damages|cap amount)\b"),
    ("service_levels_and_incidents", r"\b(sla|service level|outage|disruption|incident|response time|resolution time)\b"),
    ("termination", r"\b(terminat|suspend|cure period|breach|default)\b"),
    ("confidentiality_and_data", r"\b(confidential|personal data|security|privacy|data protection)\b"),
    ("governing_law_and_disputes", r"\b(governing law|jurisdiction|arbitration|dispute|venue)\b"),
]

def extract_document_terms(text: str, document_id: str, clause_reference: str | None = None) -> dict[str, Any]:
    """Return source-grounded excerpts, optionally restricted to one named section.

    A requested section that cannot be located returns no terms instead of silently
    falling back to a whole-document scan.
    """
    lines = text.splitlines()
    if clause_reference:
        needle = clause_reference.strip().casefold()
        heading_pattern = re.compile(r"^(?:section|article|[0-9]+(?:\\.[0-9]+)*|[A-Z]\\.)\\b", re.I)
        heading_indexes = [
            index for index, raw in enumerate(lines)
            if raw.strip() and len(raw.strip()) < 120
            and (heading_pattern.match(raw.strip()) or raw.strip().isupper())
        ]
        matched_index = None
        for index in heading_indexes:
            heading = lines[index].strip()
            if needle in heading.casefold():
                matched_index = index
                break
            requested_numbers = re.findall(r"\\d+(?:\\.\\d+)*", needle)
            heading_numbers = re.findall(r"\\d+(?:\\.\\d+)*", heading)
            if requested_numbers and heading_numbers and requested_numbers[0] == heading_numbers[0]:
                matched_index = index
                break
        if matched_index is None:
            return {
                "contract_id": document_id,
                "summary": "Requested clause or section was not located; no whole-document fallback was performed.",
                "extracted_terms": [],
                "ambiguities": [f"Requested clause reference '{clause_reference}' was not found as a section heading."],
                "missing_category_candidates": ["parties", "duration_and_term", "renewal", "payment_schedule",
                    "obligations", "penalty_and_liquidated_damages", "compliance_and_regulatory", "termination"],
                "agent": "Thor",
                "mode": "targeted_clause_scan",
                "target_clause_reference": clause_reference,
                "target_clause_found": False,
            }
        next_heading = next((index for index in heading_indexes if index > matched_index), len(lines))
        lines = lines[matched_index:next_heading]
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
                "value": quote,
                "confidence": 0.65,
                "confidence_basis": "heuristic_keyword_match_not_calibrated",
                "citation": {
                    "document_id": document_id,
                    "clause_reference": current_heading,
                    "line_number": line_no,
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
    source_lower = text.casefold()
    ambiguity_flags = [
        "This upload scan is not cross-referenced against other contracts, amendments, event logs, or payment records.",
        "Keyword classification can miss important provisions and can flag text that is not legally operative. Human review is required.",
    ]
    if re.search(r"\b(auto(?:matic)?[- ]renew|renewal)\b", source_lower) and re.search(r"\b(non[- ]renewal|does not renew|shall not renew)\b", source_lower):
        ambiguity_flags.append("Both renewal and non-renewal language occurs in the document; inspect scope, exceptions, and precedence rather than resolving automatically.")
    if re.search(r"\b(may terminate)\b", source_lower) and re.search(r"\b(may not terminate|shall not terminate)\b", source_lower):
        ambiguity_flags.append("Potentially conflicting termination language detected; section context and precedence require human review.")
    if re.search(r"\b(notwithstanding|subject to|except as provided)\b", source_lower):
        ambiguity_flags.append("Override or exception language detected; identify the provision it modifies before interpreting the obligation.")
    expected_categories = ["parties", "duration_and_term", "renewal", "payment_schedule", "obligations",
                           "penalty_and_liquidated_damages", "compliance_and_regulatory", "termination"]
    observed_categories = {term.get("category") for term in unique}
    missing_categories = [category for category in expected_categories if category not in observed_categories]
    return {
        "contract_id": document_id,
        "summary": "Generic upload scan completed. Returned items are source excerpts classified by keywords, not legal conclusions.",
        "extracted_terms": unique[:80],
        "ambiguities": ambiguity_flags,
        "missing_category_candidates": missing_categories,
        "agent": "Thor",
        "mode": "targeted_clause_scan" if clause_reference else "deterministic_upload_scan",
        "target_clause_reference": clause_reference,
        "target_clause_found": True if clause_reference else None,
    }
