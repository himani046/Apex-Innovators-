# Odin — The Contract War Room

A hackathon prototype for evidence-grounded multi-agent contract intelligence, built against the fictional Quillhub dataset from RAGNAROK Problem Statement 2.

## What currently works

- Loads the supplied canonical `.txt` contract sources, company context, ledger, holidays, clock, and JSONL event drops.
- Preserves malformed JSONL records as parse errors rather than aborting a whole drop.
- Runs an A1-focused vertical slice through Odin, Norns, Loki, Heimdall, and Tyr.
- Runs Thor's first portfolio-wide triage pass across every loaded contract, extracting potentially relevant source lines with exact-quote citations and review flags.
- Shows portfolio-scan counts and sample evidence in the dashboard; this is keyword-based triage, not final legal interpretation.
- Builds independent workstreams for A1 and its dependencies, B1, B2, C1, and D1, plus a portfolio-wide shared-risk review.
- Extracts explicit calendar dates and source-stated financial amounts per workstream, with verbatim evidence; relative deadlines and aggregate exposure are not guessed.
- Surfaces potential cross-contract exclusivity overlap as a human-review signal, not a proven legal conflict.
- Verifies workstream candidate citations against the exact source text.
- Produces a simulated timeline, a bounded risk finding, event verification, a reasoned ruling, and a human-approval-only draft action.
- Includes a responsive dashboard, health endpoint, pack summary endpoint, and selected simulated date.
- Uses deterministic fallback behavior without an API key. Thor and Loki can call Claude when configured.

**Phase 1 and Phase 2 are implemented as evidence-grounded triage, not complete legal analysis.** The graph links documents using explicit identifiers and relationship language. The reconciliation layer resolves only the specifically detected non-renewal amendment; other amendment sections are flagged for human review. Phase 2 creates source-specific workstreams for A1 (including dependency documents A2/A3/STD), B1, B2, C1, and D1, plus a portfolio-wide workstream. Candidate terms and risks require human review; financial amounts are not summed without invoice and trigger evidence.

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
5. Persist run state and event ingestion IDs, then implement an exposure heatmap and richer time-slider updates.
6. Reconcile invoices, payment ledger, event drops, and contract-specific trigger dates before calculating realized exposure.
7. Expand tests for malformed inputs, failed API calls, citation mismatch, date calculations, and budget exhaustion.

## Project layout

- `odin_dev_pack/`: supplied source pack, with PDF twins omitted to keep the repository smaller; canonical `.txt` sources are retained.
- `backend/agents/`: separate agent responsibilities.
- `backend/services/`: ingestion and citation verification.
- `backend/orchestrator.py`: bounded state-machine orchestration.
- `frontend/index.html`: single-page command-center UI.
- `tests/`: automated checks.

## Upload a contract (PDF or TXT)

The dashboard accepts a single `.pdf` or `.txt` file (up to 15 MB) through **Upload a contract**. PDF text extraction uses `pypdf`; TXT is decoded as UTF-8 with a Windows-1252 fallback. The upload response includes the original filename, format, page count when available, SHA-256 fingerprint, extracted terms, and exact-quote validation against the uploaded document text. Scanned/image-only PDFs return a clear OCR-required message rather than silently producing empty evidence.

Install the upload dependencies and start the app:

```bash
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

The `POST /api/analyze-upload` endpoint currently provides document-level extraction and citation checks. It does not yet reconcile an uploaded file against every contract, event drop, or the payment ledger. Treat output as evidence triage, not legal advice. Uploading both PDF and TXT copies is not required; different SHA-256 hashes do not necessarily mean different contract text.
