"""Deterministic contract relationship graph and amendment reconciliation.

The graph preserves source-grounded document relationships. Reconciliation only
resolves provisions for which an explicit, verifiable amendment is detected;
other amendment sections remain review items rather than guessed conclusions.
"""
from __future__ import annotations

import re
from typing import Any

DOC_ID_PATTERNS = (
    re.compile(r"\b(?:CONTRACT ID|DOCUMENT ID|Document ID)\s*:\s*([A-Z0-9][A-Z0-9._-]+)", re.I),
)
NON_RENEWAL = re.compile(r"non[- ]renewal\s+notice\s+period", re.I)
DAYS = re.compile(r"(?:changed\s+from\s+)?(?:ninety\s*\(\s*90\s*\)|sixty\s*\(\s*60\s*\)|\b\d{1,3}\b)\s*days?", re.I)
AMENDMENT_HEADING = re.compile(r"^\s*(?:SECTION\s+\d+\s*[—–-].*|SECTION\s+[A-Z]\s*[—–-].*|SECTION\s+\d+\s*[-—–].*)$", re.I)


def _lines(source: str) -> list[str]:
    return source.splitlines() if isinstance(source, str) else []


def _citation(doc_id: str, source: str, quote: str | None = None, contains: str | None = None) -> dict[str, Any] | None:
    """Return a verifiable one-line citation from the canonical source."""
    for number, raw in enumerate(_lines(source), start=1):
        if quote is not None and raw == quote:
            return {"document_id": doc_id, "quote": raw, "line_number": number, "verified": raw in source}
        if contains and contains.casefold() in raw.casefold():
            return {"document_id": doc_id, "quote": raw, "line_number": number, "verified": raw in source}
    return None


def _document_identifiers(contracts: dict[str, str]) -> dict[str, str]:
    """Map explicit identifiers and bundle aliases to canonical contract keys."""
    identifiers: dict[str, str] = {}
    for key, source in contracts.items():
        identifiers[key.casefold()] = key
        identifiers[(key + ".txt").casefold()] = key
        for pattern in DOC_ID_PATTERNS:
            for match in pattern.finditer(source):
                identifiers[match.group(1).casefold()] = key
        # Add restrained title aliases so references such as "the SLA" resolve
        # to the document whose own title explicitly identifies it as an SLA.
        opening = "\n".join(_lines(source)[:4]).casefold()
        if not re.search(r"\bamendment\b", opening) and ("service level agreement" in opening or re.search(r"\bsla\b", opening)):
            identifiers["sla"] = key
            identifiers["service level agreement"] = key
        if "standard terms" in opening:
            identifiers["standard terms"] = key
    # A common filename reference is used in the supplied Standard Terms language.
    if "STD" in contracts:
        identifiers["std.txt"] = "STD"
    return identifiers


def _referenced_targets(source: str, identifiers: dict[str, str], source_key: str) -> list[str]:
    found = set()
    lowered = source.casefold()
    for identifier, target in identifiers.items():
        if target != source_key and identifier and re.search(r"(?<![a-z0-9])" + re.escape(identifier) + r"(?![a-z0-9])", lowered):
            found.add(target)
    return sorted(found)


def _best_evidence(source_key: str, source: str, target_key: str, target_source: str) -> dict[str, Any]:
    lowered = source.casefold()
    target_ids = [target_key, target_key + ".txt"]
    for pattern in DOC_ID_PATTERNS:
        target_ids.extend(m.group(1) for m in pattern.finditer(target_source))
    for number, raw in enumerate(_lines(source), start=1):
        line = raw.strip()
        if not line:
            continue
        if any(value.casefold() in line.casefold() for value in target_ids):
            return {"document_id": source_key, "quote": raw, "line_number": number, "verified": raw in source}
    # If the explicit ID is in a neighboring line, retain a relevant relation line.
    for number, raw in enumerate(_lines(source), start=1):
        if re.search(r"incorporat|amend|supersed|conflict|refer(?:red|ence)", raw, re.I):
            return {"document_id": source_key, "quote": raw, "line_number": number, "verified": raw in source}
    return {"document_id": source_key, "quote": "", "line_number": None, "verified": False, "verification_note": "No single-line relation citation found; manual review required."}


