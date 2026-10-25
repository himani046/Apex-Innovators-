from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.config import PACK_DIR, USE_CLAUDE
from backend.orchestrator import run_demo
from backend.security import require_api_token, security_mode
from backend.services.audit_store import audit_store
from backend.services.document_upload import DocumentUploadError, extract_uploaded_document
from backend.services.ingestion import load_pack
from backend.services.upload_analysis import extract_document_terms
from backend.services.custom_portfolio import analyze_custom_portfolio
from backend.services.agentic_state import SharedAgentState
from backend.services.event_store import EventStore

event_store = EventStore()

app = FastAPI(
    title="Odin | Contract War Room",
    version="0.2.0",
    docs_url=None if security_mode() == "misconfigured_production" else "/docs",
    redoc_url=None if security_mode() == "misconfigured_production" else "/redoc",
)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response


class HumanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(default="recommended-action", min_length=1, max_length=120)
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=2, max_length=120)
    note: str = Field(default="", max_length=2000)

class ContractTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    text: str = Field(min_length=20, max_length=2_000_000)


class PortfolioAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_context: str = Field(min_length=10, max_length=100_000)
    contracts: list[ContractTextInput] = Field(min_length=1, max_length=50)
    event_records: list[dict] = Field(default_factory=list, max_length=1000)
    as_of: date = Field(default=date(2027, 3, 15))
    use_claude: bool = False

class EventIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=120)
    events: list[dict] = Field(min_length=1, max_length=1000)


class ReExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    text: str = Field(min_length=20, max_length=2_000_000)
    clause_reference: str | None = Field(default=None, max_length=200)
    shared_state: dict = Field(default_factory=dict)


@app.get("/", response_class=HTMLResponse)
def home():
    return (FRONTEND / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "project": "Odin — The Contract War Room",
        "pack_found": PACK_DIR.exists(),
        "claude_configured": USE_CLAUDE,
        "persistent_audit_enabled": True,
        "persistent_event_store_enabled": True,
        "security_mode": security_mode(),
    }


@app.get("/api/pack")
def pack_summary():
    pack = load_pack(PACK_DIR)
    return {
        "company": "Quillhub Inc.",
        "contracts": [{"id": key, "characters": len(value)} for key, value in pack["contracts"].items()],
        "event_counts": {key: len(value) for key, value in pack["event_drops"].items()},
        "parse_errors": pack["parse_errors"],
        "checkpoints": pack["clock"]["checkpoints"],
    }


@app.post("/api/events/ingest", dependencies=[Depends(require_api_token)])
def ingest_events(body: EventIngestionRequest = Body(...)):
    """Persist source-labeled event records; persistence does not authenticate their provenance."""
    try:
        return event_store.ingest(body.source, body.events)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/events", dependencies=[Depends(require_api_token)])
def list_events(as_of: date | None = Query(default=None), limit: int = Query(default=1000, ge=1, le=5000)):
    """List durable event records; future records are excluded when a simulated date is supplied."""
    try:
        return event_store.list_events(as_of=as_of.isoformat() if as_of else None, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid event query") from exc


@app.get("/api/run")
def run(as_of: date = Query(default=date(2027, 3, 15)), use_claude: bool = Query(default=True)):
    try:
        result = run_demo(as_of.isoformat(), use_claude)
        audit = audit_store.record_run(result)
        result["audit"] = {
            "run_id": audit["run_id"],
            "created_at": audit["created_at"],
            "input_fingerprint": audit["input_fingerprint"],
        }
        result["run_id"] = audit["run_id"]
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="as_of must be an ISO date, e.g. 2027-03-15") from exc
    except Exception as exc:
        # Avoid returning internal exception text, paths, or provider details to clients.
        raise HTTPException(status_code=500, detail="Odin run failed safely; inspect server logs.") from exc


@app.post("/api/reextract", dependencies=[Depends(require_api_token)])
def reextract_clause(body: ReExtractionRequest = Body(...)):
    """Re-extract one requested clause and return the updated structured shared state."""
    from backend.services.upload_analysis import extract_document_terms

    extraction = extract_document_terms(body.text, body.contract_id)
    terms = extraction.get("extracted_terms", [])
    for term in terms:
        citation = term.get("citation") or {}
        citation["verified"] = bool(citation.get("quote") and citation["quote"] in body.text)
        citation["document_id"] = body.contract_id
        term["citation"] = citation
    if body.clause_reference:
        needle = body.clause_reference.casefold()
        terms = [term for term in terms if needle in str((term.get("citation") or {}).get("clause_reference", "")).casefold()
                 or needle in str((term.get("citation") or {}).get("quote", "")).casefold()]
    shared = SharedAgentState(body.shared_state)
    existing_terms = shared.data.get("extracted_clauses", []) or []
    existing_refs = shared.data.get("evidence_references", []) or []
    shared.update("extracted_clauses", existing_terms + terms)
    shared.update("evidence_references", existing_refs + [term.get("citation") for term in terms if term.get("citation")])
    shared.message("Odin", "Thor", "targeted_reextraction_request", "complete",
                   contract_id=body.contract_id, clause_reference=body.clause_reference)
    shared.message("Thor", "Odin", "targeted_reextraction_result", "complete" if terms else "no_matching_terms",
                   contract_id=body.contract_id, terms_returned=len(terms))
    return {"status": "complete" if terms else "no_matching_terms", "contract_id": body.contract_id,
            "clause_reference": body.clause_reference, "extracted_terms": terms,
            "shared_state": shared.snapshot(),
            "notice": "Returned terms are source-grounded candidates. Shared state is updated in this response; persist the returned snapshot with the run record if durable history is required."}


