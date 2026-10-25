"""Bounded, evidence-first portfolio review orchestration.

This deterministic workflow is deliberately explicit about what it cannot prove:
source excerpts and event matches are candidates, not legal conclusions. It adds
bounded clarification passes, cross-contract candidate comparison, and durable
machine-readable trace records without requiring an LLM provider.
"""
from __future__ import annotations

import re
import json
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

PARTY_ROLE_RE = re.compile(r"\b(customer|client|buyer|supplier|provider|vendor|landlord|tenant|party\s+[ab])\b", re.I)
INCORPORATION_RE = re.compile(r"\b(incorporated by reference|incorporate[sd]? by reference|attached hereto|master services agreement|statement of work|order form|schedule [a-z0-9]+|exhibit [a-z0-9]+)\b", re.I)
CONTEXT_STOP_WORDS = {
    "shall", "must", "will", "may", "not", "within", "after", "before", "days",
    "hours", "business", "calendar", "notice", "notify", "notification", "renewal",
    "agreement", "contract", "party", "provider", "supplier", "customer", "client",
    "buyer", "vendor", "landlord", "tenant", "written", "provide", "provided",
    "under", "pursuant", "subject", "terms", "conditions", "section", "article",
}


def _context_terms(line: str) -> set[str]:
    """Extract rough scope/context tokens; never treat lexical overlap as proof."""
    tokens = set(re.findall(r"[a-z]{4,}", line.casefold()))
    return tokens - CONTEXT_STOP_WORDS


def _referenced_contract_ids(line: str, known_ids: list[str], current_id: str) -> list[str]:
    """Find explicit mentions of other supplied contract IDs in a source line."""
    found = []
    for candidate in known_ids:
        if candidate == current_id:
            continue
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(candidate) + r"(?![A-Za-z0-9])", line, re.I):
            found.append(candidate)
    return sorted(found)



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
                "party_roles": sorted(set(role.casefold().replace(" ", "_") for role in PARTY_ROLE_RE.findall(line))),
                "scope_terms": _context_terms(line),
                "referenced_contract_ids": _referenced_contract_ids(source, sorted(contracts), cid),
                "incorporation_marker": bool(INCORPORATION_RE.search(source)),
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
                    # These fields are diagnostic signals only; no lexical heuristic
                    # can confirm legal identity, scope, or precedence by itself.
                    "same_parties_confirmed": False,
                    "party_roles_overlap": bool(set(left["party_roles"]) & set(right["party_roles"])),
                    "party_roles_left": left["party_roles"],
                    "party_roles_right": right["party_roles"],
                    "same_scope_confirmed": False,
                    "scope_overlap_tokens": sorted(left["scope_terms"] & right["scope_terms"])[:20],
                    "scope_overlap_ratio": round(
                        len(left["scope_terms"] & right["scope_terms"]) /
                        max(1, len(left["scope_terms"] | right["scope_terms"])), 3
                    ),
                    "explicit_cross_references": sorted(set(
                        left["referenced_contract_ids"] + right["referenced_contract_ids"]
                    )),
                    "amendment_or_precedence_marker_detected": precedence_review,
                    "amendment_precedence_resolved": False,
                    "incorporation_marker_detected": bool(left["incorporation_marker"] or right["incorporation_marker"]),
                    "incorporated_terms_resolved": False,
                },
                "unresolved_questions": [
                    "Confirm the actual legal parties and whether they act in the same capacity in both contracts.",
                    "Confirm service, territory, transaction, duration, and covered-period scope; token overlap is not scope equivalence.",
                    "Check explicit cross-references, amendments, order forms, precedence clauses, and which document controls.",
                    "Check incorporated terms, exhibits, schedules, statements of work, and exceptions.",
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
                         "source_verified_claimed": raw.get("source_verified") is True,
                         "source_verified": False,
                         "ingestion_status": "accepted_unverified_source"})
    return {"events": accepted, "rejected": rejected,
            "counts": {"received": len(events or []), "accepted": len(accepted), "rejected": len(rejected)},
            "source_authenticity_verified": False}


