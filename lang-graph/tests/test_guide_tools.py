import json
from src.tools.guide_tools import (
    get_guideline_section,
    search_guideline_titles,
    list_guide_contents,
    get_section_with_references
)

def test_get_guideline_section():
    res = get_guideline_section.invoke({"section_id": "B3-3.1-01", "gse": "fnma"})
    assert isinstance(res, str)
    data = json.loads(res)
    assert "error" in data or "section_id" in data or "title" in data

def test_search_guideline_titles():
    res = search_guideline_titles.invoke({"query": "income", "gse": "fnma"})
    data = json.loads(res)
    assert isinstance(data, (list, dict))

def test_list_guide_contents():
    res = list_guide_contents.invoke({"path": "", "gse": "fhlmc"})
    data = json.loads(res)
    assert isinstance(data, (list, dict))

def test_get_section_with_references():
    res = get_section_with_references.invoke({"section_id": "B3-3.1-01", "gse": "fnma"})
    data = json.loads(res)
    assert isinstance(data, dict)
