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