def reconcile_payment_events(
    events: list[dict[str, Any]] | None,
    contracts: dict[str, str],
    as_of: str,
) -> dict[str, Any]:
    """Create conservative invoice/payment linkage candidates without inventing exposure."""
    normalized = normalize_event_records(events, as_of)
    money_re = re.compile(r"\b(?:USD|US\$|\$)\s*([\d,]+(?:\.\d{1,2})?)\b", re.I)
    invoice_re = re.compile(r"\b(?:invoice|inv)\s*(?:id|no\.?|number|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{1,40})\b", re.I)
    invoice_phrase_re = re.compile(r"\binvoice\s+(INV[- ][A-Z0-9][A-Z0-9-]{1,40})\b", re.I)
    standalone_invoice_re = re.compile(r"\b(INV[- ][A-Z0-9][A-Z0-9-]{1,40})\b", re.I)
    candidates: list[dict[str, Any]] = []
    for event in normalized["events"]:
        body = str(event.get("body", ""))
        raw_amount = event.get("amount")
        amount = None
        if isinstance(raw_amount, (int, float)) and not isinstance(raw_amount, bool):
            amount = float(raw_amount)
        else:
            match = money_re.search(body)
            if match:
                try:
                    amount = float(match.group(1).replace(",", ""))
                except ValueError:
                    amount = None
        currency = str(event.get("currency") or "").upper() or (
            "USD" if re.search(r"\b(?:USD|US\$|\$)", body, re.I) else None
        )
        invoice_id = str(event.get("invoice_id") or "").strip() or None
        if not invoice_id:
            match = invoice_re.search(body) or invoice_phrase_re.search(body) or standalone_invoice_re.search(body)
            if match:
                invoice_id = (match.group(1) if match.lastindex else match.group(0)).upper().replace(" ", "-")
        cid = str(event.get("contract_id") or "").strip()
        if cid not in contracts:
            hits = [known for known in contracts if re.search(r"(?<![A-Za-z0-9])" + re.escape(known) + r"(?![A-Za-z0-9])", body, re.I)]
            cid = hits[0] if len(hits) == 1 else ""
        raw_kind = str(event.get("event_type") or event.get("type") or event.get("category") or "").casefold()
        if not raw_kind:
            if re.search(r"\b(credit|refund|credited|refunded)\b", body, re.I):
                raw_kind = "credit"
            elif re.search(r"\b(invoice|billed|billing|due|overdue)\b", body, re.I):
                raw_kind = "invoice"
            elif re.search(r"\b(payment|paid|remittance|settled)\b", body, re.I):
                raw_kind = "payment"
            else:
                raw_kind = "unknown"
        payment_state = str(event.get("payment_status") or "").casefold()
        if not payment_state:
            if re.search(r"\b(overdue|unpaid|past due|outstanding)\b", body, re.I):
                payment_state = "possibly_unpaid"
            elif re.search(r"\b(paid|settled|remitted)\b", body, re.I):
                payment_state = "possibly_paid"
            elif re.search(r"\b(credit|refund)\b", body, re.I):
                payment_state = "possible_credit_or_refund"
            else:
                payment_state = "unknown"
        if raw_kind == "unknown" and amount is None and not invoice_id:
            continue
        candidates.append({
            "event_id": event.get("event_id"),
            "contract_id": cid or None,
            "invoice_id": invoice_id,
            "event_kind": raw_kind,
            "payment_state_candidate": payment_state,
            "amount_candidate": amount,
            "currency_candidate": currency,
            "event_date": event.get("timestamp"),
            "due_date_candidate": event.get("due_date"),
            "evidence": {"document_id": event.get("event_id"), "quote": body, "verified": False},
            "source_authenticity_verified": False,
            "status": "candidate_requires_invoice_payment_trigger_reconciliation",
            "human_review_required": True,
        })

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    unlinked = []
    for item in candidates:
        if item.get("contract_id") and item.get("invoice_id"):
            grouped.setdefault((item["contract_id"], item["invoice_id"]), []).append(item)
        else:
            unlinked.append(item)
    groups = []
    for (cid, invoice_id), rows in sorted(grouped.items()):
        source = contracts.get(cid, "")
        payment_trigger_candidates = []
        penalty_trigger_candidates = []
        for line_number, line in enumerate(source.splitlines(), start=1):
            quote = line.strip()
            if not quote:
                continue
            evidence = {
                "document_id": cid, "clause_reference": f"line {line_number}",
                "line_number": line_number, "quote": quote, "verified": quote in source,
            }
            if re.search(r"\b(invoice|billing|payment|payable|pay within|net\s+\d+|due within|monthly fee|installment|milestone payment|upon acceptance|following acceptance)\b", quote, re.I):
                payment_trigger_candidates.append(evidence)
            if re.search(r"\b(late fee|late charge|interest|penalty|service credit|credit cap|liquidated damages|chargeback)\b", quote, re.I):
                penalty_trigger_candidates.append(evidence)
        # Calculate a *candidate ledger balance* only when invoice, payment, and
        # credit rows can be arithmetically reconciled without guessing. This is
        # not confirmed liability: source authenticity and contractual triggers
        # remain separate verification gates.
        unique_rows_by_id: dict[str, dict[str, Any]] = {}
        conflicting_event_ids: set[str] = set()
        for row in rows:
            event_key = str(row.get("event_id") or "")
            if event_key in unique_rows_by_id and unique_rows_by_id[event_key] != row:
                conflicting_event_ids.add(event_key)
            else:
                unique_rows_by_id[event_key] = row
        reconciliation_rows = list(unique_rows_by_id.values())
        kinds = {str(row.get("event_kind", "")).casefold() for row in reconciliation_rows}
        amounts = {row.get("amount_candidate") for row in reconciliation_rows if row.get("amount_candidate") is not None}
        currencies = {row.get("currency_candidate") for row in reconciliation_rows if row.get("currency_candidate")}
        structurally_matched = len(reconciliation_rows) >= 2 and len(kinds.intersection({"invoice", "payment", "credit"})) >= 2
        amount_consistent = len(currencies) <= 1
        invoice_rows = [row for row in reconciliation_rows if str(row.get("event_kind", "")).casefold() == "invoice"]
        payment_rows = [row for row in reconciliation_rows if str(row.get("event_kind", "")).casefold() == "payment"]
        credit_rows = [row for row in reconciliation_rows if str(row.get("event_kind", "")).casefold() == "credit"]
        invoice_amounts = {row.get("amount_candidate") for row in invoice_rows if row.get("amount_candidate") is not None}
        invoice_amount_conflict = len(invoice_amounts) > 1
        missing_amount_rows = [
            str(row.get("event_id") or "unknown")
            for row in invoice_rows + payment_rows + credit_rows
            if row.get("amount_candidate") is None
        ]
        all_amount_rows = invoice_rows + payment_rows + credit_rows
        all_have_one_currency = bool(all_amount_rows) and len(currencies) == 1 and all(
            row.get("currency_candidate") in currencies for row in all_amount_rows
            if row.get("amount_candidate") is not None
        )
        due_dates = sorted({
            str(row.get("due_date_candidate") or "").strip()
            for row in reconciliation_rows if str(row.get("due_date_candidate") or "").strip()
        })
        candidate_balance = None
        balance_status = "insufficient_reconciliation_evidence"
        if conflicting_event_ids:
            balance_status = "conflicting_duplicate_event_ids"
        elif invoice_amount_conflict:
            balance_status = "invoice_amount_conflict_requires_review"
        elif not invoice_rows or len(invoice_amounts) != 1:
            balance_status = "invoice_amount_missing"
        elif missing_amount_rows:
            balance_status = "amount_missing_on_reconciliation_rows"
        elif not all_have_one_currency:
            balance_status = "currency_missing_or_inconsistent"
        elif len(due_dates) > 1:
            balance_status = "conflicting_due_dates_requires_review"
        else:
            invoice_total = float(next(iter(invoice_amounts)))
            paid_total = sum(float(row["amount_candidate"]) for row in payment_rows)
            credited_total = sum(float(row["amount_candidate"]) for row in credit_rows)
            candidate_balance = round(invoice_total - paid_total - credited_total, 2)
            balance_status = (
                "candidate_outstanding_balance_requires_verification" if candidate_balance > 0
                else "candidate_fully_offset_requires_verification" if candidate_balance == 0
                else "candidate_overpayment_or_excess_credit_requires_review"
            )
        structurally_matched = structurally_matched and not conflicting_event_ids
        groups.append({
            "contract_id": cid, "invoice_id": invoice_id, "event_ids": [row["event_id"] for row in reconciliation_rows],
            "event_kinds": sorted(kinds), "amount_candidates": sorted(amounts),
            "currency_candidates": sorted(currencies),
            "candidate_ledger_balance": candidate_balance,
            "candidate_balance_currency": next(iter(currencies)) if len(currencies) == 1 else None,
            "candidate_balance_status": balance_status,
            "invoice_amount_candidate": next(iter(invoice_amounts)) if len(invoice_amounts) == 1 else None,
            "payment_amount_candidates": [row.get("amount_candidate") for row in payment_rows],
            "credit_amount_candidates": [row.get("amount_candidate") for row in credit_rows],
            "due_date_candidates": due_dates,
            "conflicting_event_ids": sorted(conflicting_event_ids),
            "missing_amount_event_ids": missing_amount_rows,
            "structurally_matched": structurally_matched,
            "amounts_consistent": amount_consistent and not invoice_amount_conflict,
            "status": (
                "structural_match_requires_source_verification" if structurally_matched and amount_consistent and not invoice_amount_conflict
                else "amount_or_event_type_mismatch_requires_review" if structurally_matched
                else "unmatched_invoice_payment_candidate"
            ),
            "verified_financial_exposure": None,
            "contractual_payment_trigger_candidates": payment_trigger_candidates[:20],
            "penalty_or_credit_trigger_candidates": penalty_trigger_candidates[:20],
            "trigger_evidence_status": {
                "payment_trigger_candidate_found": bool(payment_trigger_candidates),
                "penalty_or_credit_trigger_candidate_found": bool(penalty_trigger_candidates),
                "trigger_occurrence_verified": False,
                "applicability_verified": False,
            },
            "reason": "Source lines are candidate contractual triggers only. Invoice linkage, trigger occurrence, applicability, settlement, credits, period, and penalty calculation remain unverified.",
            "human_review_required": True,
        })
    return {
        "status": "not_provided" if not normalized["events"] and not candidates else "needs_source_reconciliation",
        "as_of_date": as_of,
        "event_ingestion": normalized["counts"],
        "payment_candidates": candidates,
        "invoice_groups": groups,
        "unlinked_candidates": unlinked,
        "counts": {
            "payment_candidates": len(candidates),
            "invoice_groups": len(groups),
            "unlinked_candidates": len(unlinked),
            "candidate_balances_calculated": sum(group.get("candidate_ledger_balance") is not None for group in groups),
            "candidate_outstanding_balances": sum(
                group.get("candidate_balance_status") == "candidate_outstanding_balance_requires_verification"
                for group in groups
            ),
            "reconciliation_blockers": sum(group.get("candidate_ledger_balance") is None for group in groups),
        },
        "verified_financial_exposure": None,
        "note": "No financial exposure is aggregated from unverified events. Reconcile original invoice, due date, contractual trigger, payment/credit record, and source authenticity first.",
    }


