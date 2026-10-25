def verify_citation(citation,contracts):
 doc=str(citation.get('document_id','')); quote=str(citation.get('quote','')); ok=bool(quote.strip()) and quote in contracts.get(doc,'')
 return {**citation,'verified':ok,'verification_note':'Exact quote found in canonical source.' if ok else 'Quote not found verbatim; do not treat as verified evidence.'}
def verify_all(citations,contracts): return [verify_citation(c,contracts) for c in citations]
