import pytest
from src.config import fnma_guide, fhlmc_guide

def test_fnma_guide_integrity():
    """Verifies the Fannie Mae JSON index is properly mounted and queryable."""
    # 1. Ensure guide is loaded
    assert fnma_guide is not None, "FNMA GuideTool failed to initialize."
    
    # 2. Retrieve a known core section (General Income)
    section = fnma_guide.get_section("B3-3.1-01")
    assert section is not None, "Failed to retrieve FNMA B3-3.1-01"
    assert "text" in section, "FNMA section missing 'text' body"
    assert len(section["text"]) > 100, "FNMA section text is suspiciously short"
    
    # 3. Search sanity check
    search_results = fnma_guide.search_titles("income")
    assert len(search_results) > 0, "FNMA search returned 0 results for 'income'"

def test_fhlmc_guide_integrity():
    """Verifies the Freddie Mac JSON index is properly mounted and queryable."""
    # 1. Ensure guide is loaded
    assert fhlmc_guide is not None, "FHLMC GuideTool failed to initialize."
    
    # 2. Search sanity check
    search_results = fhlmc_guide.search_titles("income")
    assert len(search_results) > 0, "FHLMC search returned 0 results for 'income'"
    
    # 3. Retrieve the first section from the search results to test deep retrieval
    first_hit_id = search_results[0]["section_id"]
    section = fhlmc_guide.get_section(first_hit_id)
    
    assert section is not None, f"Failed to retrieve FHLMC section {first_hit_id}"
    assert "text" in section, f"FHLMC section {first_hit_id} missing 'text' body"
    assert len(section["text"]) > 10, f"FHLMC section {first_hit_id} text is suspiciously short"

def test_cross_reference_integrity():
    """Verifies that the cross-referencing engine is functioning for RAG traversal."""
    # 1. Test FNMA reference hops
    expanded = fnma_guide.get_section_with_references("B3-3.1-01")
    assert "primary" in expanded, "Expanded dict missing primary section"
    assert "sections" in expanded, "Expanded dict missing sections array"
    assert isinstance(expanded["sections"], list), "Sections is not a list"
