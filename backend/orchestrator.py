from datetime import date
from backend.config import PACK_DIR,USE_CLAUDE,MAX_AGENT_CALLS,MAX_AGENT_ITERATIONS
from backend.services.ingestion import load_pack
from backend.services.citations import verify_all
from backend.agents.thor import extract_a1
from backend.agents.thor_portfolio import extract_portfolio_candidates
from backend.agents.norns import build_timeline
from backend.agents.loki import review
from backend.agents.heimdall import verify
from backend.agents.tyr import arbitrate
def run_demo(as_of='2027-03-15',request_claude=True):
 date.fromisoformat(as_of);pack=load_pack(PACK_DIR);portfolio_extraction=extract_portfolio_candidates(pack['contracts']);source=pack['contracts'].get('A1')
 if not source:raise RuntimeError('A1.txt missing from supplied pack')
 use=request_claude and USE_CLAUDE
 state={'run_id':'odin-a1-'+as_of,'as_of_date':as_of,'scope':'A1-only vertical slice; not a complete portfolio analysis','status':'running','portfolio_extraction':portfolio_extraction,'workstreams':[{'id':'contract-A1','status':'running','assigned_agents':['Thor','Norns','Loki','Heimdall','Tyr']}],'api_usage':{'max_calls':MAX_AGENT_CALLS,'max_iterations':MAX_AGENT_ITERATIONS},'agent_messages':[]}
 x=extract_a1(source,use);terms=x.get('extracted_terms',[])
 for t in terms:
  if t.get('citation'):t['citation']=verify_all([t['citation']],{'A1':source})[0]
 x['citation_validation']={'total':len(terms),'verified':sum(bool(t.get('citation',{}).get('verified')) for t in terms),'failed':sum(not t.get('citation',{}).get('verified',False) for t in terms)};state['extraction']=x;state['agent_messages'].append({'from':'Thor','to':'Odin','type':'extraction_complete','status':'complete'})
 state['timeline']=build_timeline(x,as_of);state['agent_messages'].append({'from':'Norns','to':'Odin','type':'timeline_complete','status':'complete'})
 events=[e for e in pack['event_drops']['events_drop1.jsonl'] if e.get('timestamp','')[:10]<=as_of];finding=review(x,events,use);finding['citations']=verify_all(finding.get('citations',[]),{'A1':source});state['risk_finding']=finding;state['agent_messages'].append({'from':'Loki','to':'Heimdall','type':'risk_claim','status':'submitted'})
 state['verification']=verify(finding,events,finding.get('citations',[]));state['agent_messages'].append({'from':'Heimdall','to':'Tyr','type':'verification','status':state['verification']['status']});state['ruling']=arbitrate(finding,state['verification']);state['agent_messages'].append({'from':'Tyr','to':'Odin','type':'ruling','status':'complete'})
 state['event_summary']={'drop1_events_available_as_of_date':len(events),'drop2_events_loaded':len(pack['event_drops']['events_drop2.jsonl']),'parse_errors':pack['parse_errors']};state['workstreams'][0]['status']='complete_with_limitations';state['status']='complete_with_limitations';state['agent_modes']={n:('claude' if use and n in ('Thor','Loki') else 'deterministic') for n in ['Odin','Thor','Norns','Loki','Heimdall','Tyr']};state['limitations']=['This slice analyses A1 only; incorporated A2, A3 and STD are not fully resolved.','Norns, Heimdall and Tyr use deterministic logic in this version.','Draft actions require human approval and are never sent automatically.'];return state
