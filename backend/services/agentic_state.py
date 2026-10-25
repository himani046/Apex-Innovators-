"""Structured per-run state and bounded collaboration primitives for Odin."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


STATE_SECTIONS = (
    "contracts_and_relationships",
    "extracted_clauses",
    "timeline_events",
    "financial_calculations",
    "risk_claims",
    "evidence_references",
    "verification_outcomes",
    "unresolved_questions",
    "recommended_actions",
)


class SharedAgentState:
    """Validated, JSON-serializable shared state with an append-only handoff log."""

    def __init__(self, initial: dict[str, Any] | None = None):
        self.data: dict[str, Any] = {
            "schema_version": "1.0",
            "contracts_and_relationships": {},
            "extracted_clauses": [],
            "timeline_events": [],
            "financial_calculations": [],
            "risk_claims": [],
            "evidence_references": [],
            "verification_outcomes": [],
            "unresolved_questions": [],
            "recommended_actions": [],
            "agent_messages": [],
            "agent_status": {},
            "iteration": {"current": 0, "max": 0, "stop_reason": None},
            "api_usage": {"max_calls": 0, "calls_used": 0, "remaining_calls": 0},
        }
        if initial:
            for key, value in initial.items():
                self.data[key] = deepcopy(value)

    def update(self, section: str, value: Any) -> None:
        if section not in STATE_SECTIONS and section not in {
            "run_id", "as_of_date", "scope", "status", "workstream_analysis",
            "portfolio_summary", "portfolio_operations", "decision_queue",
            "portfolio_extraction", "contract_reconciliation", "timeline",
            "extraction", "risk_finding", "verification", "ruling", "event_summary",
            "limitations", "agent_modes", "contract_graph", "workstreams", "evidence_grounded_finding",
        }:
            raise KeyError(f"Unknown shared-state section: {section}")
        self.data[section] = deepcopy(value)

    def message(self, sender: str, recipient: str, message_type: str,
                status: str, **payload: Any) -> None:
        self.data["agent_messages"].append({
            "from": sender, "to": recipient, "type": message_type,
            "status": status, **deepcopy(payload),
        })

    def record_agent(self, agent: str, status: str, iteration: int = 0,
                     consumes: list[str] | None = None,
                     produces: list[str] | None = None) -> None:
        self.data["agent_status"][agent] = {
            "status": status, "iteration": iteration,
            "consumes": consumes or [], "produces": produces or [],
        }

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.data)


class ExecutionBudget:
    """Enforces a hard upper bound on orchestrated agent/API call slots."""

    def __init__(self, max_calls: int, max_iterations: int):
        self.max_calls = max(0, int(max_calls))
        self.max_iterations = max(0, int(max_iterations))
        self.calls_used = 0
        self.iterations_used = 0
        self.stop_reason: str | None = None

    def reserve_call(self, label: str) -> bool:
        if self.calls_used >= self.max_calls:
            self.stop_reason = "api_call_limit_reached"
            return False
        self.calls_used += 1
        return True

    def begin_iteration(self) -> bool:
        if self.iterations_used >= self.max_iterations:
            self.stop_reason = "iteration_limit_reached"
            return False
        self.iterations_used += 1
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "calls_used": self.calls_used,
            "remaining_calls": max(0, self.max_calls - self.calls_used),
            "max_iterations": self.max_iterations,
            "iterations_used": self.iterations_used,
            "stop_reason": self.stop_reason,
        }


def _gap_key(gap: Any) -> str:
    """Return a stable comparable representation for a gap item."""
    if isinstance(gap, str):
        return gap.strip()
    if isinstance(gap, dict):
        for key in ("id", "question", "description", "gap"):
            if gap.get(key):
                return str(gap[key]).strip()
    return repr(gap)


def _preserve_unresolved_gaps(
    previous: dict[str, Any], current: dict[str, Any]
) -> list[Any]:
    """Carry gaps forward unless the verifier explicitly marks them resolved.

    Omitting a gap from a later response is not proof its underlying fact was
    found. A follow-up must list resolved_evidence_gaps to close an old gap.
    """
    combined: list[Any] = []
    seen: set[str] = set()
    for gap in list(previous.get("evidence_gaps", []) or []) + list(current.get("evidence_gaps", []) or []):
        key = _gap_key(gap)
        if key and key not in seen:
            combined.append(deepcopy(gap))
            seen.add(key)
    resolved = {
        _gap_key(gap)
        for gap in (current.get("resolved_evidence_gaps", []) or [])
        if _gap_key(gap)
    }
    return [gap for gap in combined if _gap_key(gap) not in resolved]


def needs_follow_up(verification: dict[str, Any]) -> bool:
    """True when verification is incomplete or asks for further evidence."""
    return bool(
        verification.get("status") in {"unverified", "verified_with_limitations", "complete_with_gaps"}
        or verification.get("citation_checks_passed") is False
        or verification.get("evidence_gaps")
        or verification.get("recommended_follow_up")
    )


def run_bounded_follow_up(
    finding: dict[str, Any],
    verification: dict[str, Any],
    max_iterations: int,
    budget: ExecutionBudget,
    targeted_follow_up: Callable[[dict[str, Any], dict[str, Any], int], tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Retry only targeted analysis, never exceed either configured limit."""
    trace: list[dict[str, Any]] = []
    current_finding, current_verification = finding, verification
    for _ in range(max(0, int(max_iterations))):
        if not needs_follow_up(current_verification):
            budget.stop_reason = budget.stop_reason or "verification_satisfied"
            break
        if not budget.begin_iteration():
            break
        iteration = budget.iterations_used
        trace.append({
            "iteration": iteration,
            "trigger": "verification_gap",
            "gaps": deepcopy(current_verification.get("evidence_gaps", [])),
            "follow_up": "targeted_reanalysis",
        })
        if not budget.reserve_call("targeted_follow_up"):
            break
        previous_verification = current_verification
        current_finding, current_verification = targeted_follow_up(
            current_finding, previous_verification, iteration
        )
        # Never infer resolution from omission. Only explicit verifier resolution
        # can close a gap; otherwise preserve it across targeted re-analysis.
        current_verification = deepcopy(current_verification)
        current_verification["evidence_gaps"] = _preserve_unresolved_gaps(
            previous_verification, current_verification
        )
        trace[-1]["remaining_gaps"] = deepcopy(current_verification["evidence_gaps"])
        trace[-1]["verification_status"] = current_verification.get("status", "unknown")
        trace[-1]["resolved_gaps"] = deepcopy(current_verification.get("resolved_evidence_gaps", []))
        if not needs_follow_up(current_verification):
            budget.stop_reason = budget.stop_reason or "verification_satisfied"
            break
    if needs_follow_up(current_verification) and not budget.stop_reason:
        budget.stop_reason = "iteration_limit_reached"
    return current_finding, current_verification, {
        "iterations": trace,
        "iterations_used": budget.iterations_used,
        "max_iterations": budget.max_iterations,
        "stop_reason": budget.stop_reason or "completed",
        "needs_human_follow_up": needs_follow_up(current_verification),
        "remaining_gaps": deepcopy(current_verification.get("evidence_gaps", [])),
        "verification_status": current_verification.get("status", "unknown"),
    }
