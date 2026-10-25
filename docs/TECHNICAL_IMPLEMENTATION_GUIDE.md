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
- FR1.1 Input: The configured Quillhub pack is supported. POST /api/analyze-portfolio now accepts company context plus multiple contract text records, and the dashboard includes a multi-file TXT intake form. This custom path is separate from the full fixed-pack event/payment-aware orchestrator. Partial.
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
- FR3.1: The fixed demo provides a timeline and portfolio operations view for explicit dates and transaction candidates.
- FR3.2: The date selector and FR9 slider rerun analysis with the selected simulated date.
- FR3.3: The A1 scenario has a worst-case note; synthesis reports timelines and states when a defensible financial projection is unavailable.
- Status: partial. The current A1 timeline still contains scenario-specific dates/fee information; a generic obligation calculator for arbitrary clauses and penalty triggers remains unfinished.

### FR4 — Loki Adversarial Review
- FR4.1: The A1 scenario has a specific adversarial notice-timing review and optional Claude path.
- FR4.2: Relationship/reconciliation logic detects document references, a specific amendment pattern, and potential cross-contract exclusivity overlap for review.
- FR4.3: The A1 risk finding includes attack path, severity, likelihood, citations, and evidence gaps. Custom intake emits heuristic risk candidates with severity and explicitly unassessed likelihood.
- FR4.4: A1 evidence gaps can trigger targeted Thor re-extraction. The custom path does not run a full iterative clarification loop.
- Status: partial; generalized adversarial review across every arbitrary contract remains unfinished.

### FR5 — Heimdall Event Monitoring
- FR5.1: The fixed pack loads JSONL event drops, retains parse errors, filters events for the selected date, and links events to known contracts only using explicit identifiers. Custom intake accepts events and maps only explicit contract-ID matches.
- FR5.2: The A1 verifier checks documented outage facts and preserves missing awareness/notification timestamps. Citation checks are separately exposed.
- FR5.3: The decision queue prioritizes returned deadline, payment, and risk candidates. These are not all verified breach alerts.
- Status: partial; generalized event-to-clause mapping and continuous event ingestion remain unfinished.

### FR6 — Tyr Arbitration and Action
- FR6.1: The A1 path resolves the current Loki/Heimdall evidence disagreement into a qualified ruling.
- FR6.2: The A1 path drafts an evidence request. Custom intake creates category-specific draft review actions for renewal, termination, penalty, notice, liability, and other source candidates.
- FR6.3: Drafts carry confidence and human-approval flags. Nothing is sent automatically; the audit endpoint records approval/rejection.
- Status: partial; generalized dispute resolution and fully clause-specific ready-to-send notices remain unfinished.

### FR7 — Agent Workflow
- FR7.1: The A1 scenario demonstrates targeted Thor re-extraction, Loki challenge, Heimdall verification, and Tyr ruling. Custom intake is a deterministic single pass, not a live debate.
- FR7.2: The fixed pipeline has configurable MAX_AGENT_CALLS and MAX_AGENT_ITERATIONS, stop reasons, and unresolved-gap preservation.
- Status: partial to substantial for the fixed scenario; generalized loops for every contract remain unfinished.

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
- Status: UI components exist; end-to-end response mapping and acceptance tests are still required.

## 7. Main API endpoints

- GET / — serve dashboard.
- GET /api/health — health/configuration.
- GET /api/pack — configured pack summary.
- GET /api/run?as_of=2027-03-15&use_claude=false — fixed-pack orchestration.
- POST /api/analyze-portfolio — company context, multiple contract texts, optional event records and simulated date; returns graph, contract reports, company report, alerts and shared state.
- POST /api/reextract — targeted extraction from supplied contract text and optional clause reference.
- POST /api/analyze-upload — document-level PDF/TXT extraction and quote checks; not full portfolio reconciliation.
- GET /api/audit/runs?limit=20 — list saved runs.
- GET /api/audit/runs/{run_id} — saved run and events.
- POST /api/audit/runs/{run_id}/decision — record approved/rejected; never executes an action.

Protected endpoints use the optional bearer-token control. /api/health remains public for health checks.

### Custom portfolio request example

Send JSON with company_context, as_of, contracts, and optional event_records. The contracts field is an array of objects with id and text. Each contract should contain the complete text, not a summary. Event records are an array of objects with timestamps and bodies. The example endpoint enforces contract count, per-contract text length, total input size, and event-count limits.

## 8. Reliability, safety and security

- Malformed JSONL records are retained as parse errors.
- Uploads are capped at 15 MiB.
- PDF text extraction reports when OCR is required.
- Strict Pydantic schemas reject unexpected fields where used.
- The fixed follow-up loop has call and iteration limits.
- Unresolved evidence gaps persist across follow-ups.
- SQLite saves run snapshots and reviewer decisions.
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
- NFR7 LLM usage: Claude is integrated in supported Thor/Loki paths when configured. The custom-input endpoint is deterministic triage, not an LLM multi-agent run. This remains an acceptance gap if judges require every arbitrary portfolio run to use LLM agents.

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

GitHub Actions run 40195473116 completed successfully for commit 7256e3eb9c0b3039c3ddc9583d1756ce2e46f528: dependency installation, Python compileall, and unittest discovery all passed. A full browser/API end-to-end acceptance test has not yet been run. The CI result validates compilation and unit tests, not every functional requirement.

## 11. Highest-priority remaining work

1. Make arbitrary portfolio intake use the same full orchestration as the fixed pack, including event/payment context and a cross-contract workstream.
2. Replace A1-specific timeline and risk logic with generic evidence-grounded handlers.
3. Add targeted clarification loops and explicit completion criteria per workstream.
4. Generalize Loki/Heimdall disagreements and Tyr rulings across all contract workstreams.
5. Improve party/clause extraction and use a genuine 3D engine if strict 3D is required.
6. Calculate exposure only after contract triggers, amounts, periods, invoices and payment status are reconciled.
7. Add and run integration tests for every FR/NFR; verify the dashboard against actual API responses.
8. Harden identity, durable storage, audit tamper evidence, and deployment before handling sensitive contracts.
