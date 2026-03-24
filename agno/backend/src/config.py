import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
FNMA_INDEX_DIR = ROOT_DIR / "output" / "selling_guide_preprocessed"
FHLMC_INDEX_DIR = ROOT_DIR / "output" / "mf_guide_index"

TMP_DIR = ROOT_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

AGNO_DB_FILE = Path(os.getenv("AGNO_DB_FILE", TMP_DIR / "agents.db"))
AGNO_STORAGE_TABLE = os.getenv("AGNO_STORAGE_TABLE", "turborefi_loa_sessions")
AGNO_HISTORY_LENGTH = int(os.getenv("AGNO_HISTORY_LENGTH", "20"))

PLAYGROUND_HOST = os.getenv("PLAYGROUND_HOST", "0.0.0.0")
PLAYGROUND_PORT = int(os.getenv("PLAYGROUND_PORT", "7777"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_EXTRACTION_MODEL = os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-4o")

scripts_dir = ROOT_DIR / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.append(str(scripts_dir))

from guide_tool import GuideTool

try:
    fnma_guide = GuideTool(FNMA_INDEX_DIR)
    fhlmc_guide = GuideTool(FHLMC_INDEX_DIR)
except Exception as exc:
    print(f"Warning: Could not load GuideTool instances. {exc}")
    fnma_guide = None
    fhlmc_guide = None
