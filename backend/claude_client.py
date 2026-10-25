import os
from functools import lru_cache

from backend.config import MODEL
from backend.services.llm_runtime import (
    cached_response,
    ensure_token_budget,
    reserve_provider_call,
    store_response,
)


@lru_cache(maxsize=1)
def client():
    import anthropic
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    return anthropic.Anthropic(api_key=key, max_retries=0, timeout=45.0)


def ask_claude(system_prompt, user_prompt, max_tokens=1400):
    """Call Claude with run-scoped caching and enforced token/provider-call budgets."""
    requested_tokens = max(1, int(max_tokens))
    cached = cached_response(system_prompt, user_prompt, requested_tokens, MODEL)
    if cached is not None:
        return cached

    ensure_token_budget()
    # Clamp output budget to the remaining per-run token allowance.
    from backend.services.llm_runtime import _ACTIVE
    run = _ACTIVE.get()
    if run is not None:
        remaining = max(0, run["max_tokens"] - run["tokens_used"])
        if remaining <= 0:
            ensure_token_budget()
        requested_tokens = min(requested_tokens, remaining)

    # Reserve before the network request so failed calls and retries cannot
    # silently escape the configured provider-call budget.
    reserve_provider_call()
    response = client().messages.create(
        model=MODEL,
        max_tokens=requested_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "\n".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )
    usage = {
        "input_tokens": getattr(getattr(response, "usage", None), "input_tokens", 0),
        "output_tokens": getattr(getattr(response, "usage", None), "output_tokens", 0),
    }
    store_response(system_prompt, user_prompt, max_tokens, MODEL, text, usage)
    return text