def _call_llm_json(system_prompt: str, user_prompt: str, max_tokens: int = 1400) -> tuple[dict[str, Any] | None, str]:
    """Call the configured provider only when the caller explicitly enables it."""
    from backend.config import USE_CLAUDE
    if not USE_CLAUDE:
        return None, "provider_not_configured"
    try:
        from backend.claude_client import ask_claude
        raw = ask_claude(system_prompt, user_prompt, max_tokens)
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None, "invalid_json_response"
        value = json.loads(raw[start:end + 1])
        return (value, "complete") if isinstance(value, dict) else (None, "invalid_json_response")
    except Exception as exc:
        return None, "provider_error_" + type(exc).__name__


def _llm_thor_terms(contract_id: str, source: str) -> tuple[list[dict[str, Any]], str]:
    payload, status = _call_llm_json(
        "You are Thor, a conservative contract extraction agent. Return JSON only. Extract source-stated terms; never infer missing facts.",
        "Return JSON {\"extracted_terms\":[{\"category\":\"...\",\"quote\":\"exact verbatim source quotation\",\"value\":\"...\"}]}. "
        "Every quote must be copied exactly from SOURCE. Do not return summaries without a quote. SOURCE ID: "
        + contract_id + "\nSOURCE:\n" + source[:40000],
        1500,
    )
    if not payload:
        return [], status
    terms = []
    seen = set()
    for item in (payload.get("extracted_terms") or [])[:20]:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", ""))
        if not quote or quote not in source or quote in seen:
            continue
        seen.add(quote)
        line_number = source.count("\n", 0, source.find(quote)) + 1
        terms.append({
            "category": str(item.get("category") or "source_term_candidate")[:80],
            "value": quote,
            "confidence": 0.65,
            "confidence_basis": "LLM suggestion with exact-quote validation; not calibrated",
            "citation": {
                "document_id": contract_id, "line_number": line_number,
                "clause_reference": f"line {line_number}", "quote": quote,
                "verified": True,
                "verification_note": "LLM-suggested quote independently matched canonical source text.",
            },
            "agent": "Thor", "mode": "llm_quote_validated",
        })
    return terms, status


