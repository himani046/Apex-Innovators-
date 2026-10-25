"""Amendment lineage and precedence analysis for multi-contract portfolios.

The resolver creates source-grounded relationship candidates. It never declares a
legal conflict resolved: amendment validity, effective dates, party identity, scope,
and incorporated documents require human confirmation.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "notice": re.compile(r"\b(notice|notify|notification|non-renewal|nonrenewal)\b", re.I),
    "payment": re.compile(r"\b(payment|invoice|billing|payable|remittance|late fee|interest|net\s+\d+)\b", re.I),
    "renewal": re.compile(r"\b(renewal|auto(?:matic)?[- ]renew|renew|non-renewal|extension of term)\b", re.I),
    "termination": re.compile(r"\b(terminate|termination|cure period|default)\b", re.I),
    "liability": re.compile(r"\b(liability|indemnif\w*|damages|liability cap)\b", re.I),
    "service_level": re.compile(r"\b(service level|\bSLA\b|uptime|availability|response time|resolution time)\b", re.I),
    "exclusivity": re.compile(r"\b(exclusive|exclusivity|non-exclusive|nonexclusive)\b", re.I),
    "confidentiality": re.compile(r"\b(confidential(?:ity)?|non-disclosure|trade secret)\b", re.I),
    "data_security": re.compile(r"\b(data breach|security incident|personal data|data protection|cybersecurity)\b", re.I),
    "delivery": re.compile(r"\b(delivery|deliver|shipment|milestone|performance standard)\b", re.I),
}
AMENDMENT_MARKER = re.compile(
    r"\b(amendment|amendment no\.?\s*\d*|amended and restated|addendum|supplemental agreement|variation agreement)\b",
    re.I,
)
PRECEDENCE_MARKER = re.compile(
    r"\b(notwithstanding|order of precedence|in the event of (?:any )?conflict|"
    r"to the extent of (?:any )?conflict|shall prevail|will prevail|supersedes?|controls? over)\b",
    re.I,
)
INCORPORATION_MARKER = re.compile(
    r"\b(incorporated by reference|incorporate[sd]? by reference|attached hereto|"
    r"master services agreement|statement of work|order form|schedule|exhibit|appendix)\b",
    re.I,
)
DATE_MARKER = re.compile(
    r"\b(?:effective(?:\s+as\s+of)?|dated|entered into on|executed on)\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
GENERIC_WORDS = {
    "agreement", "amendment", "addendum", "contract", "the", "this", "that",
    "shall", "will", "may", "must", "party", "parties", "section", "article",
    "effective", "dated", "terms", "conditions", "and", "or", "of", "to", "in",
}


def _explicit_ids(text: str, known_ids: list[str], exclude: str | None = None) -> list[str]:
    hits = []
    for contract_id in known_ids:
        if contract_id == exclude:
            continue
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(contract_id) + r"(?![A-Za-z0-9])", text, re.I):
            hits.append(contract_id)
    return sorted(set(hits))


def _topics(text: str) -> list[str]:
    return [name for name, pattern in TOPIC_PATTERNS.items() if pattern.search(text)]


def _date_candidates(text: str) -> list[dict[str, str]]:
    values = []
    for match in DATE_MARKER.finditer(text):
        raw = re.sub(r"\s+", " ", match.group("date")).strip(" ,")
        iso = None
        try:
            iso = date.fromisoformat(raw).isoformat()
        except ValueError:
            try:
                from datetime import datetime
                iso = datetime.strptime(raw.replace(",", ""), "%B %d %Y").date().isoformat()
            except ValueError:
                pass
        values.append({"raw": raw, "normalized_date": iso or "", "label": match.group(0).strip()})
        if len(values) >= 10:
            break
    return values


def _citation(contract_id: str, line_number: int, quote: str, source: str) -> dict[str, Any]:
    verified = bool(quote and quote in source)
    return {
        "document_id": contract_id, "line_number": line_number,
        "clause_reference": f"line {line_number}", "quote": quote,
        "verified": verified,
        "verification_note": "Exact line matched supplied source." if verified else "Quote did not match source.",
    }


def _precedence_direction(line: str, current_id: str, known_ids: list[str]) -> tuple[str, list[str]]:
    """Infer only explicit document-name direction from a precedence sentence."""
    referenced = _explicit_ids(line, known_ids, exclude=current_id)
    if not referenced:
        return "direction_unresolved", []
    lowered = line.casefold()
    current_wins = bool(re.search(r"\b(this (?:agreement|amendment|addendum)|amendment)\b.{0,100}\b(shall|will) prevail\b", lowered))
    referenced_wins = bool(re.search(r"\b" + re.escape(referenced[0]).casefold() + r"\b.{0,100}\b(shall|will) prevail\b", lowered))
    if current_wins:
        return "current_document_precedence_candidate", referenced
    if referenced_wins:
        return "referenced_document_precedence_candidate", referenced
    if re.search(r"\b(notwithstanding|supersedes?|controls? over)\b", lowered):
        # Direction depends on grammar and the complete clause; do not guess.
        return "precedence_direction_requires_review", referenced
    return "direction_unresolved", referenced


def analyze_amendment_lineage(contracts: dict[str, str],
                              candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Extract amendment links, precedence clauses, effective-date candidates and missing references."""
    known_ids = sorted(contracts)
    document_signals: dict[str, dict[str, Any]] = {}
    lineage_edges: list[dict[str, Any]] = []
    precedence_clauses: list[dict[str, Any]] = []
    incorporated_references: list[dict[str, Any]] = []
    missing_documents: list[dict[str, Any]] = []

    for contract_id, source in sorted(contracts.items()):
        header = "\n".join(source.splitlines()[:40])
        is_amendment = bool(AMENDMENT_MARKER.search(header))
        explicit_targets = _explicit_ids(header, known_ids, exclude=contract_id) if is_amendment else []
        date_candidates = _date_candidates(header)
        document_signals[contract_id] = {
            "document_id": contract_id,
            "document_type_candidate": "amendment_or_addendum" if is_amendment else "agreement_or_document_unclassified",
            "amendment_marker_found": is_amendment,
            "explicit_target_contract_ids": explicit_targets,
            "effective_date_candidates": date_candidates,
            "source_verified": True,
            "legal_effect_confirmed": False,
        }
        if is_amendment:
            if explicit_targets:
                for target in explicit_targets:
                    edge = {
                        "id": f"amendment-link:{contract_id}:{target}",
                        "source": contract_id, "target": target,
                        "relation": "explicit_amendment_reference_candidate",
                        "status": "source_linked_requires_effective_version_review",
                        "evidence": _citation(contract_id, 1, header.splitlines()[0].strip(), source) if header.splitlines() else {},
                        "explicit_reference_found": True,
                        "amendment_validity_confirmed": False,
                    }
                    # Prefer the exact line containing the target reference.
                    for line_number, raw in enumerate(source.splitlines(), 1):
                        if re.search(r"\b(amendment|addendum|amends|amended|supplements?)\b", raw, re.I) and re.search(
                            r"(?<![A-Za-z0-9])" + re.escape(target) + r"(?![A-Za-z0-9])", raw, re.I
                        ):
                            edge["evidence"] = _citation(contract_id, line_number, raw.strip(), source)
                            break
                    lineage_edges.append(edge)
            else:
                missing_documents.append({
                    "document_id": contract_id,
                    "type": "amendment_target_not_identified",
                    "status": "manual_link_required",
                    "reason": "Amendment/addendum wording is present, but no other supplied contract ID is explicitly named in the header.",
                    "human_review_required": True,
                })

        for line_number, raw in enumerate(source.splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            if PRECEDENCE_MARKER.search(line):
                targets = _explicit_ids(line, known_ids, exclude=contract_id)
                direction, referenced = _precedence_direction(line, contract_id, known_ids)
                precedence_clauses.append({
                    "id": f"precedence:{contract_id}:{line_number}",
                    "document_id": contract_id, "line_number": line_number,
                    "topics": _topics(line), "direction_candidate": direction,
                    "referenced_contract_ids": referenced,
                    "evidence": _citation(contract_id, line_number, line, source),
                    "status": "precedence_clause_candidate_requires_human_review",
                    "precedence_legally_resolved": False,
                })
            if INCORPORATION_MARKER.search(line):
                targets = _explicit_ids(line, known_ids, exclude=contract_id)
                label_match = re.search(
                    r"\b(master services agreement|statement of work|order form|schedule|exhibit|appendix|"
                    r"incorporated by reference|attached hereto)\b[^.;\n]{0,120}", line, re.I
                )
                label = label_match.group(0).strip() if label_match else line
                incorporated_references.append({
                    "id": f"incorporated:{contract_id}:{line_number}",
                    "document_id": contract_id, "line_number": line_number,
                    "reference_label": label, "explicit_target_contract_ids": targets,
                    "evidence": _citation(contract_id, line_number, line, source),
                    "status": "incorporated_term_reference_requires_verification",
                    "source_document_supplied": bool(targets),
                    "human_review_required": True,
                })
                if not targets:
                    missing_documents.append({
                        "document_id": contract_id, "line_number": line_number,
                        "type": "incorporated_document_not_identified",
                        "reference_label": label,
                        "status": "request_missing_source",
                        "reason": "The source refers to an exhibit, schedule, order form, statement of work, or incorporated terms that cannot be uniquely linked to another supplied document.",
                        "human_review_required": True,
                    })

    candidate_results = []
    for candidate in candidates or []:
        ids = [str(cid) for cid in candidate.get("contract_ids", []) if str(cid) in contracts]
        if len(ids) != 2:
            continue
        topic = str(candidate.get("topic", ""))
        related_edges = [edge for edge in lineage_edges if edge["source"] in ids and edge["target"] in ids]
        related_precedence = [
            clause for clause in precedence_clauses
            if clause["document_id"] in ids and (
                not clause.get("topics") or topic in clause.get("topics", [])
                or set(clause.get("referenced_contract_ids", [])) & set(ids)
            )
        ]
        related_incorporation = [
            item for item in incorporated_references
            if item["document_id"] in ids and (
                not item.get("explicit_target_contract_ids")
                or set(item.get("explicit_target_contract_ids", [])) & set(ids)
            )
        ]
        amendment_topics = {
            cid: _topics(contracts[cid]) for cid in ids
            if document_signals[cid]["document_type_candidate"] == "amendment_or_addendum"
        }
        touches_topic = any(topic in values for values in amendment_topics.values())
        if related_edges or related_precedence:
            status = "precedence_or_amendment_context_found_requires_human_review"
        elif related_incorporation:
            status = "incorporated_terms_may_change_comparison"
        elif any(document_signals[cid]["amendment_marker_found"] for cid in ids):
            status = "possible_amendment_context_target_unresolved"
        else:
            status = "no_explicit_precedence_resolution_found"
        candidate_results.append({
            "candidate_id": candidate.get("id"),
            "contract_ids": ids, "topic": topic,
            "status": status,
            "amendment_documents_in_pair": [
                cid for cid in ids if document_signals[cid]["amendment_marker_found"]
            ],
            "amendment_mentions_candidate_topic": touches_topic,
            "lineage_edges": related_edges,
            "precedence_clauses": related_precedence,
            "incorporated_references": related_incorporation,
            "effective_date_candidates": {
                cid: document_signals[cid]["effective_date_candidates"] for cid in ids
            },
            "questions_to_resolve": [
                "Verify amendment execution, validity, effective date, and the version of the base agreement it modifies.",
                "Confirm whether the amendment changes this exact topic and whether its scope covers the same parties, services, territory, transaction, and period.",
                "Read the full precedence clause and any exceptions; a keyword or explicit reference does not establish which text legally controls.",
                "Obtain any missing schedules, exhibits, order forms, statements of work, or incorporated terms.",
            ],
            "controlling_document_candidate": None,
            "legal_conflict_resolved": False,
            "human_review_required": True,
        })

    return {
        "mode": "deterministic_amendment_lineage_and_precedence_triage",
        "status": "complete_with_review_items" if candidate_results or lineage_edges or missing_documents else "no_explicit_amendment_signals",
        "document_signals": document_signals,
        "lineage_edges": lineage_edges,
        "precedence_clauses": precedence_clauses,
        "incorporated_references": incorporated_references,
        "missing_document_requests": missing_documents,
        "candidate_reviews": candidate_results,
        "summary": {
            "documents_scanned": len(contracts),
            "amendment_documents": sum(v["amendment_marker_found"] for v in document_signals.values()),
            "explicit_amendment_links": len(lineage_edges),
            "precedence_clauses": len(precedence_clauses),
            "incorporated_references": len(incorporated_references),
            "missing_document_requests": len(missing_documents),
            "candidates_with_precedence_context": sum(
                bool(item["lineage_edges"] or item["precedence_clauses"]) for item in candidate_results
            ),
            "legal_conflicts_resolved": 0,
        },
        "notice": "Source-grounded amendment and precedence candidates only; no legal conflict or controlling version is automatically determined.",
    }
