from datetime import date,timedelta
def build_timeline(extraction,as_of):
 now=date.fromisoformat(as_of);start=date(2026,8,1);end=date(2028,7,31);deadline=end-timedelta(days=90);items=[]
 for dt,title in [(start,'A1 effective date'),(deadline,'A1 stated non-renewal notice deadline — check amendments'),(end,'A1 initial term ends')]:items.append({'date':dt.isoformat(),'title':title,'status':'past' if dt<now else 'upcoming','amount_usd':None})
 return {'agent':'Norns','as_of_date':as_of,'milestones':items,'monthly_fee':{'amount_usd':8000,'cadence':'monthly','note':'Contract fee only; ledger reconciliation is not included in this first slice.'},'worst_case_note':'A1 states 1.5% monthly interest on overdue amounts. Exact exposure requires invoice principal, due date and payment history.','status':'computed'}
