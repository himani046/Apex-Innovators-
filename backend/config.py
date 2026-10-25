from pathlib import Path
import os
from dotenv import load_dotenv
ROOT_DIR=Path(__file__).resolve().parents[1]
PACK_DIR=ROOT_DIR/'odin_dev_pack'
load_dotenv(ROOT_DIR/'.env')
MODEL=os.getenv('CLAUDE_MODEL','claude-haiku-4-5')
MAX_AGENT_CALLS=int(os.getenv('MAX_AGENT_CALLS','12'))
MAX_AGENT_ITERATIONS=int(os.getenv('MAX_AGENT_ITERATIONS','2'))
USE_CLAUDE=bool(os.getenv('ANTHROPIC_API_KEY','').strip())

# Separate hard cap for the generalized portfolio workflow; never derive an unlimited budget from pack size.
MAX_PORTFOLIO_AGENT_CALLS = max(1, int(os.getenv('MAX_PORTFOLIO_AGENT_CALLS', '300')))
CITATION_VERIFICATION_THRESHOLD = min(0.99, max(0.0, float(os.getenv('CITATION_VERIFICATION_THRESHOLD', '0.75'))))
