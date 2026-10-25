# Odin — Technical Implementation Guide

This guide explains the current codebase in plain language and maps it to the RAGNAROK Problem Statement 2 functional and non-functional requirements. It distinguishes implemented behavior from partial work. A UI panel or an agent name is not proof that the underlying behavior has passed acceptance tests.

## 1. What Odin does

Odin is a multi-agent contract-intelligence prototype. It reads contracts and related event/payment data, extracts source passages, builds document relationships, identifies dates and candidate risks, asks specialized analysis stages to challenge and verify claims, prepares human-review actions, and records analysis runs.

It is decision support, not legal advice. A source quotation, risk signal, or graph edge does not automatically prove a breach, conflict, penalty, or recoverable financial amount.

## 2. Complete technology stack

| Technology | Where used | Purpose |
|---|---|---|
| Python | Backend, agents, analysis services | Ingestion, extraction, coordination, deterministic rules |
| FastAPI | backend/app.py | HTTP API, request validation, uploads, review routes |
| Uvicorn | Application server | Runs the FastAPI ASGI application |
| Pydantic v2 | Request models in backend/app.py | Validates types, bounds, allowed values, and unknown fields |
| Anthropic Python SDK | backend/claude_client.py | Optional Claude calls for supported Thor/Loki paths |
| Python regex and text processing | Agent and service modules | Source-line triage and candidate extraction |
| pypdf | backend/services/document_upload.py | Text extraction from text-based PDFs |
| python-multipart | FastAPI upload endpoint | Parses multipart document uploads |
| python-dotenv | backend/config.py | Loads local .env configuration |
| SQLite | backend/services/audit_store.py | Persistent run snapshots, finding history, audit events, review decisions |
| HTML, CSS, JavaScript | frontend/index.html | Single-page dashboard, tabs, canvas graph, timeline and review panels |
| TXT | odin_dev_pack/bundle/contracts | Canonical source text used to verify exact quotations |
| JSON and JSONL | Manifest, event drops, API payloads, shared state | Structured contract/event data and agent handoffs |
| CSV | Payment ledger and holiday data | Tabular operational inputs |
| unittest | tests/ | Regression tests |

The frontend is plain HTML/CSS/JavaScript, not React. The graph uses a browser canvas with a perspective projection, drag rotation, zoom, hover details, and selection. It is pseudo-3D canvas rendering, not a Three.js/WebGL scene.

### Environment variables

- ANTHROPIC_API_KEY enables optional Claude use in supported agent paths.
- CLAUDE_MODEL selects the configured model.
- MAX_AGENT_CALLS limits orchestrated agent/task invocation slots.
- MAX_AGENT_ITERATIONS limits bounded feedback iterations.
- ODIN_API_TOKEN enables the shared bearer-token gate for protected routes.
- ODIN_ENV=production causes protected routes to fail closed if the token is missing.
- ODIN_AUDIT_DB chooses the SQLite database path.

Never commit real API keys or bearer tokens. The deterministic fallback can run without Claude. Do not claim that Claude was used on a particular run unless runtime configuration and logs confirm it.

## 3. Architecture in simple terms

1. Ingestion reads canonical contract text, company context, event drops, payment ledger, holiday data, and configured clock.
2. Thor finds potentially relevant text and attaches source citations.
3. Odin creates workstreams, records handoffs, and controls workflow.
4. Norns classifies dates and builds timeline candidates.
5. Loki challenges proposed risk interpretations.
6. Heimdall checks event/citation evidence and identifies gaps.
7. Tyr records a qualified ruling and prepares a draft action for human review.
8. Synthesis builds a report per contract and a company-level report.
9. The dashboard renders structured outputs.
10. SQLite stores run snapshots, evidence provenance, findings, messages, and reviewer decisions.

These agents are Python modules inside one application, not separate microservices. The fixed demonstration uses state-machine-style orchestration rather than unconstrained group chat.

## 4. What agentic AI means in Odin

Agentic AI is not simply calling an LLM. In Odin, it means distinct responsibilities, explicit inputs/outputs, shared state, recorded handoffs, and an orchestrator that controls what happens next.

### Shared state

backend/services/agentic_state.py defines SharedAgentState. Its JSON-serializable sections include:
- Contract relationships.
- Extracted clauses.
- Timeline events.
- Financial candidates/calculations.
- Risk claims.
- Evidence references.
- Verification outcomes.
- Unresolved questions.
- Recommended actions.
- Agent statuses and messages.
- Iteration and call-budget metadata.

A message records sender, recipient, message type, status, and structured payload. This makes the workflow inspectable instead of hiding every intermediate result inside a prompt.

### Execution budget and feedback

