from __future__ import annotations

import json

from turborefi.services.retrieval_service import RetrievalService


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


def build_guideline_tools(retrieval_service: RetrievalService):
    from agno.tools import tool

    @tool(show_result=True)
    def list_guide_contents(gse: str, path: str | None = None, agent=None, run_context=None) -> list[dict]:
        """List one level of the guide hierarchy so the agent can drill down iteratively."""
        result = retrieval_service.list_contents(gse=gse, path=path)
        _record_rag_tool(
            "list_guide_contents",
            {"gse": gse, "path": path},
            result,
            agent=agent,
            run_context=run_context,
        )
        return result

    @tool(show_result=True)
    def get_guideline_section(section_id: str, gse: str, agent=None, run_context=None) -> dict:
        """Retrieve a specific guideline section by section ID and guide type."""
        result = retrieval_service.get_section(section_id=section_id, gse=gse)
        _record_rag_tool(
            "get_guideline_section",
            {"section_id": section_id, "gse": gse},
            result,
            agent=agent,
            run_context=run_context,
        )
        return result

    @tool(show_result=True)
    def search_guideline_titles(query: str, gse: str, agent=None, run_context=None) -> list[dict]:
        """Search guideline section titles for keywords."""
        result = retrieval_service.search_titles(query=query, gse=gse)
        _record_rag_tool(
            "search_guideline_titles",
            {"query": query, "gse": gse},
            result,
            agent=agent,
            run_context=run_context,
        )
        return result

    @tool(show_result=True)
    def get_section_with_references(section_id: str, gse: str, depth: int = 1, agent=None, run_context=None) -> dict:
        """Retrieve a section and its cross-references."""
        result = retrieval_service.get_section_with_references(
            section_id=section_id,
            gse=gse,
            depth=depth,
        )
        _record_rag_tool(
            "get_section_with_references",
            {"section_id": section_id, "gse": gse, "depth": depth},
            result,
            agent=agent,
            run_context=run_context,
        )
        return result

    return [
        list_guide_contents,
        get_guideline_section,
        search_guideline_titles,
        get_section_with_references,
    ]
