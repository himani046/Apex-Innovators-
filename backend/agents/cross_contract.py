"""Conservative cross-contract inconsistency candidates."""
import re

RULES = {
    "notice": re.compile(r"\b(notice|notify|notification)\b", re.I),
    "payment": re.compile(r"\b(payment|invoice|net\s+\d+|pay within)\b", re.I),
    "renewal": re.compile(r"\b(renewal|renew|non-renewal)\b", re.I),
    "termination": re.compile(r"\b(termination|terminate|cure period)\b", re.I),
    "liability": re.compile(r"\b(liability|indemnity|indemnify|damages)\b", re.I),
    "service_level": re.compile(r"\b(uptime|availability|service level|response time)\b", re.I),
}
NUM = re.compile(r"\b(\d+(?:\.\d+)?)\s*(hours?|days?|months?|years?|%)?\b", re.I)
MOD = re.compile(r"\b(must not|shall not|may not|prohibited|non-exclusive|exclusive|must|shall|required|permitted|allowed)\b", re.I)
NEG = {"must not", "shall not", "may not", "prohibited"}
POS = {"must", "shall", "required", "permitted", "allowed"}
def detect_cross_contract_candidates(contracts):
    """Flag different numeric/modality terms as candidates, never as legal conclusions."""
    provisions = {}
    for cid, source in contracts.items():
        for n, raw in enumerate(source.splitlines(), 1):
            line = raw.strip()
            if not line: continue
            for topic, pattern in RULES.items():
                if pattern.search(line):
                    nums = [(m.group(1), (m.group(2) or "").lower().rstrip("s")) for m in NUM.finditer(line)]
                    mods = {m.group(1).lower() for m in MOD.finditer(line)}
                    if nums or mods:
                        provisions.setdefault(topic, []).append((cid, n, raw, nums, mods))
    found = []
    for topic, items in provisions.items():
        for i, a in enumerate(items):
            for b in items[i+1:]:
                if a[0] == b[0]: continue
                numeric_diff = bool(a[3] and b[3] and a[3] != b[3])
                modality_diff = bool((a[4] & NEG and b[4] & POS) or (b[4] & NEG and a[4] & POS) or
                                     ("exclusive" in a[4] and "non-exclusive" in b[4]) or
                                     ("non-exclusive" in a[4] and "exclusive" in b[4]))
                if not (numeric_diff or modality_diff): continue
                found.append({
                    "id": f"cross:{topic}:{a[0]}:{a[1]}:{b[0]}:{b[1]}",
                    "category": "cross_contract_inconsistency_candidate", "topic": topic,
                    "contract_ids": [a[0], b[0]], "severity": "medium",
                    "likelihood": "unassessed_not_a_probability", "status": "candidate_requires_human_review",
                    "claim": f"Potentially inconsistent {topic.replace('_', ' ')} language appears across two contracts.",
                    "reason": "Different numeric terms or opposite modality were found; scope, parties, amendments and precedence are not resolved.",
                    "citations": [
                        {"document_id": a[0], "clause_reference": f"line {a[1]}", "line_number": a[1], "quote": a[2], "verified": a[2] in contracts[a[0]]},
                        {"document_id": b[0], "clause_reference": f"line {b[1]}", "line_number": b[1], "quote": b[2], "verified": b[2] in contracts[b[0]]},
                    ],
                    "evidence_gaps": ["Confirm parties, scope, effective versions, amendments and precedence clauses."],
                    "human_review_required": True,
                    "notice": "Syntactic inconsistency candidate only; not a legal conflict determination."
                })
    return found
