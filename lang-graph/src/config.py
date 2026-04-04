import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Paths
ROOT_DIR = Path(__file__).parent.parent
FNMA_INDEX_DIR = ROOT_DIR / "output" / "selling_guide_preprocessed"
FHLMC_INDEX_DIR = ROOT_DIR / "output" / "sf_guide_index"

# Add scripts directory to path to import GuideTool
scripts_dir = ROOT_DIR / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.append(str(scripts_dir))

from guide_tool import GuideTool

# Model Config
OPENAI_MODEL = "gpt-4o"
OPENAI_EXTRACTION_MODEL = "gpt-4o"

# Loaded Tool Instances
try:
    fnma_guide = GuideTool(FNMA_INDEX_DIR)
    fhlmc_guide = GuideTool(FHLMC_INDEX_DIR)
except Exception as e:
    print(f"Warning: Could not load GuideTool instances. {e}")
    fnma_guide = None
    fhlmc_guide = None
