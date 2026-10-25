# Odin — The Contract War Room

A hackathon prototype for evidence-grounded multi-agent contract intelligence, built against the fictional Quillhub dataset from RAGNAROK Problem Statement 2.

## What currently works

- Loads the supplied canonical `.txt` contract sources, company context, ledger, holidays, clock, and JSONL event drops.
- Preserves malformed JSONL records as parse errors rather than aborting a whole drop.
- Runs an A1-only vertical slice through Odin, Thor, Norns, Loki, Heimdall, and Tyr.
- Verifies every displayed citation against the exact source text.
- Produces a simulated timeline, a bounded risk finding, event verification, a reasoned ruling, and a human-approval-only draft action.
- Includes a responsive dashboard, health endpoint, pack summary endpoint, and selected simulated date.
- Uses deterministic fallback behavior without an API key. Thor and Loki can call Claude when configured.

**This is intentionally the first vertical slice, not yet the complete portfolio implementation.** It does not claim to have fully analyzed A2, A3, B1, B2, C1, D1, and STD or resolved every cross-contract relationship.

## Quick start (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Optional: edit .env and set ANTHROPIC_API_KEY to your own key.
uvicorn backend.app:app --reload
```

Open http://127.0.0.1:8000. API checks:

- `GET /api/health`
- `GET /api/pack`
- `GET /api/run?as_of=2027-03-15&use_claude=false`

## Data / citation policy

The supplied `.txt` files are canonical citation anchors. A citation must include document ID, clause reference, and an exact quote. Unverified quotes must not be treated as evidence. The supplied data is fictional. Draft actions are never sent automatically.

## Development roadmap

1. Complete Thor extraction and quote validation across every contract, including incorporated STD terms.
2. Add Norns' full obligation/payment ledger reconciliation and checkpoint recalculation.
3. Add Loki/Heimdall cross-contract claims and event mapping across both drops.
4. Add Tyr dispute workflow and action approvals with explicit state transitions and bounded iterations.
5. Persist run state and event ingestion IDs, then implement portfolio graph, exposure heatmap, and time-slider updates.
6. Expand tests for malformed inputs, failed API calls, citation mismatch, date calculations, and budget exhaustion.

## Project layout

- `odin_dev_pack/`: supplied source pack, with PDF twins omitted to keep the repository smaller; canonical `.txt` sources are retained.
- `backend/agents/`: separate agent responsibilities.
- `backend/services/`: ingestion and citation verification.
- `backend/orchestrator.py`: bounded state-machine orchestration.
- `frontend/index.html`: single-page command-center UI.
- `tests/`: automated checks.
