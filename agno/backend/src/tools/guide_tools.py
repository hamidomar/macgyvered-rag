import json

from src.config import fnma_guide, fhlmc_guide


def _get_state(agent=None, run_context=None):
    if run_context is not None and getattr(run_context, "session_state", None) is not None:
        return run_context.session_state
    if agent is not None and getattr(agent, "session_state", None) is not None:
        return agent.session_state
    return None


def _json_safe(value):
    try:
        return json.loads(json.dumps(value))
    except TypeError:
        return str(value)


def _record_rag_tool(tool_name: str, arguments: dict, result, agent=None, run_context=None) -> None:
    state = _get_state(agent=agent, run_context=run_context)
    if state is None:
        return

    state.setdefault("rag_retrievals", [])
    state.setdefault("tool_call_history", [])
    entry = {
        "tool": tool_name,
        "arguments": _json_safe(arguments),
        "result": _json_safe(result),
    }
    state["rag_retrievals"].append(entry)
    state["tool_call_history"].append(entry)


def get_guideline_section(section_id: str, gse: str, agent=None, run_context=None) -> str:
    """Retrieve the full text of a specific guideline section by ID.

    Args:
        section_id: The section identifier.
                    FNMA examples: "B3-3.1-01", "B2-1.3-01"
                    FHLMC examples: "5302.2", "1101.1"
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        result = {"error": f"GuideTool for {gse.upper()} is not loaded."}
        _record_rag_tool(
            "get_guideline_section",
            {"section_id": section_id, "gse": gse},
            result,
            agent=agent,
            run_context=run_context,
        )
        return json.dumps(result)
    
    result = guide.get_section(section_id)
    _record_rag_tool(
        "get_guideline_section",
        {"section_id": section_id, "gse": gse},
        result,
        agent=agent,
        run_context=run_context,
    )
    return json.dumps(result, indent=2)


def search_guideline_titles(query: str, gse: str, agent=None, run_context=None) -> str:
    """Search section titles by keyword across a guide.

    Args:
        query: Space-separated keywords (AND logic). E.g. "income verification W2"
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        result = {"error": f"GuideTool for {gse.upper()} is not loaded."}
        _record_rag_tool(
            "search_guideline_titles",
            {"query": query, "gse": gse},
            result,
            agent=agent,
            run_context=run_context,
        )
        return json.dumps(result)
    
    results = guide.search_titles(query)
    _record_rag_tool(
        "search_guideline_titles",
        {"query": query, "gse": gse},
        results[:20],
        agent=agent,
        run_context=run_context,
    )
    return json.dumps(results[:20], indent=2)


def list_guide_contents(path: str, gse: str, agent=None, run_context=None) -> str:
    """Show one level of the guide hierarchy for navigation.

    Args:
        path: A nav_id to drill into, or empty string for top level.
              FNMA examples: "A", "A2", "A2-1"
              FHLMC examples: "1000", "5300", "5302"
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        result = {"error": f"GuideTool for {gse.upper()} is not loaded."}
        _record_rag_tool(
            "list_guide_contents",
            {"path": path, "gse": gse},
            result,
            agent=agent,
            run_context=run_context,
        )
        return json.dumps(result)
    
    results = guide.list_contents(path if path else None)
    _record_rag_tool(
        "list_guide_contents",
        {"path": path, "gse": gse},
        results,
        agent=agent,
        run_context=run_context,
    )
    return json.dumps(results, indent=2)


def get_section_with_references(section_id: str, gse: str, agent=None, run_context=None) -> str:
    """Retrieve a section AND all sections it references (1 hop).

    Args:
        section_id: The section to expand
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    if guide is None:
        result = {"error": f"GuideTool for {gse.upper()} is not loaded."}
        _record_rag_tool(
            "get_section_with_references",
            {"section_id": section_id, "gse": gse},
            result,
            agent=agent,
            run_context=run_context,
        )
        return json.dumps(result)
    
    result = guide.get_section_with_references(section_id)
    _record_rag_tool(
        "get_section_with_references",
        {"section_id": section_id, "gse": gse},
        result,
        agent=agent,
        run_context=run_context,
    )
    return json.dumps(result, indent=2)