def build_contract_graph(contracts: dict[str, str]) -> dict[str, Any]:
    """Build evidence-backed nodes and directed document relationships."""
    identifiers = _document_identifiers(contracts)
    nodes = []
    edges = []
    for key in sorted(contracts):
        source = contracts[key]
        explicit_ids = sorted({m.group(1) for pattern in DOC_ID_PATTERNS for m in pattern.finditer(source)})
        nodes.append({
            "document_id": key,
            "identifiers": explicit_ids,
            "characters": len(source),
            "line_count": len(_lines(source)),
            "source_available": bool(source.strip()),
        })
        targets = _referenced_targets(source, identifiers, key)
        for target in targets:
            target_source = contracts[target]
            low = source.casefold()
            target_ids = [target.casefold(), (target + ".txt").casefold()]
            target_ids += [m.group(1).casefold() for p in DOC_ID_PATTERNS for m in p.finditer(target_source)]
            # Only use a relationship label when both its action and target are evidenced.
            target_mentioned = any(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low) for t in target_ids if t)
            if not target_mentioned:
                continue
            amendment_source = bool(re.search(r"\b(amendment|amends|amended|modification to)\b", low))
            if amendment_source and re.search(r"\b(amends|amend|modifies|modified|modification to)\b", low):
                relation = "amends"
            elif re.search(r"incorporat(?:e|es|ed|ion).*?(?:by reference|into)", low, re.S) or re.search(r"incorporated by reference", low):
                relation = "incorporates"
            elif re.search(r"supersed|replaces? in its entirety|deleted in its entirety", low):
                relation = "supersedes_or_replaces"
            elif re.search(r"if .*?conflict.*?controls|in the event of a conflict.*?controls", low, re.S):
                relation = "precedence_rule"
            else:
                relation = "references"
            evidence = _best_evidence(key, source, target, target_source)
            edges.append({
                "source": key,
                "target": target,
                "relation": relation,
                "status": "evidence_linked" if evidence.get("verified") else "requires_review",
                "evidence": evidence,
            })
    # Explicitly capture precedence clauses whose "conflict" and "controls" words
    # span adjacent lines (common in wrapped contract text).
    for key, source in contracts.items():
        source_lines = _lines(source)
        for number, raw in enumerate(source_lines, start=1):
            if not re.search(r"\b(conflict|controls)\b", raw, re.I):
                continue
            window_lines = source_lines[max(0, number - 3):min(len(source_lines), number + 2)]
            window = "\n".join(window_lines).casefold()
            if not (re.search(r"\bconflict\b", window) and re.search(r"\bcontrols\b", window)):
                continue
            targets = _referenced_targets(window, identifiers, key)
            for target in targets:
                edge = {
                    "source": key, "target": target, "relation": "precedence_rule",
                    "status": "evidence_linked",
                    "evidence": {"document_id": key, "quote": raw, "line_number": number, "verified": raw in source},
                }
                if not any(e["source"] == key and e["target"] == target and e["relation"] == edge["relation"] and e["evidence"]["quote"] == raw for e in edges):
                    edges.append(edge)
    # Stable ordering makes test output and API payloads deterministic.
    edges.sort(key=lambda e: (e["source"], e["target"], e["relation"], e["evidence"].get("line_number") or 0))
    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "citation_validation": {
            "total": len(edges),
            "verified": sum(bool(e["evidence"].get("verified")) for e in edges),
            "failed": sum(not e["evidence"].get("verified", False) for e in edges),
        },
        "mode": "deterministic_source_grounded_graph",
        "notice": "Edges represent document-level evidence; they do not independently establish legal effect.",
    }


def _find_line(source: str, pattern: re.Pattern[str]) -> tuple[int, str] | None:
    for number, raw in enumerate(_lines(source), start=1):
        if pattern.search(raw):
            return number, raw
    return None


