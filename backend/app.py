from pathlib import Path
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from backend.config import PACK_DIR,USE_CLAUDE
from backend.orchestrator import run_demo
from backend.services.ingestion import load_pack
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
 try:return run_demo(as_of,use_claude)
 except ValueError:raise HTTPException(status_code=400,detail='as_of must be an ISO date, e.g. 2027-03-15')
 except Exception as exc:raise HTTPException(status_code=500,detail='Odin run failed safely: '+str(exc))
