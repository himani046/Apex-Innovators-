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
- **FR4 · Loki adversarial review:** scans clauses for ambiguity, unilateral discretion, one-sided remedies, broad indemnity, renewal, termination, payment/penalty, notice, performance, security, confidentiality, force-majeure, and compliance risks; records exact source-line citations, an attack path, severity rationale, and qualitative likelihood rationale.
- Cross-contract candidates now include Loki's counterparty-side challenge, alternative explanations, scope/amendment/precedence checks, and targeted Thor clarification requests when citations or amendment context are weak. Likelihood labels are qualitative triage—not calibrated probabilities—and no conflict or breach is automatically determined.
- **FR5 · Heimdall event monitoring:** maps supplied event-feed items to contract candidates and clause families, verifies Loki citations against canonical source text, records whether event evidence supports or challenges a claim, and reports evidence gaps. Severity-rated deadline/event alerts prioritize near-term obligations and material incident language; duplicate and low-signal alerts are filtered. Event authenticity, contractual trigger, breach, and realized exposure are never inferred from a keyword match alone.
- **FR6 · Tyr arbitration and action drafting:** produces a per-finding ruling that reconciles Loki's claim with Heimdall's citation checks, supporting/challenging evidence, event candidates, and unresolved gaps. Rulings carry a rationale and confidence level. Action drafts cover renewal/non-renewal, termination/cure, potential breach/incident notices, amendment proposals, and internal escalation memos. Each draft contains exact clause quotations and verification status, stable action IDs, evidence gaps, placeholders for facts requiring confirmation, and a mandatory pending-human-approval state. Unverified citations are explicitly blocked; drafts are never sent automatically, and an approval record does not execute a consequential action. These are evidence-qualified workflow outputs, not legal advice or a determination of breach.


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

## Implementation handoff

Before starting a Claude-enabled implementation session, use [`docs/CLAUDE_IMPLEMENTATION_HANDOFF.md`](docs/CLAUDE_IMPLEMENTATION_HANDOFF.md). It records the current code-path audit, FR/NFR status, prioritized work, token-budget rules, and local prerequisites. Repository preparation does not run tests or invoke the Claude API; configure secrets only in the local `.env` file.

## Development roadmap

1. Complete Thor extraction and quote validation across every contract, including incorporated STD terms.
2. Complete Norns obligation/payment reconciliation and checkpoint recalculation with source-backed trigger dates.
3. Expand Loki/Heimdall semantic conflict review and event-to-clause mapping across every workstream.
4. Extend Tyr dispute and human-approval transitions to all contract workstreams; consequential actions remain draft-only.
5. Reconcile invoices, ledger entries, event records, and contractual trigger dates before calculating realized exposure.
6. Add a full browser/API acceptance suite and real-provider smoke tests; unit-test success alone is not end-to-end proof.
7. Expand malformed-input, failed-provider, citation-mismatch, date-calculation, and budget-exhaustion tests.

### Recent completion increment

- Targeted re-extraction can be attached to an existing audit run by supplying `run_id` to `POST /api/reextract`.
- The updated shared-state snapshot and re-extraction history are written back to the saved run, and a `targeted_reextraction` event records the actor, contract, clause reference, result count, and status.
- Missing section references return an explicit no-match result without a whole-document fallback. Source line numbers remain anchored to the original document.
- Portfolio draft actions receive stable IDs so a reviewer can approve or reject one action at a time; decisions remain records only and never dispatch an action.
- Calls without `run_id` remain compatible, but explicitly report that the returned state is not durable. Missing run IDs return `404`.
- Regression tests cover targeted extraction, persistent state updates, and action-specific decisions.

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

Phase 7 regression test: `python -m unittest tests.test_audit_store -v`.


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


## Phase 8 — Production hardening (first increment)

Phase 8 begins adding explicit API controls and safer request handling. This is an incremental hardening layer, not a claim that the prototype is production-certified.

- **Optional bearer-token gate:** set `ODIN_API_TOKEN` to require a matching `Authorization: Bearer <token>` header for audit history reads, reviewer decisions, and contract uploads. The dashboard has a token field; the value is held in the current browser tab's session storage.
- **Fail-closed production configuration:** set `ODIN_ENV=production`. If no `ODIN_API_TOKEN` is configured, protected endpoints return HTTP 503 rather than silently allowing anonymous access.
- **Request validation:** human decisions use a strict schema; unsupported fields and invalid decision values are rejected. Reviewer and note lengths are bounded.
- **Upload bounds:** uploaded content is capped at 15 MiB at the API boundary.
- **Response hardening:** common security headers are added, API responses are not cached, and server exception details are not returned to clients.
- **Regression coverage:** `python -m unittest tests.test_security -v` checks local, production-misconfiguration, and bearer-token behavior.

### Configure local / deployed environments

Copy `.env.example` to `.env` for local use. For a protected review workflow, set a long random `ODIN_API_TOKEN` value. For a production deployment, set both `ODIN_ENV=production` and `ODIN_API_TOKEN`; configure them as deployment secrets, never commit the real token, and restart the service. Paste the same token into the dashboard's API access token field. Requests to `/api/health` remain public so health checks can work.

