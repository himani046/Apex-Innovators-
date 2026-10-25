import os
from functools import lru_cache
from backend.config import MODEL
@lru_cache(maxsize=1)
def client():
 import anthropic
 key=os.getenv('ANTHROPIC_API_KEY','').strip()
 if not key: raise RuntimeError('ANTHROPIC_API_KEY is not configured')
 return anthropic.Anthropic(api_key=key,max_retries=1,timeout=45.0)
def ask_claude(system_prompt,user_prompt,max_tokens=1400):
 response=client().messages.create(model=MODEL,max_tokens=max_tokens,system=system_prompt,messages=[{'role':'user','content':user_prompt}])
 return '\n'.join(b.text for b in response.content if getattr(b,'type','')=='text')
