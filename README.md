# Odin — The Contract War Room

Evidence-grounded multi-agent contract intelligence prototype for the fictional Quillhub dataset in RAGNAROK Problem Statement 2.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.app:app --reload
```

Open http://127.0.0.1:8000.

Add your own Anthropic API key to local `.env` to enable Claude for Thor and Loki. Never commit `.env`; the browser never receives the key. Without a key, the first vertical slice runs in deterministic demo mode.

## Current vertical slice

- Load canonical contract text and event feeds.
- Thor extracts A1 terms with exact citations.
- Citation gate validates quotes against source text.
- Norns computes A1 dates from the simulated clock.
- Loki identifies an evidence-limited incident-notice risk.
- Heimdall checks it against E-04.
- Tyr records a reasoned ruling and drafts a human-approval-only evidence request.
- FastAPI endpoints and a responsive dashboard expose the run trace.

This is a first vertical slice, not a claim that all contracts and cross-contract requirements are complete. The supplied fictional data's `.txt` files are canonical citation anchors.