### Important limits still open

The bearer token is a **shared access secret**, not individual reviewer authentication, roles, SSO, or per-reviewer attribution verified by an identity provider. Audit history is SQLite-backed but not yet cryptographically tamper-evident or WORM storage. Production deployment still needs durable-volume verification, TLS/reverse-proxy configuration, rate limiting, operational secret rotation, and a full security review. Do not expose this prototype to public or sensitive contract data until those controls are addressed.

## Phase 9 — Light-themed tabbed contract workspace

The dashboard has been redesigned around a light, sage-and-neutral visual system inspired by the supplied reference. Navigation is tab-based rather than a long vertically stacked dashboard.

- **Overview:** portfolio health cards, contract count, review queue, deadline preview, and a compact relationship graph.
- **Contracts:** contract cards open a detail modal with linked relationships, extracted terms and citations, deadlines, and associated review findings.
- **Relations:** interactive SVG graph. Select a contract node to open its profile or a relationship edge to inspect the link and potential downstream impact. Relationship effects remain review candidates unless supported by the contract evidence.
- **Time machine:** monthly calendar with dated milestones and a selected-day view, plus the next deadlines list.
- **Agents:** workstream/agent status, evidence findings, agent message trace and unresolved questions.
- **Settings and authority reminders:** save a contact email per contract, select a reminder cadence (30/14/7/1, 14/7/3/1, or 7/3/1 days), and prepare a mailto draft for a selected deadline. Contact settings are browser-local.

**Important limitation:** reminder cadence is currently configuration and draft preparation only. The prototype does not run a background scheduler or automatically email authorities. Before automated delivery is enabled, add a server-side scheduler, verified authority/contract recipient mapping, provider credentials stored as secrets, notice-rule validation, duplicate-send protection, delivery/bounce logs, audit events, and a human approval gate. Do not email an authority based only on a keyword-extracted date or an unverified recipient.


## Phase 10 — Configurable portfolio intake and FR8 synthesis

This increment adds a multi-contract intake path and structured report synthesis.

- **Configurable input:** `POST /api/analyze-portfolio` accepts company context, up to 50 contract text records, optional event records, and a simulated date. Combined contract text is limited to 15 MiB. The dashboard can read multiple TXT files and submit them together.
- **Clause re-extraction:** `POST /api/reextract` accepts a contract ID, source text, optional clause reference, and a shared-state snapshot. It returns targeted terms and the updated state snapshot. The caller must persist the returned snapshot if durable continuity is needed.
- **Broader Thor categories:** extraction triage includes party labels, duration, renewal, payment schedule, obligations, penalties, compliance, notice, liability, incident, termination, confidentiality, and dispute/law keywords. It adds heuristic ambiguity and missing-category flags.
- **FR8 contract reports:** the fixed-pack run now returns `synthesis.contract_reports`, one report per extracted contract, with source terms, obligations, timeline candidates, risks, citations, confidence where available, unresolved questions, and recommended actions.
- **FR8 company report:** `synthesis.company_risk_report` summarizes cross-contract relationships, amendment review items, prioritized actions, timeline projections, references, and unresolved questions.
- **Evidence graph:** the custom-input path returns contract, clause-candidate, and explicitly labeled party nodes when source labels exist. Edges carry evidence references where available.
- **Draft actions:** the custom path prepares category-specific review drafts for renewal, termination, penalty, notice, liability, and other candidate clauses. Drafts are not sent automatically.
- **Audit fingerprint:** custom portfolio source identity is included in run fingerprinting.

### Current acceptance-test boundary

The custom-input path now runs a bounded per-contract Thor → Norns → Loki → Heimdall → Tyr workflow with targeted clarification, explicit stopping reasons, and human-review gates. It is still deterministic by default; optional Claude-assisted review is opt-in and only runs when `ANTHROPIC_API_KEY` is configured. Model-proposed quotations are validated against source text before inclusion.

The fixed-pack demo also exposes generalized bounded workflow traces and cross-contract candidate findings. Cross-contract differences are still **review candidates**, not semantic/legal conflict conclusions. Event records are normalized and future/malformed records are handled explicitly. Invoice/payment records can be linked structurally by contract and invoice ID, but their authenticity and contractual trigger are not independently established; financial exposure remains uncalculated unless supported reconciliation evidence is available. The graph is an evidence-linked visualization, not a full WebGL 3D engine. GitHub Actions validate Python compilation/unit tests and inline dashboard JavaScript syntax. A full browser/API end-to-end acceptance test and real-provider smoke test still remain; CI success does not prove every FR is complete.

See [docs/TECHNICAL_IMPLEMENTATION_GUIDE.md](docs/TECHNICAL_IMPLEMENTATION_GUIDE.md) for the stack, architecture, API, FR/NFR status, safety constraints, and remaining work.

## Phase 11 — Bounded agent collaboration, cross-contract review, and reconciliation

