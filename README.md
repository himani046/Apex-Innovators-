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
4. Expand Tyr dispute workflow and approval transitions across all contract workstreams.
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


## Phase 3 — Portfolio operations

Phase 3 adds an explicit-date portfolio timeline and an evidence-led payment-event reconciliation view.

- Classifies source-grounded dates by context: explicit action deadlines, historical/effective/reference dates, contract-term milestones, relative notice terms, and unclassified dates. Only explicitly worded action deadlines can be marked overdue.
- Reads the supplied `payments_ledger.csv` as well as invoice, payment, remittance, refund, credit, and billing signals from loaded event drops; future-dated rows are excluded for the selected simulated date.
- Links a ledger candidate to a contract only when the event text explicitly names exactly one known contract/document ID; otherwise it remains unlinked for review.
- Keeps contract-stated amounts separate from transaction candidates. It does not sum contract rates, caps, recurring fees, or candidate events into a portfolio exposure total.
- Preserves event source, timestamp, text evidence, extracted amount strings, match status, and unresolved reconciliation questions.
- The dashboard displays the normalized timeline and payment-ledger candidates alongside the existing six workstreams.

**Limitations:** These are operational triage candidates, not accounting entries, confirmed liabilities, or legal conclusions. Reconciliation requires a contract-linked invoice/credit, applicable trigger and period, and payment/dispute status. Relative deadlines are not converted into dates without a supported trigger date. Human review remains required.


## Phase 4 — Agentic collaboration and shared state

Phase 4 now adds structured collaboration around the existing portfolio workflow, alongside the evidence-grounded decision queue.

- **Shared state:** each run emits a JSON-serializable `shared_state` with schema version and sections for contract relationships, extracted clauses, timeline events, financial candidates/calculations, risk claims, evidence references, verification outcomes, unresolved questions, recommended actions, agent status, and handoff messages.
- **Agent handoffs:** Odin coordinates the run; Thor's evidence is consumed downstream by Norns/Loki; Loki's claims and citations are passed to Heimdall; Heimdall's verification outcome and gaps are passed to Tyr; Odin returns the consolidated state, decision queue, ruling, and unresolved questions.
- **Bounded follow-up:** missing proof or failed verification can trigger targeted deterministic re-analysis. The loop stops when verification no longer requests follow-up or when `MAX_AGENT_ITERATIONS` is reached. A missing external record remains unresolved; retries never manufacture evidence.
- **Execution budget:** `MAX_AGENT_CALLS` limits orchestrated agent/task invocation slots, and `MAX_AGENT_ITERATIONS` caps feedback iterations. The API response reports configured and used budgets plus the stop reason. Provider-internal retries are not observable by this counter.
- **Auditability:** `collaboration` exposes loop status, agent status/read/write metadata, handoff count, unresolved questions, and recommended actions. The dashboard renders these fields.
- **Safety:** recommendations remain drafts requiring human approval. No legal breach, damages, or aggregate financial exposure is inferred without supporting evidence.

The run's shared state is in-memory and returned with the API response; it is not a persistent database across runs. The current A1 risk workflow demonstrates the verification-feedback pattern, while broader cross-contract legal interpretation and fully reconciled financial exposure remain staged work.

Run the test suite after pulling updates:

```powershell
python -m unittest discover -s tests -v
```


## Phase 5 — Evidence-grounded risk and decisions

Phase 5 adds a normalized `evidence_grounded_finding` to each API run and exposes it in the dashboard.

- **Structured finding:** finding ID, contract ID, claim, severity, supporting evidence, missing evidence, status, recommended action, and human-review requirement.
- **Exact quote validation:** contract quotations are checked against the named canonical contract source; the E-04 event quotation is checked against the exact event-feed body. The API reports the validation result and note for each evidence item.
- **Facts vs. interpretation:** the dashboard separates what the event record supports from the interpretation that notification compliance remains uncertain.
- **No unsupported breach conclusion:** the A1 finding remains `partially_supported` while provider-awareness and notice-delivery evidence are missing; `breach_proven` remains false.
- **Uncertainty and conflicts:** missing evidence and verification challenges are explicit. Conflicting evidence is recorded only when a source-backed conflict is supplied; an absence of evidence is not mislabeled as a contradiction.
- **Decision transparency:** the dashboard shows remaining gaps, loop stop reason, iteration/call budget, recommended next action, and its approval status.
- **Approval gate:** consequential actions remain draft-only and are never sent automatically. The dashboard communicates the approval requirement; it does not silently approve or dispatch the action.

