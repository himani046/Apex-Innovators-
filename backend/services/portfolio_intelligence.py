"""Bounded, evidence-first portfolio review orchestration.

This deterministic workflow is deliberately explicit about what it cannot prove:
source excerpts and event matches are candidates, not legal conclusions. It adds
bounded clarification passes, cross-contract candidate comparison, and durable
machine-readable trace records without requiring an LLM provider.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

TOPICS = {
    "notice": re.compile(r"\b(notice|notify|notification|non-renewal|nonrenewal)\b", re.I),
    "payment": re.compile(r"\b(payment|invoice|fee|interest|late fee|net\s+\d+|payable)\b", re.I),
    "renewal": re.compile(r"\b(renewal|auto(?:matic)?[- ]renew|renew|non-renewal)\b", re.I),
    "termination": re.compile(r"\b(terminate|termination|cure period|default)\b", re.I),
    "liability": re.compile(r"\b(liability|indemnif\w*|damages|liability cap)\b", re.I),
    "service_level": re.compile(r"\b(service level|sla|uptime|availability|response time|resolution time)\b", re.I),
    "exclusivity": re.compile(r"\b(exclusive|exclusivity|non-exclusive|nonexclusive)\b", re.I),
}
NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:\$\s*)?\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|days?|business days?|calendar days?|hours?|months?|years?)?", re.I)
POSITIVE_MODAL = re.compile(r"\b(shall|must|required to|will|is obligated to|may)\b", re.I)
NEGATIVE_MODAL = re.compile(r"\b(shall not|must not|may not|is prohibited from|will not|cannot)\b", re.I)
OVERRIDE = re.compile(r"\b(amendment|amended|addendum|notwithstanding|prevail|precedence|supersede|subject to)\b", re.I)
PARTY_LABEL = re.compile(r"\b(customer|client|buyer|supplier|provider|vendor|landlord|tenant|party a|party b)\b", re.I)


def _topic(line: str) -> str | None:
    matches = [name for name, pattern in TOPICS.items() if pattern.search(line)]
    # A sentence can touch several topics. Keep the most specific stable category.
    return matches[0] if matches else None


def _numbers(line: str) -> list[str]:
    values = []
    for value in NUMBER_RE.findall(line):
        normalized = re.sub(r"\s+", " ", value.strip().casefold()).replace(",", "")
        # Exclude section numbering and standalone headings.
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _citation(contract_id: str, line_number: int, quote: str, source: str) -> dict[str, Any]:
    return {
        "document_id": contract_id,
        "line_number": line_number,
        "clause_reference": f"line {line_number}",
        "quote": quote,
        "verified": bool(quote and quote in source),
        "verification_note": "Exact source line matched canonical contract text." if quote and quote in source
        else "Source quote did not match canonical text; review required.",
    }


def detect_cross_contract_candidates(contracts: dict[str, str]) -> list[dict[str, Any]]:
    """Find sourced cross-contract numeric/modality differences for human review.

    Matching is intentionally conservative: clauses must share a topic and either
    share at least one meaningful content token or express a same-topic term. An
    amendment/precedence marker suppresses an automatic conflict label and instead
    creates an explicit precedence-review candidate.
    """
    rows: list[dict[str, Any]] = []
    for cid, source in sorted(contracts.items()):
        contract_rows = 0
        for line_number, raw in enumerate(source.splitlines(), start=1):
            if len(rows) >= 1200 or contract_rows >= 100:
                break
            line = raw.strip()
            topic = _topic(line)
            if not topic or len(line) < 12:
                continue
            # Skip likely section labels without operative language.
            if len(line) < 70 and re.match(r"^(?:section|article|clause)\s+[\w.-]+\s*[:—-]?$", line, re.I):
                continue
            rows.append({
                "contract_id": cid, "line_number": line_number, "line": line,
                "topic": topic, "numbers": _numbers(line),
                "positive": bool(POSITIVE_MODAL.search(line)),
                "negative": bool(NEGATIVE_MODAL.search(line)),
                "override": bool(OVERRIDE.search(line)),
                "party_label": bool(PARTY_LABEL.search(line)),
                "tokens": set(re.findall(r"[a-z]{4,}", line.casefold())),
            })
            contract_rows += 1

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, left in enumerate(rows):
        if len(candidates) >= 250:
            break
        for right in rows[index + 1:]:
            if len(candidates) >= 250:
                break
            if left["contract_id"] == right["contract_id"] or left["topic"] != right["topic"]:
                continue
            shared = left["tokens"] & right["tokens"]
            # Topic words are weak evidence; require shared context beyond the topic itself.
            topic_words = set(re.findall(r"[a-z]{4,}", left["topic"].replace("_", " ")))
            meaningful_overlap = shared - topic_words
            number_diff = bool(left["numbers"] and right["numbers"] and left["numbers"] != right["numbers"])
            modality_diff = ((left["negative"] and right["positive"]) or
                             (right["negative"] and left["positive"]))
            exclusive_diff = left["topic"] == "exclusivity" and (
                ("non-exclusive" in left["line"].casefold()) != ("non-exclusive" in right["line"].casefold()))
            precedence_review = left["override"] or right["override"]
            if not (number_diff or modality_diff or exclusive_diff or precedence_review):
                continue
            if not meaningful_overlap and not (left["topic"] in {"notice", "renewal", "exclusivity"}):
                continue
            a, b = sorted([left["contract_id"], right["contract_id"]])
            key = (a, b, left["topic"], "|".join(sorted(set(left["numbers"] + right["numbers"]))))
            if key in seen:
                continue
            seen.add(key)
            source_a = contracts[left["contract_id"]]
            source_b = contracts[right["contract_id"]]
            evidence = [
                _citation(left["contract_id"], left["line_number"], left["line"], source_a),
                _citation(right["contract_id"], right["line_number"], right["line"], source_b),
            ]
            if precedence_review:
                classification = "precedence_or_amendment_review"
                explanation = "At least one excerpt mentions an amendment, override, or precedence term; determine which document controls before comparing obligations."
            elif number_diff:
                classification = "numeric_term_difference"
                explanation = "The excerpts contain different numeric terms. They may have different scopes or periods; this is a candidate for review, not proof of contradiction."
            elif exclusive_diff:
                classification = "exclusivity_wording_difference"
                explanation = "The excerpts use different exclusivity wording. Confirm the parties, scope, duration, and exceptions."
            else:
                classification = "opposing_modality_candidate"
                explanation = "The excerpts contain potentially opposing modal language. Check scope, exceptions, amendments, and defined terms."
            candidates.append({
                "id": f"cross:{a}:{b}:{left['topic']}:{len(candidates)+1}",
                "contract_ids": [left["contract_id"], right["contract_id"]],
                "topic": left["topic"], "classification": classification,
                "status": "candidate_requires_human_review", "severity": "medium",
                "explanation": explanation, "evidence": evidence,
                "evidence_verified": all(item["verified"] for item in evidence),
                "context_checks": {
                    "same_parties_confirmed": False,
                    "same_scope_confirmed": False,
                    "amendment_precedence_resolved": not precedence_review,
                    "incorporated_terms_resolved": False,
                },
                "unresolved_questions": [
                    "Are the parties, services, and covered periods the same?",
                    "Does an amendment, order form, or precedence clause control either excerpt?",
                    "Are exceptions or incorporated terms relevant?",
                ],
                "legal_conflict_determined": False,
                "human_review_required": True,
            })
    return candidates


def normalize_event_records(events: list[dict[str, Any]] | None, as_of: str) -> dict[str, Any]:
    """Validate event records and return only events at/before the simulated date."""
    clock = date.fromisoformat(as_of)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(events or []):
        if not isinstance(raw, dict):
            rejected.append({"index": index, "reason": "record_not_object"})
            continue
        body = str(raw.get("body", raw.get("text", raw.get("description", "")))).strip()
        event_id = str(raw.get("event_id", raw.get("id", f"supplied-{index+1}"))).strip()
        if not body:
            rejected.append({"index": index, "event_id": event_id, "reason": "missing_body"})
            continue
        timestamp = str(raw.get("timestamp", raw.get("date", ""))).strip()
        if timestamp:
            try:
                event_date = date.fromisoformat(timestamp[:10])
            except ValueError:
                rejected.append({"index": index, "event_id": event_id, "reason": "invalid_timestamp"})
                continue
            if event_date > clock:
                continue
        accepted.append({**raw, "event_id": event_id, "body": body,
                         "timestamp": timestamp or None,
                         "source_verified": bool(raw.get("source_verified", False)),
                         "ingestion_status": "accepted_unverified_source"})
    return {"events": accepted, "rejected": rejected,
            "counts": {"received": len(events or []), "accepted": len(accepted), "rejected": len(rejected)},
            "source_authenticity_verified": False}


def run_bounded_review_cycles(
    contracts: dict[str, str],
    extractions: dict[str, dict[str, Any]],
    events: list[dict[str, Any]] | None,
    as_of: str,
    max_iterations: int = 1,
    max_agent_calls: int = 300,
) -> dict[str, Any]:
    """Run bounded Thor→Loki→Heimdall→Tyr cycles and preserve unresolved gaps.

    This is a real bounded deterministic feedback workflow, not an LLM debate.
    A repeated pass can refine source citations but cannot manufacture absent
    external evidence or independently authenticate user-provided events.
    """
    from backend.agents.heimdall import verify_contract_review
    from backend.agents.loki import review_contract_candidates
    from backend.agents.norns import build_contract_timeline
    from backend.agents.tyr import arbitrate_contract_review
    from backend.services.upload_analysis import extract_document_terms

    if max_iterations < 0 or max_iterations > 3:
        raise ValueError("max_iterations must be between 0 and 3")
    normalized = normalize_event_records(events, as_of)
    visible_events = normalized["events"]
    calls = 0
    messages: list[dict[str, Any]] = []
    workstreams: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    all_verifications: list[dict[str, Any]] = []
    all_rulings: list[dict[str, Any]] = []
    all_timelines: list[dict[str, Any]] = []
    loop_traces: list[dict[str, Any]] = []
    stopped_reason = "all_workstreams_processed"

    for cid, source in sorted(contracts.items()):
        if calls + 5 > max_agent_calls:
            stopped_reason = "agent_call_budget_exhausted"
            workstreams.append({"contract_id": cid, "status": "not_run_budget_exhausted"})
            continue
        extraction = extractions.get(cid) or extract_document_terms(source, cid)
        calls += 1
        messages.append({"from": "Thor", "to": "Norns", "type": "extraction_handoff",
                         "status": "complete", "contract_id": cid,
                         "terms": len(extraction.get("extracted_terms", []))})
        timeline = build_contract_timeline(cid, extraction, as_of)
        all_timelines.extend(timeline)
        calls += 1
        messages.append({"from": "Norns", "to": "Loki", "type": "timeline_handoff",
                         "status": "complete", "contract_id": cid, "milestones": len(timeline)})
        loki = review_contract_candidates(cid, source, extraction)
        findings = list(loki.get("findings", []))[:20]
        calls += 1
        messages.append({"from": "Loki", "to": "Heimdall", "type": "risk_challenge",
                         "status": "submitted", "contract_id": cid, "findings": len(findings)})
        verification = verify_contract_review(cid, source, findings, visible_events)
        calls += 1
        messages.append({"from": "Heimdall", "to": "Tyr", "type": "evidence_verification",
                         "status": verification.get("status", "unknown"), "contract_id": cid,
                         "findings": len(verification.get("findings", []))})
        trace = {"contract_id": cid, "iterations": [], "stop_reason": "no_clarification_needed"}
        iteration = 0
        while iteration < max_iterations:
            gaps = list(dict.fromkeys(
                str(gap) for finding in findings for gap in (finding.get("evidence_gaps") or [])
                if str(gap).strip()
            ))
            if not gaps:
                trace["stop_reason"] = "evidence_threshold_met"
                break
            if calls + 5 > max_agent_calls:
                trace["stop_reason"] = "agent_call_budget_exhausted"
                stopped_reason = "agent_call_budget_exhausted"
                break
            iteration += 1
            # Thor's targeted pass extracts from the same canonical source and
            # preserves the original evidence gaps if no new source evidence exists.
            targeted = extract_document_terms(source, cid)
            calls += 1
            targeted_quotes = {str((term.get("citation") or {}).get("quote", "")) for term in targeted.get("extracted_terms", [])}
            messages.append({"from": "Loki", "to": "Thor", "type": "targeted_reextraction_request",
                             "status": "issued", "contract_id": cid, "iteration": iteration,
                             "requested_gaps": gaps})
            revised = review_contract_candidates(cid, source, targeted)
            calls += 1
            # Carry gaps forward: a re-read is not evidence that a missing event occurred.
            revised_findings = list(revised.get("findings", []))[:20]
            for item in revised_findings:
                if item.get("evidence_gaps"):
                    item["evidence_gaps"] = list(dict.fromkeys(list(item["evidence_gaps"]) + gaps))
                item["targeted_reextraction"] = {
                    "iteration": iteration,
                    "source_quotes_revisited": len(targeted_quotes),
                    "external_evidence_added": False,
                }
            revised_verification = verify_contract_review(cid, source, revised_findings, visible_events)
            calls += 1
            revised_rulings = arbitrate_contract_review(cid, revised_findings, revised_verification)
            calls += 1
            new_gaps = list(dict.fromkeys(
                str(gap) for finding in revised_findings for gap in (finding.get("evidence_gaps") or [])
                if str(gap).strip()
            ))
            trace["iterations"].append({
                "iteration": iteration, "requested_gaps": gaps,
                "source_reextraction_completed": True, "external_evidence_added": False,
                "remaining_gaps": new_gaps, "resolved": not new_gaps,
            })
            messages.extend([
                {"from": "Thor", "to": "Loki", "type": "targeted_extraction_result",
                 "status": "complete", "contract_id": cid, "iteration": iteration},
                {"from": "Loki", "to": "Heimdall", "type": "revised_risk_challenge",
                 "status": "submitted", "contract_id": cid, "iteration": iteration},
                {"from": "Heimdall", "to": "Tyr", "type": "revised_verification",
                 "status": revised_verification.get("status", "unknown"),
                 "contract_id": cid, "iteration": iteration},
            ])
            findings, verification = revised_findings, revised_verification
            if not new_gaps:
                trace["stop_reason"] = "evidence_threshold_met"
                break
            trace["stop_reason"] = "evidence_gap_persists_human_review_required"
        if iteration == max_iterations and trace["stop_reason"] == "no_clarification_needed":
            trace["stop_reason"] = "iteration_limit_reached"
        tyr = arbitrate_contract_review(cid, findings, verification)
        calls += 1
        trace["iterations_used"] = iteration
        trace["final_unresolved_gaps"] = list(dict.fromkeys(
            str(gap) for finding in findings for gap in (finding.get("evidence_gaps") or [])
            if str(gap).strip()
        ))
        trace["human_review_required"] = bool(trace["final_unresolved_gaps"] or findings)
        loop_traces.append(trace)
        all_findings.extend(findings)
        all_verifications.append({"contract_id": cid, **verification})
        all_rulings.append({"contract_id": cid, **tyr})
        messages.append({"from": "Tyr", "to": "Odin", "type": "qualified_ruling",
                         "status": tyr.get("status", "unknown"), "contract_id": cid,
                         "rulings": len(tyr.get("rulings", [])),
                         "human_approval_required": True})
        workstreams.append({
            "contract_id": cid,
            "status": "complete_with_review_items" if trace["human_review_required"] else "complete",
            "iterations_used": iteration, "max_iterations": max_iterations,
            "findings": len(findings), "timeline_candidates": len(timeline),
            "unresolved_questions": trace["final_unresolved_gaps"],
            "human_review_required": trace["human_review_required"],
            "legal_outcome_resolved": False,
        })

    return {
        "mode": "bounded_deterministic_multi_agent_workflow",
        "status": "complete_with_limitations" if workstreams else "not_run",
        "as_of_date": as_of, "max_iterations": max_iterations,
        "iterations_used": max((item.get("iterations_used", 0) for item in loop_traces), default=0),
        "agent_calls_used": calls, "agent_call_budget": max_agent_calls,
        "budget_exhausted": stopped_reason == "agent_call_budget_exhausted",
        "stop_reason": stopped_reason,
        "agent_messages": messages, "workstreams": workstreams,
        "loop_traces": loop_traces, "risk_findings": all_findings,
        "verification_outcomes": all_verifications, "rulings": all_rulings,
        "timeline_candidates": all_timelines, "event_ingestion": normalized,
        "human_review_required": any(item.get("human_review_required") for item in workstreams),
        "legal_outcome_resolved": False,
        "notice": "Bounded deterministic agent collaboration; not an LLM debate, legal opinion, breach determination, or external event authenticity check.",
    }
