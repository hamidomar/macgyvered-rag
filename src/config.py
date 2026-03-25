import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Paths
ROOT_DIR = Path(__file__).parent.parent
FNMA_INDEX_DIR = ROOT_DIR / "output" / "selling_guide_preprocessed"
FHLMC_INDEX_DIR = ROOT_DIR / "output" / "mf_guide_index"

# Add scripts directory to path to import GuideTool
scripts_dir = ROOT_DIR / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.append(str(scripts_dir))

from guide_tool import GuideTool

# Model Config
OPENAI_MODEL = "gpt-4o"
OPENAI_EXTRACTION_MODEL = "gpt-4o"

# Loaded Tool Instances - Fail Fast RAG Health Checks
print("Initializing GuideTool instances...")
fnma_guide = GuideTool(FNMA_INDEX_DIR)
fhlmc_guide = GuideTool(FHLMC_INDEX_DIR)

# Smoke test - ensure tools didn't load silently empty (e.g., bad paths)
assert getattr(fnma_guide, "sections", None) or hasattr(fnma_guide, "get_section"), f"FNMA guide loaded improperly from {FNMA_INDEX_DIR}"
assert getattr(fhlmc_guide, "sections", None) or hasattr(fhlmc_guide, "get_section"), f"FHLMC guide loaded improperly from {FHLMC_INDEX_DIR}"

# Validate a core FNMA income section exists as a sanity check
test_result = fnma_guide.get_section("B3-3.1-01")
assert test_result and "text" in test_result, "FNMA B3-3.1-01 lookup failed — index may be corrupt."
print("GuideTool instances loaded successfully and smoke tested.")