ExecutionBudget tracks maximum calls and iterations. run_bounded_follow_up checks whether verification still needs follow-up, reserves an iteration and call slot, invokes targeted re-analysis, and preserves old evidence gaps unless the verifier explicitly marks them resolved. This helps prevent infinite loops and false claims that a gap was resolved merely because a later pass omitted it. Provider-internal retries are not counted by the orchestrator budget.

### LLM versus deterministic behavior

- Thor's A1 extraction and Loki's A1 review can call Claude when configured.
- Deterministic fallbacks exist.
- Norns, Heimdall, and Tyr in the current fixed demonstration use deterministic logic.
- The custom portfolio intake path performs deterministic source triage in one pass. It does not claim to run a live LLM debate.
- The presence of an agent panel does not itself prove that an LLM call occurred.

LLM integration exists in supported paths, but general-purpose multi-agent LLM analysis for arbitrary contract sets remains unfinished.

## 5. Evidence model

Canonical TXT contract sources are citation anchors. A citation records document ID, clause/section reference, exact quote, verification status, and verification note. Extracted terms carry a heuristic confidence value where the extractor provides one.

A finding distinguishes:
- What a source explicitly says.
- What an agent infers or challenges.
- Which quotations were checked.
- Which evidence is missing.
- What next step is recommended.
- Whether human review is required.

Exact quote matching helps catch invented or misattributed quotations. It does not prove that a quotation is legally applicable or that the interpretation is correct. Keyword extraction is triage and can miss clauses or classify non-operative text.

## 6. Functional requirements status

### FR1 — Odin Orchestrator
- FR1.1 Input: The configured Quillhub pack is supported. POST /api/analyze-portfolio accepts company context, multiple contract text records, optional event records, and an optional payment_ledger array; the dashboard exposes all four inputs. The custom path runs generalized bounded review and conservative invoice/payment reconciliation. Partial.
- FR1.2 Planning: The fixed pack creates source-specific workstreams and a portfolio-wide review stream. General configurable-input planning remains partial.
- FR1.3 Delegation/tracking: Shared state records statuses, handoffs, and call/iteration usage. Some statuses are summary-level rather than a complete task lifecycle. Partial to substantial.
- FR1.4 Coordination: The fixed A1 scenario has bounded targeted follow-up and final ruling. Explicit clarification/debate and completion gates for every arbitrary contract are not yet complete. Partial.

### FR2 — Thor Extraction Agent
- FR2.1: Source-line triage covers parties, duration/term, renewal, payment schedules, obligations, penalties/damages, compliance, notices, liability, incidents, termination, confidentiality, and dispute/law keywords.
- FR2.2: Candidate terms include confidence and a source citation. Citation verification checks quotes against source text.
- FR2.3: Heuristic ambiguity flags identify potentially conflicting renewal/termination language and override/exception wording. This is not a complete contradiction solver.
- FR2.4: POST /api/reextract accepts a contract ID, source text, optional clause reference, and shared-state snapshot. It returns targeted terms and an updated state snapshot. The caller must retain that snapshot for durable continuity.
- Status: broad source-grounded triage and targeted re-extraction exist; semantic completeness and calibrated confidence are not established.

### FR3 — Norns Timeline Agent
- FR3.1: The timeline and portfolio operations view includes explicit dates and transaction candidates. Invoice-reference groups calculate a candidate ledger balance only when an invoice amount, payment/credit amounts, currency, event IDs, and due-date evidence are internally reconcilable. The balance is arithmetic over supplied rows, not verified exposure; source authenticity and contractual trigger applicability remain separate gates.
- FR3.2: The date selector and FR9 slider rerun analysis with the selected simulated date.
- FR3.3: The A1 scenario has a worst-case note; synthesis reports timelines and states when a defensible financial projection is unavailable.
- Status: partial. The current A1 timeline still contains scenario-specific dates/fee information; a generic obligation calculator for arbitrary clauses and penalty triggers remains unfinished.

### FR4 — Loki Adversarial Review
- FR4.1: The A1 scenario has a specific adversarial notice-timing review and optional Claude path.
- FR4.2: Relationship/reconciliation logic detects document references, a specific amendment pattern, and potential cross-contract exclusivity overlap for review.
- FR4.3: The A1 risk finding includes attack path, severity, likelihood, citations, and evidence gaps. Custom intake emits heuristic risk candidates with severity and explicitly unassessed likelihood.
- FR4.4: Bounded per-contract review can request targeted Thor re-extraction. Cross-contract candidates now also pass through a bounded Loki challenge → Heimdall citation/event verification → Tyr human-review ruling trace. This is evidence-first triage, not semantic legal adjudication.
- Status: bounded review handoffs are implemented; deeper semantic analysis of arbitrary contracts, precedence resolution, and legally equivalent scope remain unfinished.