- **Bounded workflow:** per-contract agent stages record messages, iterations, budget usage, stop reasons, unresolved evidence, and human-review status. A budget-exhausted workstream is not reported as complete.
- **Optional LLM agents:** Thor can add exact-quote-validated extraction candidates; Loki can suggest adversarial risk candidates; Heimdall can suggest event-evidence challenges; Tyr can add a qualified rationale and draft suggestions. This is opt-in, requires a configured provider key, counts calls against a budget, and never sends actions automatically.
- **Cross-contract candidates:** differing numeric terms, opposing modal language, exclusivity wording, and amendment/precedence signals create graph/report candidates with citations to both sources. Party, scope, precedence, incorporated terms, and legal effect remain explicit review questions.
- **Event normalization:** records with missing bodies or invalid timestamps are rejected; future records are excluded from a simulated-date run. Supplied event authenticity is not independently verified.
- **Durable event feed:** `POST /api/events/ingest` persists source-labeled event records in SQLite with idempotent source/event IDs; `GET /api/events?as_of=YYYY-MM-DD` lists the stored feed and excludes future-dated events for that simulated date. The dashboard includes a **Store event feed** control. Stored records remain explicitly unverified.
- **Invoice/payment candidate matching:** structured invoice IDs, contract IDs, event kinds, and amounts can be grouped for reconciliation. Structural linkage is not treated as proof of payment, outstanding liability, or financial exposure.
- **Dashboard and CI:** both the custom portfolio panel and fixed-pack synthesis surface bounded-workflow status, cross-contract evidence, and reconciliation counts. CI now syntax-checks the inline JavaScript in addition to compiling Python and running unit tests.
- **Remaining limits:** a real external event connector and authenticated event provenance, semantic legal reasoning over all amendments/precedence rules, invoice-to-ledger/contract trigger reconciliation, and full browser/API end-to-end acceptance are still required before production use.


## FR7 — Agent workflow, feedback loops, and termination

- **Loki → Thor clarification:** when the evidence/citation review remains below the configured citation-verification threshold, Loki emits a structured, contract-scoped re-extraction request listing the open questions and requested source context. Thor returns a targeted extraction result; re-reading the same source is explicitly not treated as new external evidence.
- **Loki ↔ Heimdall disagreement:** Heimdall's per-finding support, challenges, citation checks, event associations, and evidence gaps are passed to Tyr. The collaboration trace records an explicit `evidence_disagreement` / `revised_evidence_disagreement` handoff and Tyr's qualified ruling. Disagreement is not silently converted into proof of breach.
- **Bounded feedback:** `MAX_AGENT_ITERATIONS` controls follow-up passes (supported range: 0–3). `MAX_PORTFOLIO_AGENT_CALLS` is a hard cap for the generalized portfolio workflow. A workstream that cannot fit its required initial tasks is marked `not_run_budget_exhausted`; it is not reported as completed.
- **Evidence-based stop:** `CITATION_VERIFICATION_THRESHOLD` (default `0.75`) controls when the workflow stops repeating source-only passes because enough citations are verified. Open event/trigger facts remain explicit review questions; a repeated read cannot manufacture external evidence. The loop also stops when there are no remaining gaps, the iteration limit is reached, or the call budget would be exceeded.
- **Traceability:** each workstream reports iteration count, requested and remaining gaps, citation-verification ratio where applicable, stop reason, agent messages, and whether human review remains required.
- **Safety:** Tyr's rulings and action drafts remain qualified assessments requiring human approval. No notices are sent and no consequential contract action is executed automatically.

Configure these values in your local `.env` file (never commit secrets). Regression tests for FR7 are in `tests/test_fr7_workflow.py`; run them and then the full suite after pulling:
```bash
python -m unittest tests.test_fr7_workflow -v
python -m unittest discover -s tests -v
```


## Claude API configuration

Odin reads the Anthropic API key from the server-side `.env` file. Never paste the key into frontend code, commit it, or send it in chat.

1. Copy `.env.example` to `.env` if you have not already done so.
2. Set `ANTHROPIC_API_KEY` to your own key locally and confirm `CLAUDE_MODEL` is available to your Anthropic account.
3. Keep `MAX_LLM_CALLS` and `MAX_LLM_TOKENS` bounded while testing. The provider-call cap counts attempted network calls, including failed requests; cached responses do not consume another provider call.
4. Restart the FastAPI server after editing `.env`.
5. Open `/api/health` and check `claude_configured`, `claude_model`, and `llm_limits`. These fields never reveal the key.
6. Use **Ask Odin** for source-grounded contract Q&A, or **Analyze portfolio** for the multi-agent portfolio workflow. Claude review is enabled by default in the portfolio request when the key is configured; clear the checkbox to run deterministic-only analysis.

Claude is used as a bounded semantic reviewer where enabled. Exact-quote validation, date arithmetic, evidence checks, and safety/approval rules remain deterministic. If the API is unavailable or the budget is exhausted, inspect the returned agent modes/statuses and usage metadata; do not assume that a configured key means every agent used Claude. The system may continue with explicitly recorded deterministic fallback behavior. A live provider call must be verified locally with your own key.
