# Odin — The Contract War Room

An evidence-grounded multi-agent contract intelligence prototype for the fictional Quillhub dataset in RAGNAROK Problem Statement 2.

## Quick start (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Optional: add your Anthropic API key to local .env
uvicorn backend.app:app --reload
```

Open http://127.0.0.1:8000.

## First end-to-end vertical slice

- Load the supplied canonical contract text, company context, ledger, holidays, clock, and both JSONL event drops.
- Thor extracts key terms from A1 and attaches exact source quotes.
- Citation verification checks that quotes exist verbatim in A1.txt.
- Norns computes a term timeline for the selected simulated date.
- Loki raises an evidence-limited risk about the March 3 outage notice timeline.
- Heimdall verifies what E-04 supports and what it does not establish.
- Tyr records a reasoned ruling and drafts a human-approval-only evidence request.
- The dashboard shows the risk, citations, timeline, action, and agent transition trace.

This is the first vertical slice, not yet a complete analysis of every contract and cross-contract relationship. The incorporated A2, A3 and STD terms need to be reconciled before the portfolio can be treated as fully analyzed.

## API endpoints

- GET /api/health
- GET /api/pack
- GET /api/run?as_of=2027-03-15&use_claude=false

## Claude API setup

The API key belongs in local .env only. Never commit it and never expose it in frontend code. The frontend calls FastAPI; only the backend can access Claude. Without a key, the first slice runs using deterministic fallbacks. Thor and Loki can use Claude when configured.

Confirm that the model in CLAUDE_MODEL is available in your Anthropic API account. The sample is a configurable default, not a guarantee of account access. MAX_AGENT_CALLS and MAX_AGENT_ITERATIONS are exposed as configuration for the next workflow iterations.

## Evidence standard

The supplied .txt files are the canonical citation anchors. Every risk claim should include document ID, clause reference and a verbatim quote. Quotes not found in source text must be marked unverified. Facts must be distinguished from analysis, and draft actions are never sent automatically.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Roadmap

1. Complete Thor extraction across all contract documents and incorporated terms.
2. Implement ledger reconciliation, obligations and financial projections in Norns.
3. Expand Loki/Heimdall cross-contract analysis and event mapping to both drops.
4. Add persisted run state, bounded clarification loops, and Tyr dispute management.
5. Complete the contract graph, exposure views and checkpoint-aware dashboard.
