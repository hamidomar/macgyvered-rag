import json
from langchain_core.tools import tool
from src.config import fnma_guide, fhlmc_guide

@tool
def get_guideline_section(section_id: str, gse: str) -> str:
    """Retrieve the full text of a specific guideline section by ID.

    Args:
        section_id: The section identifier.
                    FNMA examples: "B3-3.1-01", "B2-1.3-01"
                    FHLMC examples: "1.3", "17.2", "1.3.a"
        gse: Which guide to search — "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        return json.dumps({"error": f"GuideTool for {gse.upper()} is not loaded."})
    
    result = guide.get_section(section_id)
    return json.dumps(result, indent=2)

@tool
def search_guideline_titles(query: str, gse: str) -> str:
    """Search section titles by keyword across a guide.

    Args:
        query: Space-separated keywords (AND logic). E.g. "income verification W2"
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        return json.dumps({"error": f"GuideTool for {gse.upper()} is not loaded."})
    
    results = guide.search_titles(query)
    return json.dumps(results[:20], indent=2)

@tool
def list_guide_contents(path: str, gse: str) -> str:
    """Show one level of the guide hierarchy for navigation.

    Args:
        path: A nav_id to drill into, or empty string for top level.
              FNMA examples: "A", "A2", "A2-1"
              FHLMC examples: "01", "1.3"
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        return json.dumps({"error": f"GuideTool for {gse.upper()} is not loaded."})
    
    results = guide.list_contents(path if path else None)
    return json.dumps(results, indent=2)

@tool
def get_section_with_references(section_id: str, gse: str) -> str:
    """Retrieve a section AND all sections it references (1 hop).

    Args:
        section_id: The section to expand
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        return json.dumps({"error": f"GuideTool for {gse.upper()} is not loaded."})
    
    result = guide.get_section_with_references(section_id)
    return json.dumps(result, indent=2)