### FR5 — Heimdall Event Monitoring
- FR5.1: The fixed pack loads JSONL event drops and retains parse errors. Custom intake accepts supplied events; `POST /api/events/ingest` stores source-labeled event records in SQLite, deduplicates unchanged records, and retains before/after payload snapshots when an existing event changes. `GET /api/events?as_of=YYYY-MM-DD` filters future-dated events for a simulated date and exposes revision counts.
- FR5.2: Event records are normalized; missing bodies and invalid timestamps are rejected, and event-to-contract mapping remains evidence-led. Explicit IDs and lexical clause overlap are candidates, not proof of causation.
- FR5.3: The verifier preserves missing awareness/notification timestamps. Event source authenticity is never accepted from a user-supplied flag; a trusted external-source connector and signature/provenance validation are still required.
- Status: substantial ingestion and normalization foundation; authenticated external integrations and causal event-to-clause verification remain partial.

### FR6 — Tyr Arbitration and Action
- FR6.1: The A1 path resolves the current Loki/Heimdall evidence disagreement into a qualified ruling.
- FR6.2: The A1 path drafts an evidence request. Custom intake creates category-specific draft review actions for renewal, termination, penalty, notice, liability, and other source candidates.
- FR6.3: Drafts carry confidence and human-approval flags. Nothing is sent automatically; the audit endpoint records approval/rejection.
- Status: partial; generalized dispute resolution and fully clause-specific ready-to-send notices remain unfinished.

### FR7 — Agent Workflow
- FR7.1: Fixed-pack and custom portfolio runs execute bounded per-contract Thor → Norns → Loki → Heimdall → Tyr cycles with structured handoffs, targeted source re-extraction, persistent evidence gaps, and explicit stop reasons.
- FR7.2: Cross-contract candidates have a separate bounded Loki → Heimdall → Tyr review trace with exact source-quote checks, event candidates, draft-only actions, and explicit unresolved context checks for parties, scope, precedence, and incorporated terms.
- FR7.3: Iterations and agent calls are budgeted. Budget exhaustion or candidate-limit exhaustion is surfaced as partial completion; analysis completion does not mean a legal outcome is resolved.
- FR7.4: Claude review is opt-in. When configured, Thor/Loki/Heimdall/Tyr can contribute suggestions; model-proposed source quotations are checked against canonical contract/event text, and Tyr actions remain draft-only. Without a configured key, the workflow falls back to deterministic agents.
- Status: bounded per-contract and cross-contract handoffs plus optional hybrid LLM path implemented; live-provider smoke tests, deeper semantic disagreement resolution, and full browser/API acceptance remain outstanding.

### FR8 — Synthesis
- FR8.1: backend/services/synthesis.py assembles a report per contract with terms, obligations, timeline, risks, recommended actions, citations, citation validation, confidence where available, and unresolved questions.
- FR8.2: The company report includes cross-contract relationships, amendment review items, prioritized actions, worst-case timeline notes, references, and unresolved questions. Total exposure remains null unless a defensible aggregate is supplied.
- Status: implemented as conservative synthesis; completeness depends on upstream evidence coverage.

### FR9 — Dashboard
- FR9.1: The graph displays document nodes and evidence-backed edges. The canvas renderer supports perspective rotation, zoom, hover details, and selected-node evidence. Custom intake graph data includes clause nodes and explicitly labeled party nodes when those labels occur in source text. It is pseudo-3D, not a WebGL scene; party extraction is limited.
- FR9.2: The slider maps to a simulated date and triggers a rerun, not an instant cached replay.
- FR9.3: Exposure is unavailable when unsupported; heatmap levels are risk-signal counts, not calibrated probabilities or dollar amounts.
- FR9.4: The panel displays Loki, Heimdall, and Tyr outputs returned by the current run. A three-column panel alone is not proof of a live debate.
- FR9.5: Alert and action panels display decision-queue items and draft notices with citations where returned. Actions remain draft-only.
- Status: UI components and backend regression/acceptance tests exist. The CI workflow compiles Python, validates inline dashboard JavaScript, and runs unittest. Full browser interaction checks and a real Claude-provider smoke test remain outstanding.

## 7. Main API endpoints

- GET / — serve dashboard.
- GET /api/health — health/configuration.
- GET /api/pack — configured pack summary.
- GET /api/run?as_of=2027-03-15&use_claude=false — fixed-pack orchestration.
- POST /api/analyze-portfolio — company context, multiple contract texts, optional event records, optional payment_ledger rows, simulated date, and opt-in `use_claude`; returns graph, workflow traces, contract reports, company report, alerts, financial reconciliation candidates (including conditional arithmetic balance candidates), and shared state.
- POST /api/events/ingest — persist source-labeled event records with deduplication; records remain unverified.
- GET /api/events?as_of=YYYY-MM-DD — list stored events and exclude future-dated records for the selected simulated date; changed records include revision metadata.
- GET /api/events/history?source=...&event_id=... — retrieve before/after payload snapshots for a changed event.
- POST /api/reextract — targeted extraction from supplied contract text and optional clause reference.
- POST /api/analyze-upload — document-level PDF/TXT extraction and quote checks; not full portfolio reconciliation.
- GET /api/audit/runs?limit=20 — list saved runs.
- GET /api/audit/runs/{run_id} — saved run and events.
- POST /api/audit/runs/{run_id}/decision — record approved/rejected; never executes an action.

