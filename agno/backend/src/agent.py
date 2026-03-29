from __future__ import annotations

import inspect
import os
from functools import lru_cache

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from src.config import AGNO_DB_FILE, AGNO_HISTORY_LENGTH, AGNO_STORAGE_TABLE, OPENAI_MODEL
from src.prompts.loa_system_prompt import LOA_SYSTEM_PROMPT
from src.state import build_session_state
from src.tools.calculators import calc_ltv, calc_pmi_savings, calc_se_income, calc_w2_income
from src.prompts.rag_system_prompt import RAG_SYSTEM_PROMPT
from src.tools.guide_tools import (
    get_guideline_section,
    get_section_with_references,
    list_guide_contents,
    search_guideline_titles,
)

try:
    from agno.db.sqlite import SqliteDb
except ImportError:
    SqliteDb = None

try:
    from agno.storage.agent.sqlite import SqliteAgentStorage
except ImportError:
    SqliteAgentStorage = None

try:
    from agno.storage.sqlite import SqliteStorage
except ImportError:
    SqliteStorage = None


TOOLS = [
    list_guide_contents,
    get_guideline_section,
    search_guideline_titles,
    get_section_with_references,
    calc_w2_income,
    calc_ltv,
    calc_pmi_savings,
    calc_se_income,
]


def _build_model() -> OpenAIChat:
    model_params = inspect.signature(OpenAIChat).parameters
    kwargs = {"id": OPENAI_MODEL}
    if "temperature" in model_params:
        kwargs["temperature"] = 0
    if "api_key" in model_params and os.getenv("OPENAI_API_KEY"):
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
    return OpenAIChat(**kwargs)


def _build_storage_kwargs(agent_params: dict[str, inspect.Parameter]) -> dict:
    if "db" in agent_params and SqliteDb is not None:
        return {"db": SqliteDb(db_file=str(AGNO_DB_FILE))}

    if "storage" in agent_params:
        if SqliteAgentStorage is not None:
            storage_params = inspect.signature(SqliteAgentStorage).parameters
            storage_kwargs = {
                "db_file": str(AGNO_DB_FILE),
            }
            if "table_name" in storage_params:
                storage_kwargs["table_name"] = AGNO_STORAGE_TABLE
            if "auto_upgrade_schema" in storage_params:
                storage_kwargs["auto_upgrade_schema"] = True
            return {
                "storage": SqliteAgentStorage(**storage_kwargs)
            }
        if SqliteStorage is not None:
            storage_params = inspect.signature(SqliteStorage).parameters
            storage_kwargs = {
                "db_file": str(AGNO_DB_FILE),
            }
            if "table_name" in storage_params:
                storage_kwargs["table_name"] = AGNO_STORAGE_TABLE
            if "auto_upgrade_schema" in storage_params:
                storage_kwargs["auto_upgrade_schema"] = True
            return {
                "storage": SqliteStorage(**storage_kwargs)
            }

    return {}


@lru_cache(maxsize=1)
def get_loa_agent() -> Agent:
    agent_params = inspect.signature(Agent).parameters
    kwargs = {
        "name": "TurboRefi LOA",
        "model": _build_model(),
        "description": "Loan officer agent for refinance assessment across FNMA and FHLMC.",
        "instructions": [LOA_SYSTEM_PROMPT],
        "tools": TOOLS,
        "session_state": build_session_state(),
        "markdown": True,
    }
    if "show_tool_calls" in agent_params:
        kwargs["show_tool_calls"] = True
    if "debug_mode" in agent_params:
        kwargs["debug_mode"] = True

    kwargs.update(_build_storage_kwargs(agent_params))

    if "id" in agent_params:
        kwargs["id"] = "turborefi-loa"
    elif "agent_id" in agent_params:
        kwargs["agent_id"] = "turborefi-loa"

    if "tool_call_limit" in agent_params:
        kwargs["tool_call_limit"] = 20

    if "search_knowledge" in agent_params:
        kwargs["search_knowledge"] = False
    if "add_search_knowledge_instructions" in agent_params:
        kwargs["add_search_knowledge_instructions"] = False
    if "store_history_messages" in agent_params:
        kwargs["store_history_messages"] = True

    if "add_history_to_messages" in agent_params:
        kwargs["add_history_to_messages"] = True
        if "num_history_responses" in agent_params:
            kwargs["num_history_responses"] = AGNO_HISTORY_LENGTH
        elif "num_history_runs" in agent_params:
            kwargs["num_history_runs"] = AGNO_HISTORY_LENGTH
    elif "add_history_to_context" in agent_params:
        kwargs["add_history_to_context"] = True
        if "num_history_runs" in agent_params:
            kwargs["num_history_runs"] = AGNO_HISTORY_LENGTH

    if "add_session_state_to_context" in agent_params:
        kwargs["add_session_state_to_context"] = True

    return Agent(**kwargs)


RAG_TOOLS = [
    list_guide_contents,
    get_guideline_section,
    search_guideline_titles,
    get_section_with_references,
]


@lru_cache(maxsize=1)
def get_rag_agent() -> Agent:
    agent_params = inspect.signature(Agent).parameters
    kwargs = {
        "name": "Guide Expert (RAG)",
        "model": _build_model(),
        "description": "Agent for querying FNMA and FHLMC guidelines directly. Explores the TOC and fetches guidelines.",
        "instructions": [RAG_SYSTEM_PROMPT],
        "tools": RAG_TOOLS,
        "markdown": True,
    }
    if "show_tool_calls" in agent_params:
        kwargs["show_tool_calls"] = True

    kwargs.update(_build_storage_kwargs(agent_params))

    if "id" in agent_params:
        kwargs["id"] = "guide-expert-rag"
    elif "agent_id" in agent_params:
        kwargs["agent_id"] = "guide-expert-rag"

    if "store_history_messages" in agent_params:
        kwargs["store_history_messages"] = True

    if "add_history_to_messages" in agent_params:
        kwargs["add_history_to_messages"] = True
        if "num_history_responses" in agent_params:
            kwargs["num_history_responses"] = AGNO_HISTORY_LENGTH
        elif "num_history_runs" in agent_params:
            kwargs["num_history_runs"] = AGNO_HISTORY_LENGTH
    elif "add_history_to_context" in agent_params:
        kwargs["add_history_to_context"] = True
        if "num_history_runs" in agent_params:
            kwargs["num_history_runs"] = AGNO_HISTORY_LENGTH

    return Agent(**kwargs)