def _llm_loki_findings(contract_id: str, source: str, current_findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    payload, status = _call_llm_json(
        "You are Loki, an adversarial contract reviewer. Identify plausible risks and ambiguities, not proven breaches. Return JSON only.",
        "Return JSON {\"findings\":[{\"category\":\"...\",\"claim\":\"potential risk only\",\"severity\":\"low|medium|high\","
        "\"quote\":\"exact source quote\",\"reasoning\":\"why a reviewer should challenge it\","
        "\"evidence_gaps\":[\"missing fact\"]}]}. Do not assert a breach. Each quote must be verbatim. "
        "Existing deterministic candidates: " + json.dumps(current_findings[:8], ensure_ascii=False, default=str)[:5000]
        + "\nCONTRACT ID: " + contract_id + "\nSOURCE:\n" + source[:40000],
        1600,
    )
    if not payload:
        return [], status
    output = []
    for index, item in enumerate((payload.get("findings") or [])[:8], start=1):
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", ""))
        if not quote or quote not in source:
            continue
        line_number = source.count("\n", 0, source.find(quote)) + 1
        citation = _citation(contract_id, line_number, quote, source)
        severity = str(item.get("severity", "medium")).casefold()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        output.append({
            "id": f"{contract_id}:llm-risk:{index}", "contract_id": contract_id,
            "category": str(item.get("category") or "llm_review_candidate")[:80],
            "title": str(item.get("category") or "LLM review candidate")[:120],
            "severity": severity, "likelihood": "unassessed_not_a_probability",
            "status": "candidate_requires_review",
            "claim": str(item.get("claim") or "Potential risk candidate; human review required.")[:1200],
            "reason": "LLM-suggested risk; exact quotation was validated, but interpretation is not a legal conclusion.",
            "attack_path": [str(item.get("reasoning") or "Review the cited language in context.")[:1500]],
            "evidence_gaps": [str(gap)[:300] for gap in (item.get("evidence_gaps") or [])[:8]],
            "citations": [citation], "evidence": citation, "agent": "Loki",
            "mode": "llm_quote_validated",
        })
    return output, status


def _llm_heimdall_review(contract_id: str, source: str, findings: list[dict[str, Any]],
                         events: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    compact_events = [{"event_id": e.get("event_id"), "timestamp": e.get("timestamp"),
                       "body": str(e.get("body", ""))[:1200]} for e in events[:40]]
    payload, status = _call_llm_json(
        "You are Heimdall, an evidence verifier. Distinguish supported facts from missing evidence. Return JSON only; never infer authenticity.",
        "Return JSON {\"challenges\":[\"...\"],\"evidence_gaps\":[\"...\"],"
        "\"event_evidence\":[{\"finding_id\":\"...\",\"event_id\":\"...\",\"quote\":\"exact event quote\"}]}. "
        "Only cite event quotes copied exactly from a supplied event. A matching quote does not authenticate its source. "
        "CONTRACT ID: " + contract_id + "\nFINDINGS:\n" + json.dumps(findings[:12], ensure_ascii=False, default=str)[:7000]
        + "\nEVENTS:\n" + json.dumps(compact_events, ensure_ascii=False, default=str)[:18000]
        + "\nCONTRACT SOURCE:\n" + source[:20000],
        1200,
    )
    if not payload:
        return None, status
    event_by_id = {str(e.get("event_id")): e for e in events}
    validated = []
    rejected = 0
    for item in (payload.get("event_evidence") or [])[:20]:
        if not isinstance(item, dict):
            continue
        event = event_by_id.get(str(item.get("event_id")))
        quote = str(item.get("quote", ""))
        if event and quote and quote in str(event.get("body", "")):
            validated.append({"finding_id": item.get("finding_id"), "event_id": item.get("event_id"),
                              "quote": quote, "verified": True,
                              "verification_note": "Exact quote matched supplied event body; event authenticity remains unverified."})
        else:
            rejected += 1
    return {
        "agent": "Heimdall", "status": "llm_review_with_limitations",
        "challenges": [str(x)[:1000] for x in (payload.get("challenges") or [])[:10]],
        "evidence_gaps": [str(x)[:500] for x in (payload.get("evidence_gaps") or [])[:15]],
        "validated_event_evidence": validated, "rejected_event_citations": rejected,
        "source_authenticity_verified": False,
    }, status


def _llm_tyr_review(contract_id: str, source: str, findings: list[dict[str, Any]],
                    verification: dict[str, Any], rulings: dict[str, Any],
                    events: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    payload, status = _call_llm_json(
        "You are Tyr, a cautious contract-review arbitrator. Return JSON only. Never declare legal liability or a proven breach from incomplete evidence. Actions must remain drafts requiring human approval.",
        "Return JSON {\"rulings\":[{\"finding_id\":\"...\",\"rationale\":\"...\",\"unproven_claims\":[\"...\"],"
        "\"citation_quotes\":[\"exact quote from contract or event\"],\"draft_subject\":\"...\",\"draft_body\":\"...\"}]}. "
        "Each citation quote must be copied exactly from the contract or supplied event. Do not approve actions or send anything. "
        "FINDINGS:\n" + json.dumps(findings[:10], ensure_ascii=False, default=str)[:6500]
        + "\nVERIFICATION:\n" + json.dumps(verification, ensure_ascii=False, default=str)[:5000]
        + "\nEXISTING RULINGS:\n" + json.dumps((rulings.get("rulings") or [])[:10], ensure_ascii=False, default=str)[:5000]
        + "\nEVENTS:\n" + json.dumps([{"event_id": e.get("event_id"), "body": e.get("body", "")} for e in events[:30]], ensure_ascii=False, default=str)[:12000]
        + "\nCONTRACT ID: " + contract_id + "\nSOURCE:\n" + source[:30000],
        1600,
    )
    if not payload:
        return None, status
    event_bodies = [str(e.get("body", "")) for e in events]
    existing = {str(r.get("finding_id")): r for r in rulings.get("rulings", [])}
    accepted = 0
    for item in (payload.get("rulings") or [])[:15]:
        if not isinstance(item, dict):
            continue
        quotes = [str(q) for q in item.get("citation_quotes", [])[:5]]
        valid_quotes = [q for q in quotes if q and (q in source or any(q in body for body in event_bodies))]
        if not valid_quotes:
            continue
        finding_id = str(item.get("finding_id", ""))
        target = existing.get(finding_id)
        if not target:
            continue
        target["llm_review"] = {
            "rationale": str(item.get("rationale") or "")[:1500],
            "unproven_claims": [str(x)[:500] for x in item.get("unproven_claims", [])[:8]],
            "validated_citation_quotes": valid_quotes,
            "human_review_required": True,
        }
        draft = target.get("action_draft") or {}
        if item.get("draft_subject"):
            draft["llm_suggested_subject"] = str(item["draft_subject"])[:240]
        if item.get("draft_body"):
            draft["llm_suggested_body"] = str(item["draft_body"])[:3000]
        draft["human_approval_required"] = True
        draft["status"] = "draft_only_not_sent"
        target["action_draft"] = draft
        accepted += 1
    return {"agent": "Tyr", "accepted_rulings": accepted, "rejected_or_unmatched_rulings": max(0, len(payload.get("rulings") or []) - accepted),
            "legal_outcome_resolved": False, "human_approval_required": True}, status


def run_bounded_review_cycles(
    contracts: dict[str, str],
    extractions: dict[str, dict[str, Any]],
    events: list[dict[str, Any]] | None,
    as_of: str,
    max_iterations: int = 1,
    max_agent_calls: int = 300,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Run bounded agent cycles; optional LLM suggestions are accepted only with exact-quote validation.

    Without explicit opt-in and a configured provider this remains deterministic. LLM output never
    authenticates events, establishes breach, or bypasses human approval.
    """
    from backend.agents.heimdall import verify_contract_review
    from backend.agents.loki import review_contract_candidates
    from backend.agents.norns import build_contract_timeline
    from backend.agents.tyr import arbitrate_contract_review
    from backend.services.upload_analysis import extract_document_terms
    from backend.config import USE_CLAUDE, EVIDENCE_CONFIDENCE_THRESHOLD

    llm_enabled = bool(use_llm and USE_CLAUDE)
    llm_status: dict[str, str] = {}
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
        required_initial_calls = 5 + (4 if llm_enabled else 0)
        if calls + required_initial_calls > max_agent_calls:
            stopped_reason = "agent_call_budget_exhausted"
            workstreams.append({"contract_id": cid, "status": "not_run_budget_exhausted"})
            continue
        extraction = extractions.get(cid) or extract_document_terms(source, cid)
        calls += 1
        if llm_enabled:
            extra_terms, llm_status["Thor"] = _llm_thor_terms(cid, source)
            calls += 1
            existing_quotes = {str((term.get("citation") or {}).get("quote", "")) for term in extraction.get("extracted_terms", [])}
            for term in extra_terms:
                if term.get("citation", {}).get("quote") not in existing_quotes:
                    extraction.setdefault("extracted_terms", []).append(term)
                    existing_quotes.add(term.get("citation", {}).get("quote"))
            messages.append({"from": "Thor", "to": "Odin", "type": "llm_extraction_review",
                             "status": llm_status["Thor"], "contract_id": cid,
                             "validated_terms_added": len(extra_terms)})
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
        if llm_enabled:
            llm_findings, llm_status["Loki"] = _llm_loki_findings(cid, source, findings)
            calls += 1
            known_ids = {item.get("id") for item in findings}
            findings.extend(item for item in llm_findings if item.get("id") not in known_ids)
            findings = findings[:28]
            messages.append({"from": "Loki", "to": "Heimdall", "type": "llm_risk_challenge",
                             "status": llm_status["Loki"], "contract_id": cid,
                             "validated_findings_added": len(llm_findings)})
        messages.append({"from": "Loki", "to": "Heimdall", "type": "risk_challenge",
                         "status": "submitted", "contract_id": cid, "findings": len(findings)})
        verification = verify_contract_review(cid, source, findings, visible_events)
        calls += 1
        if llm_enabled:
            llm_verification, llm_status["Heimdall"] = _llm_heimdall_review(cid, source, findings, visible_events)
            calls += 1
            if llm_verification:
                verification["llm_review"] = llm_verification
                verification.setdefault("evidence_gaps", []).extend((llm_verification.get("evidence_gaps") or []))
                verification["evidence_gaps"] = list(dict.fromkeys(verification["evidence_gaps"]))
            messages.append({"from": "Heimdall", "to": "Tyr", "type": "llm_evidence_review",
                             "status": llm_status["Heimdall"], "contract_id": cid,
                             "validated_event_quotes": len((llm_verification or {}).get("validated_event_evidence", []))})
        messages.append({"from": "Heimdall", "to": "Tyr", "type": "evidence_verification",
                         "status": verification.get("status", "unknown"), "contract_id": cid,
                         "findings": len(verification.get("findings", []))})
        trace = {"contract_id": cid, "iterations": [], "stop_reason": "no_clarification_needed"}
        iteration = 0
        # FR7.1: record Loki/Heimdall disagreement explicitly for Tyr.
        verified_rows = list(verification.get("findings") or [])
        citation_ratio = (sum(bool(item.get("citation_checks_passed")) for item in verified_rows) / len(verified_rows)) if verified_rows else 0.0
        messages.append({
            "from": "Heimdall", "to": "Tyr", "type": "evidence_disagreement",
            "status": "disagreement_recorded" if any(str(item.get("claim_assessment", "")).startswith("challenged") or item.get("challenges") for item in verified_rows) else "qualified_support_recorded",
            "contract_id": cid, "loki_findings": len(findings),
            "heimdall_challenges": sum(bool(item.get("challenges")) for item in verified_rows),
            "citation_verification_ratio": round(citation_ratio, 3),
        })
        while True:
            gaps = list(dict.fromkeys(
                [str(gap) for finding in findings for gap in (finding.get("evidence_gaps") or []) if str(gap).strip()]
                + [str(gap) for gap in (verification.get("evidence_gaps") or []) if str(gap).strip()]
                + [str(gap) for item in (verification.get("findings") or []) for gap in (item.get("evidence_gaps") or []) if str(gap).strip()]
            ))
            if not gaps:
                trace["stop_reason"] = "evidence_threshold_met"
                break
            # A repeated source read cannot resolve missing external event or trigger facts.
            verified_rows = list(verification.get("findings") or [])
            citation_ratio = (sum(bool(item.get("citation_checks_passed")) for item in verified_rows) / len(verified_rows)) if verified_rows else 0.0
            has_citation_failure = any(not item.get("citation_checks_passed") for item in verified_rows)
            if verified_rows and citation_ratio >= EVIDENCE_CONFIDENCE_THRESHOLD and not has_citation_failure:
                trace["stop_reason"] = "evidence_threshold_met_with_open_questions"
                trace["threshold"] = EVIDENCE_CONFIDENCE_THRESHOLD
                trace["citation_verification_ratio"] = round(citation_ratio, 3)
                break
            if iteration >= max_iterations:
                trace["stop_reason"] = "iteration_limit_reached"
                break
            if calls + 5 > max_agent_calls:
                trace["stop_reason"] = "agent_call_budget_exhausted"
                stopped_reason = "agent_call_budget_exhausted"
                break
            iteration += 1
            messages.append({
                "from": "Loki", "to": "Thor", "type": "targeted_reextraction_request",
                "status": "issued", "contract_id": cid, "iteration": iteration, "requested_gaps": gaps,
                "requested_evidence": ["Exact clause quotation and heading", "Surrounding paragraph, definitions, exceptions, amendments, and precedence", "Source-backed trigger facts present in the supplied contract"],
            })
            targeted = extract_document_terms(source, cid)
            calls += 1
            targeted_quotes = {str((term.get("citation") or {}).get("quote", "")) for term in targeted.get("extracted_terms", [])}
            messages.append({
                "from": "Thor", "to": "Loki", "type": "targeted_extraction_result",
                "status": "complete", "contract_id": cid, "iteration": iteration,
                "source_quotes_revisited": len(targeted_quotes), "external_evidence_added": False,
            })
            revised = review_contract_candidates(cid, source, targeted)
            calls += 1
            revised_findings = list(revised.get("findings", []))[:20]
            for item in revised_findings:
                if item.get("evidence_gaps"):
                    item["evidence_gaps"] = list(dict.fromkeys(list(item["evidence_gaps"]) + gaps))
                item["targeted_reextraction"] = {"iteration": iteration, "source_quotes_revisited": len(targeted_quotes), "external_evidence_added": False}
            revised_verification = verify_contract_review(cid, source, revised_findings, visible_events)
            calls += 1
            revised_rulings = arbitrate_contract_review(cid, revised_findings, revised_verification)
            calls += 1
            new_gaps = list(dict.fromkeys(str(gap) for finding in revised_findings for gap in (finding.get("evidence_gaps") or []) if str(gap).strip()))
            trace["iterations"].append({
                "iteration": iteration, "requested_gaps": gaps, "source_reextraction_completed": True,
                "external_evidence_added": False, "remaining_gaps": new_gaps, "resolved": not new_gaps,
                "loki_findings": len(revised_findings),
                "heimdall_challenges": sum(bool(item.get("challenges")) for item in (revised_verification.get("findings") or [])),
                "tyr_rulings": len(revised_rulings.get("rulings", [])),
            })
            messages.extend([
                {"from": "Loki", "to": "Heimdall", "type": "revised_risk_challenge", "status": "submitted", "contract_id": cid, "iteration": iteration},
                {"from": "Heimdall", "to": "Tyr", "type": "revised_evidence_disagreement", "status": "reviewed", "contract_id": cid, "iteration": iteration, "challenges": sum(bool(item.get("challenges")) for item in (revised_verification.get("findings") or []))},
                {"from": "Tyr", "to": "Odin", "type": "iterative_dispute_ruling", "status": "complete", "contract_id": cid, "iteration": iteration, "rulings": len(revised_rulings.get("rulings", [])), "human_approval_required": True},
            ])
            findings, verification = revised_findings, revised_verification
            if not new_gaps:
                trace["stop_reason"] = "evidence_threshold_met"
                break
            trace["stop_reason"] = "evidence_gap_persists_human_review_required"
        tyr = arbitrate_contract_review(cid, findings, verification)
        calls += 1
        if llm_enabled:
            llm_ruling, llm_status["Tyr"] = _llm_tyr_review(cid, source, findings, verification, tyr, visible_events)
            calls += 1
            if llm_ruling:
                tyr["llm_review"] = llm_ruling
            messages.append({"from": "Tyr", "to": "Odin", "type": "llm_qualified_ruling",
                             "status": llm_status["Tyr"], "contract_id": cid,
                             "accepted_rulings": (llm_ruling or {}).get("accepted_rulings", 0),
                             "human_approval_required": True})
        trace["iterations_used"] = iteration
        trace["final_unresolved_gaps"] = list(dict.fromkeys(
            [str(gap) for finding in findings for gap in (finding.get("evidence_gaps") or []) if str(gap).strip()]
            + [str(gap) for gap in (verification.get("evidence_gaps") or []) if str(gap).strip()]
            + [str(gap) for item in (verification.get("findings") or []) for gap in (item.get("evidence_gaps") or []) if str(gap).strip()]
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

    not_run_workstreams = [item for item in workstreams if item.get("status") == "not_run_budget_exhausted"]
    # Unresolved evidence after a completed, bounded pass is a review item,
    # not an orchestration failure. Mark partial only when the workflow was
    # actually prevented from performing required work by its iteration limit.
    iteration_limited = any(
        trace.get("stop_reason") == "iteration_limit_reached"
        for trace in loop_traces
    )
    partial_completion = bool(
        stopped_reason == "agent_call_budget_exhausted"
        or not_run_workstreams
        or iteration_limited
    )
    final_status = (
        "partial_budget_exhausted" if stopped_reason == "agent_call_budget_exhausted" or not_run_workstreams
        else "partial_review_limit_reached" if iteration_limited
        else "complete_with_review_items" if workstreams
        else "not_run"
    )
    return {
        "mode": "bounded_hybrid_llm_multi_agent_workflow" if llm_enabled else "bounded_deterministic_multi_agent_workflow",
        "status": final_status,
        "as_of_date": as_of, "max_iterations": max_iterations,
        "iterations_used": max((item.get("iterations_used", 0) for item in loop_traces), default=0),
        "agent_calls_used": calls, "agent_call_budget": max_agent_calls,
        "budget_exhausted": stopped_reason == "agent_call_budget_exhausted" or bool(not_run_workstreams),
        "partial_completion": partial_completion,
        "not_run_contract_ids": [item.get("contract_id") for item in not_run_workstreams],
        "stop_reason": stopped_reason,
        "agent_messages": messages, "workstreams": workstreams, "llm_enabled": llm_enabled,
        "llm_provider_status": "enabled" if llm_enabled else "not_configured" if use_llm and not USE_CLAUDE else "not_requested",
        "llm_agent_status": llm_status,
        "loop_traces": loop_traces, "risk_findings": all_findings,
        "verification_outcomes": all_verifications, "rulings": all_rulings,
        "timeline_candidates": all_timelines, "event_ingestion": normalized,
        "human_review_required": any(item.get("human_review_required") for item in workstreams) or partial_completion,
        "legal_outcome_resolved": False,
        "notice": ("Bounded hybrid agent workflow with quote-validated LLM suggestions; still not a legal opinion, breach determination, or event-authenticity check." if llm_enabled else "Bounded deterministic agent collaboration; LLM use was not enabled or no provider key is configured. This is not a legal opinion, breach determination, or external event-authenticity check."),
    }


def review_cross_contract_candidates(
    candidates: list[dict[str, Any]],
    contracts: dict[str, str],
    events: list[dict[str, Any]] | None,
    as_of: str,
    max_agent_calls: int = 150,
) -> dict[str, Any]:
    """Run bounded Loki → Heimdall → Tyr review on portfolio-level candidates.

    This is a deterministic, evidence-first review trace. It validates quotations
    against canonical contract text, surfaces explicitly linked event candidates,
    and keeps the outcome unresolved for human review. It never concludes that a
    legal conflict or breach exists.
    """
    normalized = normalize_event_records(events, as_of)
    visible_events = normalized["events"]
    traces: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    calls_used = 0
    stop_reason = "all_candidates_reviewed"

    for candidate in candidates[:100]:
        candidate_id = str(candidate.get("id", ""))
        contract_ids = [str(cid) for cid in candidate.get("contract_ids", []) if str(cid) in contracts]
        if len(contract_ids) != 2:
            continue
        if calls_used + 3 > max(0, int(max_agent_calls)):
            stop_reason = "agent_call_budget_exhausted"
            traces.append({
                "candidate_id": candidate_id, "status": "not_run_budget_exhausted",
                "decision": "not_reviewed", "legal_conflict_determined": False,
                "human_review_required": True,
            })
            continue

        evidence = candidate.get("evidence", []) or []
        amendment_context = candidate.get("amendment_resolution", {}) or {}
        verified_evidence = []
        for item in evidence:
            cid = str(item.get("document_id", ""))
            quote = str(item.get("quote", ""))
            source = contracts.get(cid, "")
            verified_evidence.append({
                **item,
                "verified": bool(quote and quote in source),
                "verification_note": (
                    "Exact quote matched canonical contract text."
                    if quote and quote in source
                    else "Quote could not be independently matched to the supplied canonical contract."
                ),
            })
        calls_used += 1
        all_quotes_verified = bool(verified_evidence) and all(item.get("verified") for item in verified_evidence)
        classification = str(candidate.get("classification", ""))
        severity = str(candidate.get("severity", "medium")).lower()
        if severity not in {"low", "medium", "high", "critical"}:
            severity = "medium"
        if not all_quotes_verified:
            likelihood = "indeterminate"
            likelihood_rationale = "At least one clause citation did not match canonical source text."
        elif classification in {"numeric_term_difference", "modality_conflict", "exclusivity_conflict"}:
            likelihood = "elevated"
            likelihood_rationale = "Both excerpts are source-verified and a same-topic numeric/modality difference was detected; party scope, trigger facts, and precedence remain unresolved."
        else:
            likelihood = "moderate"
            likelihood_rationale = "Verified excerpts indicate a possible same-topic inconsistency, but semantic scope and precedence are not established."
        clarification_requests = []
        if not all_quotes_verified or amendment_context.get("questions_to_resolve"):
            clarification_requests.append({
                "from": "Loki", "to": "Thor", "type": "targeted_reextraction_request",
                "candidate_id": candidate_id, "contract_ids": contract_ids,
                "reason": "Evidence is unverified or amendment/scope context is unresolved.",
                "requested_evidence": [
                    "Exact full clauses and surrounding definitions",
                    "Executed amendments, order forms, and precedence language",
                    "Party, service, territory, and effective-date scope",
                ],
            })
        loki = {
            "agent": "Loki",
            "status": "challenge_submitted",
            "candidate_id": candidate_id,
            "claim_challenged": candidate.get("explanation", "Potential cross-contract inconsistency."),
            "severity": severity,
            "severity_rationale": "Potential commercial/operational impact is material enough to review; actual magnitude depends on scope and facts.",
            "likelihood": likelihood,
            "likelihood_rationale": likelihood_rationale,
            "alternative_explanations": [
                "The clauses may govern different parties, services, territories, transactions, or periods.",
                "An amendment, order form, precedence clause, exception, or incorporated term may control.",
                "Amendment lineage status: " + str(amendment_context.get("status", "not assessed")) + ".",
            ],
            "attack_path": [
                "Compare exact operative language, including negation, numeric thresholds, defined terms, exceptions, and remedies.",
                "Confirm the clauses apply to the same parties, service, territory, transaction, and effective period.",
                "Trace amendments, incorporation by reference, and precedence; test whether a later or controlling document resolves the difference.",
                "Ask each counterparty's strongest defense and identify the missing fact that would prove or defeat the alleged conflict.",
            ],
            "evidence": verified_evidence,
            "clarification_requests": clarification_requests,
            "requires_clarification": bool(clarification_requests),
            "legal_conflict_determined": False,
        }
        messages.append({
            "from": "Loki", "to": "Heimdall", "type": "cross_contract_challenge",
            "status": "submitted", "candidate_id": candidate_id,
            "evidence_count": len(verified_evidence),
        })

        topic = str(candidate.get("topic", "")).replace("_", " ").casefold()
        event_candidates = []
        for event in visible_events:
            event_contract = str(event.get("contract_id", "")).strip()
            body = str(event.get("body", ""))
            explicit_link = event_contract in contract_ids or any(
                re.search(r"(?<![A-Za-z0-9])" + re.escape(cid) + r"(?![A-Za-z0-9])", body, re.I)
                for cid in contract_ids
            )
            topic_match = bool(topic and re.search(r"\b" + re.escape(topic) + r"\b", body, re.I))
            if explicit_link and topic_match:
                event_candidates.append({
                    "event_id": event.get("event_id"),
                    "contract_id": event_contract or None,
                    "quote": body,
                    "quote_matches_supplied_event": True,
                    "source_authenticity_verified": False,
                    "status": "event_candidate_requires_source_and_trigger_verification",
                })
        calls_used += 1
        citations_verified = len(verified_evidence) >= 2 and all(
            item.get("verified") for item in verified_evidence[:2]
        )
        heimdall = {
            "agent": "Heimdall",
            "status": "source_quotes_verified" if citations_verified else "citation_gap",
            "candidate_id": candidate_id,
            "verified_contract_citations": sum(bool(item.get("verified")) for item in verified_evidence),
            "citation_count": len(verified_evidence),
            "event_candidates": event_candidates,
            "event_source_authenticity_verified": False,
            "challenges": [
                "Quoted clauses are source-grounded but do not establish identical scope or a legal contradiction."
            ],
            "evidence_gaps": list(dict.fromkeys(list(candidate.get("unresolved_questions", []) or []) + list(amendment_context.get("questions_to_resolve", []) or []))),
            "amendment_context": amendment_context,
            "precedence_clauses_reviewed": len(amendment_context.get("precedence_clauses", []) or []),
            "lineage_edges_reviewed": len(amendment_context.get("lineage_edges", []) or []),
            "legal_conflict_determined": False,
        }
        messages.append({
            "from": "Heimdall", "to": "Tyr", "type": "cross_contract_evidence_verification",
            "status": heimdall["status"], "candidate_id": candidate_id,
            "verified_citations": heimdall["verified_contract_citations"],
            "event_candidates": len(event_candidates),
        })

        calls_used += 1
        decision = "retain_for_human_review" if citations_verified else "insufficient_verified_evidence"
        tyr = {
            "agent": "Tyr",
            "status": "draft_only_not_sent",
            "candidate_id": candidate_id,
            "decision": decision,
            "rationale": (
                "Both contract quotations matched the supplied source. Amendment context status: "
                + str(amendment_context.get("status", "not assessed"))
                + ". Party identity, scope, execution, effective dates, precedence, and incorporated terms still require human confirmation; no legal conflict is determined."
                if citations_verified else
                "One or more source quotations could not be verified. Do not rely on this candidate until the source is corrected."
            ),
            "legal_conflict_determined": False,
            "human_approval_required": True,
            "action_draft": {
                "subject": "Human review: cross-contract " + topic + " candidate",
                "body": (
                    "Review candidate " + candidate_id + " across contracts " + " and ".join(contract_ids) +
                    ". Verify party identity, scope, amendments, precedence, incorporated terms, and any relevant events. "
                    "This draft is not a legal conclusion and has not been sent."
                ),
                "citations": verified_evidence,
                "amendment_resolution": amendment_context,
                "status": "draft_only_not_sent",
                "human_approval_required": True,
            },
        }
        messages.append({
            "from": "Tyr", "to": "Odin", "type": "cross_contract_review_ruling",
            "status": decision, "candidate_id": candidate_id,
            "human_approval_required": True, "legal_conflict_determined": False,
        })
        traces.append({
            "candidate_id": candidate_id, "contract_ids": contract_ids,
            "status": "complete_with_review_items",
            "loki_challenge": loki, "heimdall_verification": heimdall,
            "tyr_ruling": tyr, "iterations_used": 0,
            "stop_reason": "human_review_required",
            "legal_conflict_determined": False, "human_review_required": True,
        })

    if len(candidates) > 100 and stop_reason == "all_candidates_reviewed":
        stop_reason = "candidate_limit_reached"
    return {
        "mode": "bounded_cross_contract_review",
        "status": (
            "partial_budget_exhausted" if stop_reason == "agent_call_budget_exhausted"
            else "partial_candidate_limit_reached" if stop_reason == "candidate_limit_reached"
            else "complete_with_review_items" if traces else "no_candidates"
        ),
        "candidate_count": len(candidates),
        "candidate_review_limit": 100,
        "candidates_not_reviewed": max(0, len(candidates) - len(traces)),
        "agent_calls_used": calls_used,
        "agent_call_budget": max(0, int(max_agent_calls)),
        "stop_reason": stop_reason,
        "event_ingestion": normalized,
        "traces": traces,
        "agent_messages": messages,
        "legal_outcome_resolved": False,
        "human_review_required": bool(candidates),
    }