Protected endpoints use the optional bearer-token control. /api/health remains public for health checks.

### Custom portfolio request example

Send JSON with company_context, as_of, contracts, and optional event_records and payment_ledger. The contracts field is an array of objects with id and text. Each contract should contain the complete text, not a summary. Event records are objects with timestamps and bodies. Payment-ledger rows may include date/timestamp, contract_id, reference or invoice_id, amount, currency, status, and counterparty fields. Invoice links and source clause matches remain candidates; totals are not inferred from unverified rows. The endpoint enforces contract count, per-contract text length, total contract input size, and event/ledger row limits.

## 8. Reliability, safety and security

- Malformed JSONL records are retained as parse errors.
- Uploads are capped at 15 MiB.
- PDF text extraction reports when OCR is required.
- Strict Pydantic schemas reject unexpected fields where used.
- The fixed follow-up loop has call and iteration limits.
- Unresolved evidence gaps persist across follow-ups.
- SQLite saves run snapshots, reviewer decisions, and source-labeled event records; this is persistence, not proof of event authenticity.
- The API can require a shared bearer token and fails closed in production mode if it is not configured.
- Security headers and non-cache headers are applied.
- Draft actions are never sent automatically.

Limitations: a shared token is not individual identity verification; reviewer names are caller-supplied; SQLite is not tamper-proof; deployment storage must be durable; TLS, rate limiting, secret rotation, and production security review remain necessary.

## 9. Non-functional requirements status

- NFR1 Architecture: Agents are separate modules and communicate through structured state/messages. Partial for the custom intake workflow.
- NFR2 Analysis quality: Exact-quote checks, source references, ambiguity flags, and fact/interpretation separation exist. Heuristic extraction is not exhaustive.
- NFR3 Reliability: Malformed events, upload errors, token misconfiguration, bounded loops, and safe error responses are handled. Broader retry/failure coverage still needs tests.
- NFR4 Observability: Workstreams, statuses, handoffs, findings, timelines, citations, and audit history are exposed; some statuses remain high-level.
- NFR5 Performance: Call/iteration limits and targeted re-extraction exist. Cross-run caching and comprehensive duplicate-call avoidance are not implemented.
- NFR6 Reproducibility: Fixed-pack deterministic fallback and structured state exist; audit snapshots are persistent. LLM output may vary.
- NFR7 LLM usage: Claude can be explicitly enabled for bounded Thor/Loki/Heimdall/Tyr review when a key is configured. Quote validation, call budgets, safe fallback, and draft-only actions are implemented. No provider key is configured in the current environment, so the default run remains deterministic; a live-provider smoke test is still needed.

## 10. Run locally

Create and activate a Python virtual environment, install requirements.txt, copy .env.example to .env, then run:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000.

Check the fixed demonstration:

    curl http://127.0.0.1:8000/api/health
    curl http://127.0.0.1:8000/api/pack
    curl "http://127.0.0.1:8000/api/run?as_of=2027-03-15&use_claude=false"

Run tests:

    python -m unittest discover -s tests -v

GitHub Actions run 40195717406 completed successfully for commit 4ff4886d9280529cd3c1f7b1270ae1d0da7c0286: dependency installation, Python compileall, and unittest discovery all passed. The dashboard JavaScript also passed a syntax compilation check. A full browser/API end-to-end acceptance test has not yet been run. These checks validate compilation and unit tests, not every functional requirement.

## 11. Highest-priority remaining work

1. Add trusted external event adapters and independent source-provenance/authenticity verification; current ingestion validates record shape and timestamps but cannot authenticate the sender.
2. Improve semantic contract comparison for party/scope equivalence, amendment precedence, and incorporated terms; new context diagnostics are signals only and conflicts remain human-review candidates.
3. Reconcile invoice, due date, contractual trigger, payment/credit evidence, and source authenticity before calculating exposure.
4. Run a live-provider smoke test when a valid Claude key is available; validate provider timeout, retry, malformed-output, and failure behavior against a real provider.
5. Add browser-driven end-to-end tests for upload, analysis, graph, reports, stored event feed, cross-contract review, and human decision flow.
6. Improve extraction beyond keyword heuristics and replace the pseudo-3D graph with WebGL only if strict 3D is required.
7. Harden identity, tamper-evident audit storage, TLS, rate limiting, deployment volumes, and secret rotation before handling sensitive contracts.
