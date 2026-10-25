"""Per-run LLM accounting, response caching, and hard token budget enforcement."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from typing import Any

_ACTIVE: ContextVar[dict[str, Any] | None] = ContextVar("odin_llm_run", default=None)


def _key(system: str, prompt: str, max_tokens: int, model: str) -> str:
    raw = json.dumps([model, system, prompt, int(max_tokens)], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@contextmanager
def llm_run_context(max_tokens: int):
    state = {
        "max_tokens": max(0, int(max_tokens)), "tokens_used": 0,
        "input_tokens": 0, "output_tokens": 0, "provider_calls": 0,
        "cache_hits": 0, "budget_blocked": 0, "cache": {},
    }
    token = _ACTIVE.set(state)
    try:
        yield state
    finally:
        _ACTIVE.reset(token)


def cached_response(system: str, prompt: str, max_tokens: int, model: str):
    state = _ACTIVE.get()
    if state is None:
        return None
    key = _key(system, prompt, max_tokens, model)
    if key in state["cache"]:
        state["cache_hits"] += 1
        return state["cache"][key]
    return None


def store_response(system: str, prompt: str, max_tokens: int, model: str, text: str, usage: dict):
    state = _ACTIVE.get()
    if state is None:
        return
    key = _key(system, prompt, max_tokens, model)
    state["cache"][key] = text
    state["provider_calls"] += 1
    input_tokens = max(0, int(usage.get("input_tokens", 0) or 0))
    output_tokens = max(0, int(usage.get("output_tokens", 0) or 0))
    state["input_tokens"] += input_tokens
    state["output_tokens"] += output_tokens
    state["tokens_used"] += input_tokens + output_tokens


def ensure_token_budget():
    state = _ACTIVE.get()
    if state is None:
        return
    if state["tokens_used"] >= state["max_tokens"]:
        state["budget_blocked"] += 1
        raise RuntimeError("Odin per-run LLM token budget exhausted")


def usage_snapshot(state: dict | None) -> dict:
    if not state:
        return {"max_tokens": 0, "tokens_used": 0, "input_tokens": 0, "output_tokens": 0,
                "provider_calls": 0, "cache_hits": 0, "budget_blocked": 0}
    return {key: value for key, value in state.items() if key != "cache"}
