from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.config import PACK_DIR, USE_CLAUDE
from backend.orchestrator import run_demo
from backend.services.audit_store import audit_store
from backend.services.document_upload import DocumentUploadError, extract_uploaded_document
from backend.services.ingestion import load_pack
from backend.services.upload_analysis import extract_document_terms

app = FastAPI(title="Odin | Contract War Room", version="0.1.0")
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


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


@app.get("/api/run")
def run(as_of: str = Query(default="2027-03-15"), use_claude: bool = Query(default=True)):
    try:
        result = run_demo(as_of, use_claude)
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
        raise HTTPException(status_code=500, detail="Odin run failed safely: " + str(exc)) from exc


@app.get("/api/audit/runs")
def audit_runs(limit: int = Query(default=25, ge=1, le=100)):
    """List persistent analysis runs for the audit explorer."""
    return {"runs": audit_store.list_runs(limit)}


@app.get("/api/audit/runs/{run_id}")
def audit_run(run_id: str):
    """Fetch a saved run snapshot, provenance events, and human decisions."""
    result = audit_store.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Audit run not found")
    return result


@app.post("/api/audit/runs/{run_id}/decision")
def record_human_decision(run_id: str, body: dict = Body(...)):
    """Record an explicit review decision. This endpoint never executes the action."""
    try:
        return audit_store.decide(
            run_id=run_id,
            action_id=body.get("action_id", "recommended-action"),
            decision=body.get("decision", ""),
            reviewer=body.get("reviewer", ""),
            note=body.get("note", ""),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze-upload")
async def analyze_upload(file: UploadFile = File(...), use_claude: bool = Query(default=True)):
    """Analyze one uploaded PDF/TXT using the evidence-grounded extraction path."""
    try:
        raw = await file.read()
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