@app.post("/api/analyze-portfolio", dependencies=[Depends(require_api_token)])
def analyze_portfolio(body: PortfolioAnalysisRequest = Body(...)):
    """Analyze a user-supplied company context and multiple contract texts.

    The custom-input path performs conservative deterministic source triage. It
    does not claim to run a live multi-agent LLM debate or calculate unsupported
    financial exposure.
    """
    contract_ids = [item.id.strip() for item in body.contracts]
    if len(set(cid.casefold() for cid in contract_ids)) != len(contract_ids):
        raise HTTPException(status_code=422, detail="Contract IDs must be unique, ignoring case")
    total_bytes = sum(len(item.text.encode("utf-8")) for item in body.contracts)
    if total_bytes > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Combined contract text exceeds the 15 MB limit")
    try:
        stored_events = event_store.list_events(as_of=body.as_of.isoformat(), limit=1000)["events"]
        combined_events = {}
        for event in stored_events + body.event_records:
            event_id = str(event.get("event_id") or event.get("id") or "")
            source_id = str(event.get("source") or "request")
            key = (source_id, event_id) if event_id else (source_id, str(event.get("body") or event.get("text") or ""))
            combined_events[key] = event
        result = analyze_custom_portfolio(
            company_context=body.company_context,
            contract_items=[{"id": item.id.strip(), "text": item.text} for item in body.contracts],
            events=list(combined_events.values()),
            as_of=body.as_of.isoformat(),
            use_llm=body.use_claude,
        )
        result["event_store_context"] = {
            "stored_events_loaded": len(stored_events),
            "request_events_received": len(body.event_records),
            "event_source_authenticity_verified": False,
        }
        audit = audit_store.record_run(result)
        result["audit"] = {
            "run_id": audit["run_id"],
            "created_at": audit["created_at"],
            "input_fingerprint": audit["input_fingerprint"],
        }
        result["run_id"] = audit["run_id"]
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid simulated date or portfolio input") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Portfolio analysis failed safely; inspect server logs.") from exc


@app.get("/api/audit/runs", dependencies=[Depends(require_api_token)])
def audit_runs(limit: int = Query(default=25, ge=1, le=100)):
    """List persistent analysis runs for the audit explorer."""
    return {"runs": audit_store.list_runs(limit)}


@app.get("/api/audit/runs/{run_id}", dependencies=[Depends(require_api_token)])
def audit_run(run_id: str):
    """Fetch a saved run snapshot, provenance events, and human decisions."""
    result = audit_store.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Audit run not found")
    return result


@app.post("/api/audit/runs/{run_id}/decision", dependencies=[Depends(require_api_token)])
def record_human_decision(run_id: str, body: HumanDecisionRequest = Body(...)):
    """Record an explicit review decision. This endpoint never executes the action."""
    try:
        return audit_store.decide(
            run_id=run_id,
            action_id=body.action_id,
            decision=body.decision,
            reviewer=body.reviewer,
            note=body.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze-upload", dependencies=[Depends(require_api_token)])
async def analyze_upload(file: UploadFile = File(...), use_claude: bool = Query(default=True)):
    """Analyze one uploaded PDF/TXT using the evidence-grounded extraction path."""
    try:
        raw = await file.read(15 * 1024 * 1024 + 1)
        if len(raw) > 15 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Upload exceeds the 15 MB limit")
        document = extract_uploaded_document(file.filename or "contract.txt", raw)
        contract_id = Path(document["filename"]).stem.upper()
        source_id = contract_id if contract_id in {"A1", "A2", "A3", "B1", "B2", "C1", "D1", "STD"} else document["filename"]
        extraction = extract_document_terms(document["text"], source_id)
        citations = []
        for term in extraction.get("extracted_terms", []):
            citation = term.get("citation") or {}
            citation["document_id"] = source_id
            citation["verified"] = bool(citation.get("quote") and citation["quote"] in document["text"])
            citation["verification_note"] = (
                "Exact quote matched uploaded document text."
                if citation["verified"]
                else "Quote not found verbatim in uploaded document; human review required."
            )
            term["citation"] = citation
            citations.append(citation)
        extraction["citation_validation"] = {
            "total": len(citations),
            "verified": sum(1 for citation in citations if citation.get("verified")),
            "failed": sum(1 for citation in citations if not citation.get("verified")),
        }
        return {
            "status": "complete_with_limitations",
            "document": {key: value for key, value in document.items() if key != "text"},
            "document_id": source_id,
            "extraction": extraction,
            "notice": (
                "This upload run extracts terms and verifies exact quotes only. It does not yet reconcile "
                "this upload against all contracts, event drops, or the payment ledger. Scanned PDFs need OCR before upload."
            ),
        }
    except DocumentUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
