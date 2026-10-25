from pathlib import Path
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from backend.config import PACK_DIR,USE_CLAUDE
from backend.orchestrator import run_demo
from backend.services.ingestion import load_pack
from backend.services.document_upload import DocumentUploadError, extract_uploaded_document
from backend.services.upload_analysis import extract_document_terms
from backend.config import USE_CLAUDE
from pathlib import Path
app=FastAPI(title='Odin | Contract War Room',version='0.1.0')
FRONTEND=Path(__file__).resolve().parents[1]/'frontend';app.mount('/static',StaticFiles(directory=str(FRONTEND)),name='static')
@app.get('/',response_class=HTMLResponse)
def home():return (FRONTEND/'index.html').read_text(encoding='utf-8')
@app.get('/api/health')
def health():return {'status':'ok','project':'Odin — The Contract War Room','pack_found':PACK_DIR.exists(),'claude_configured':USE_CLAUDE}
@app.get('/api/pack')
def pack_summary():
 p=load_pack(PACK_DIR);return {'company':'Quillhub Inc.','contracts':[{'id':k,'characters':len(v)} for k,v in p['contracts'].items()],'event_counts':{k:len(v) for k,v in p['event_drops'].items()},'parse_errors':p['parse_errors'],'checkpoints':p['clock']['checkpoints']}
@app.get('/api/run')
def run(as_of:str=Query(default='2027-03-15'),use_claude:bool=Query(default=True)):
 try:\n  result=run_demo(as_of,use_claude)\n  audit=audit_store.record_run(result)\n  result["audit"]={"run_id":audit["run_id"],"created_at":audit["created_at"],"input_fingerprint":audit["input_fingerprint"]}\n  result["run_id"]=audit["run_id"]\n  return result
 except ValueError:raise HTTPException(status_code=400,detail='as_of must be an ISO date, e.g. 2027-03-15')
 except Exception as exc:raise HTTPException(status_code=500,detail='Odin run failed safely: '+str(exc))


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
            citation["verification_note"] = "Exact quote matched uploaded document text." if citation["verified"] else "Quote not found verbatim in uploaded document; human review required."
            term["citation"] = citation
            citations.append(citation)
        extraction["citation_validation"] = {
            "total": len(citations),
            "verified": sum(1 for c in citations if c.get("verified")),
            "failed": sum(1 for c in citations if not c.get("verified")),
        }
        return {
            "status": "complete_with_limitations",
            "document": {k: v for k, v in document.items() if k != "text"},
            "document_id": source_id,
            "extraction": extraction,
            "notice": "This upload run extracts terms and verifies exact quotes only. It does not yet reconcile this upload against all contracts, event drops, or the payment ledger. Scanned PDFs need OCR before upload.",
        }
    except DocumentUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