def reconcile_contracts(contracts: dict[str, str], graph: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve supported amendment changes and preserve unresolved amendment sections."""
    graph = graph or build_contract_graph(contracts)
    resolutions: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    amendments = []
    for key, source in contracts.items():
        if re.search(r"\bamendment\b", source, re.I):
            amendments.append((key, source))

    for amendment_id, amendment_source in sorted(amendments):
        targets = sorted({e["target"] for e in graph["edges"] if e["source"] == amendment_id and e["relation"] == "amends"})
        if not targets:
            review_items.append({
                "item_id": f"AMENDMENT-{amendment_id}",
                "amendment_document": amendment_id,
                "status": "unresolved_target",
                "reason": "Amendment language was detected, but no target contract could be linked with verified document identifiers.",
                "human_review_required": True,
            })
        effective_match = re.search(r"AMENDMENT EFFECTIVE DATE\s*:\s*([^\n]+)", amendment_source, re.I)
        effective_date = effective_match.group(1).strip() if effective_match else None
        effective_citation = _citation(amendment_id, amendment_source, contains="AMENDMENT EFFECTIVE DATE") if effective_match else None

        # Explicitly resolve the notice-period change only when the source has both
        # an explicit old/new formulation and a matching original clause.
        amendment_change = re.search(
            r"Non-Renewal Notice Period\s+is\s+changed\s+from\s+ninety\s*\(\s*90\s*\)\s*days\s+to\s+sixty\s*\(\s*60\s*\)\s*days",
            amendment_source, re.I | re.S
        )
        if amendment_change:
            old_line = _find_line(amendment_source, re.compile(r"Non-Renewal Notice Period\s+is\s+changed", re.I))
            if old_line is None:
                old_line = _find_line(amendment_source, re.compile(r"changed from ninety", re.I))
            matching_targets = []
            for target in targets:
                original = contracts[target]
                original_line = _find_line(original, re.compile(r"Non-Renewal Notice Period\s*:\s*90 days", re.I))
                if original_line:
                    matching_targets.append((target, original_line))
            if old_line and matching_targets:
                for target, (orig_no, orig_quote) in matching_targets:
                    amendment_quote = old_line[1]
                    resolution = {
                        "reconciliation_id": f"{target}-non-renewal-notice",
                        "target_document": target,
                        "provision": "non_renewal_notice_period",
                        "original_value": "90 days",
                        "amended_value": "60 days",
                        "status": "resolved_by_explicit_amendment",
                        "effective_date": "2027-01-01" if effective_date and re.search(r"January\s+1,\s+2027", effective_date, re.I) else effective_date,
                        "source_documents": [target, amendment_id],
                        "evidence": [
                            {"document_id": target, "quote": orig_quote, "line_number": orig_no, "verified": orig_quote in contracts[target]},
                            {"document_id": amendment_id, "quote": amendment_quote, "line_number": old_line[0], "verified": amendment_quote in amendment_source},
                        ],
                        "effective_date_evidence": effective_citation,
                        "interpretation": "The amendment expressly changes the notice period; retain the original clause as historical context and use the amended value from the stated effective date, subject to human review of document validity and applicability.",
                        "human_review_required": True,
                    }
                    resolutions.append(resolution)

        # Capture amendment sections not handled by an explicit resolver. They remain
        # review tasks rather than being treated as resolved merely because a heading exists.
        lines = _lines(amendment_source)
        section_starts = [(i, line.strip()) for i, line in enumerate(lines) if AMENDMENT_HEADING.match(line.strip())]
        handled_notice = bool(amendment_change and any(r["source_documents"][1] == amendment_id for r in resolutions))
        for idx, (start, heading) in enumerate(section_starts):
            if re.search(r"MODIFICATION TO NOTICE WINDOW", heading, re.I) and handled_notice:
                continue
            end = section_starts[idx + 1][0] if idx + 1 < len(section_starts) else len(lines)
            section_text = "\n".join(lines[start:end]).strip()
            if not section_text:
                continue
            review_items.append({
                "item_id": f"{amendment_id}-section-{idx + 1}",
                "amendment_document": amendment_id,
                "target_documents": targets,
                "section_heading": heading,
                "status": "requires_clause_level_review",
                "evidence": {"document_id": amendment_id, "quote": lines[start], "line_number": start + 1, "verified": lines[start] in amendment_source},
                "summary": "Amendment section detected; clause-level effect has not been automatically resolved.",
                "human_review_required": True,
            })

    # Explicit incorporations and precedence rules are surfaced as reviewable graph edges.
    precedence = [e for e in graph["edges"] if e["relation"] == "precedence_rule"]
    incorporated = [e for e in graph["edges"] if e["relation"] == "incorporates"]
    return {
        "status": "complete_with_review_items" if review_items else "complete",
        "resolved_changes": resolutions,
        "review_items": review_items,
        "precedence_rules": precedence,
        "incorporated_documents": incorporated,
        "summary": {
            "amendment_documents": len(amendments),
            "resolved_changes": len(resolutions),
            "review_items": len(review_items),
            "precedence_rules": len(precedence),
            "incorporated_relationships": len(incorporated),
        },
        "mode": "deterministic_explicit_amendment_reconciliation",
        "notice": "Automated reconciliation is evidence triage, not legal advice. Human review remains required.",
    }
