from __future__ import annotations

import inspect
import os
from typing import Any

from turborefi.config import Settings


def build_openai_chat(model_id: str):
    from agno.models.openai import OpenAIChat

    model_params = inspect.signature(OpenAIChat).parameters
    kwargs: dict[str, Any] = {"id": model_id}
    if "temperature" in model_params:
        kwargs["temperature"] = 0
    if "api_key" in model_params and os.getenv("OPENAI_API_KEY"):
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
    return OpenAIChat(**kwargs)


def build_storage_kwargs(settings: Settings, agent_params: dict[str, inspect.Parameter]) -> dict[str, Any]:
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

    if "db" in agent_params and SqliteDb is not None:
        return {"db": SqliteDb(db_file=str(settings.agno_storage_db))}

    if "storage" in agent_params:
        if SqliteAgentStorage is not None:
            storage_params = inspect.signature(SqliteAgentStorage).parameters
            storage_kwargs: dict[str, Any] = {"db_file": str(settings.agno_storage_db)}
            if "auto_upgrade_schema" in storage_params:
                storage_kwargs["auto_upgrade_schema"] = True
            return {"storage": SqliteAgentStorage(**storage_kwargs)}
        if SqliteStorage is not None:
            storage_params = inspect.signature(SqliteStorage).parameters
            storage_kwargs = {"db_file": str(settings.agno_storage_db)}
            if "auto_upgrade_schema" in storage_params:
                storage_kwargs["auto_upgrade_schema"] = True
            return {"storage": SqliteStorage(**storage_kwargs)}
    return {}


def build_base_agent_kwargs(
    *,
    settings: Settings,
    name: str,
    description: str,
    model_id: str,
    instructions: list[str],
    tools: list[Any],
    session_state: dict[str, Any] | None = None,
    response_model: type[Any] | None = None,
) -> dict[str, Any]:
    from agno.agent import Agent

    agent_params = inspect.signature(Agent).parameters
    kwargs: dict[str, Any] = {
        "name": name,
        "description": description,
        "model": build_openai_chat(model_id),
        "instructions": instructions,
        "tools": tools,
        "markdown": True,
    }

    if session_state is not None and "session_state" in agent_params:
        kwargs["session_state"] = session_state

    kwargs.update(build_storage_kwargs(settings, agent_params))

    if "store_history_messages" in agent_params:
        kwargs["store_history_messages"] = True

    if "add_history_to_messages" in agent_params:
        kwargs["add_history_to_messages"] = True
        if "num_history_responses" in agent_params:
            kwargs["num_history_responses"] = settings.agno_history_length
        elif "num_history_runs" in agent_params:
            kwargs["num_history_runs"] = settings.agno_history_length
    elif "add_history_to_context" in agent_params:
        kwargs["add_history_to_context"] = True
        if "num_history_runs" in agent_params:
            kwargs["num_history_runs"] = settings.agno_history_length

    if "add_session_state_to_context" in agent_params:
        kwargs["add_session_state_to_context"] = True

    if "show_tool_calls" in agent_params:
        kwargs["show_tool_calls"] = True

    if "use_json_mode" in agent_params:
        kwargs["use_json_mode"] = True

    if response_model is not None and "output_schema" in agent_params:
        kwargs["output_schema"] = response_model

    return kwargs