The Phase 5 finding is a review artifact, not a legal conclusion. The A1 scenario still supports an unplanned 190-minute outage, but does not establish provider-awareness time or delivery time for the required Operations notice.

Regression tests: `python -m unittest tests.test_evidence_grounding -v` and the full suite with `python -m unittest discover -s tests -v`.


## Phase 6 — Executive dashboard and portfolio command center

Phase 6 expands the single-page dashboard into a portfolio-level view using the current `/api/run` response.

- **Portfolio overview:** counts source documents and distinct contracts represented in workstreams, summarizes high-priority triage signals and timeline items, and reports unresolved relationship/reconciliation review items.
- **Contract explorer:** lists loaded source documents, extracted term counts, verified quote counts, detected relationships, and candidate obligations. Expand a document to inspect available source terms; use the jump control to navigate to the workstream detail.
- **Portfolio timeline:** continues to show explicit normalized dates and operational milestones, including deadlines, payment candidates, and dates that require classification review.
- **Risk heatmap:** groups workstream risk signals by contract/workstream and their reported severity/priority, with verification and open-question context.
- **Agent activity:** retains agent status, messages, handoffs, bounded follow-up, stop reason, and execution-budget information.
- **Decision/evidence panel:** retains the Phase 5 finding, source quotations, missing evidence, interpretation, and human-approval-only recommended action.
- **Event/audit timeline:** combines returned portfolio milestones, current-run agent messages, finding status, and follow-up loop outcome.

**Interpretation safeguards:** dashboard counts are triage summaries and may overlap (for example, a risk signal can also appear in the decision queue). Potential exposure is deliberately displayed as not calculated unless the source data and reconciliation logic support a defensible figure. Relationship edges and risk signals are not treated as proven legal conflicts or breaches.

**Scope limitation:** the event/audit timeline is based on the current API run and is not a persistent cross-run audit database. The contract explorer shows available extracted terms and relationships, not a guarantee that every obligation or incorporated document has been identified. Dates and financial items remain subject to the existing source-grounding and human-review safeguards.


## Phase 7 — Persistent audit trail and decision governance

Phase 7 adds a SQLite-backed audit trail. The default database is `data/odin_audit.sqlite3`; set `ODIN_AUDIT_DB` to choose a different persistent path. Runtime database files are excluded from Git.

- **Run snapshots:** every successful `GET /api/run` response is stored with run ID, simulated date, status, a source/input fingerprint, and the complete response payload. Repeated runs are stored separately.
- **Finding history:** material finding snapshots are tracked by finding ID. A changed claim/status/severity/evidence snapshot emits a `finding_changed` event containing previous and current values.
- **Evidence provenance:** exact quote, source document ID, clause reference, verification result, and verification note are recorded as provenance events. Remaining verification gaps are captured separately.
- **Agent/audit events:** the store records run completion, agent messages, finding creation/changes, evidence provenance, remaining gaps, and reviewer decisions with UTC timestamps.
- **Human review:** `POST /api/audit/runs/{run_id}/decision` records an explicit `approved` or `rejected` decision with reviewer, note, and timestamp. The endpoint does not send or execute the draft action.
- **Audit explorer:** the dashboard lists saved runs and lets a reviewer inspect a run's event history and recorded decisions.

Audit API:
- `GET /api/audit/runs?limit=20`
- `GET /api/audit/runs/{run_id}`
- `POST /api/audit/runs/{run_id}/decision` with JSON such as `{"action_id":"recommended-action","decision":"approved","reviewer":"Contract Counsel","note":"Reviewed the draft."}`

**Operational/security notes:** SQLite is suitable for the current single-instance prototype. Configure a durable writable volume and set `ODIN_AUDIT_DB` in deployments where filesystem persistence is not guaranteed. This prototype records the reviewer identity as supplied by the caller; it does not authenticate that identity or provide tamper-proof/WORM storage. Do not treat the approval record as an electronic signature or permission to dispatch the action. A recorded approval/rejection never executes a consequential action.
