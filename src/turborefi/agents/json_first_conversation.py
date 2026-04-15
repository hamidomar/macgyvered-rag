from __future__ import annotations

from turborefi.agents.common import build_base_agent_kwargs
from turborefi.config import Settings
from turborefi.prompts import JSON_FIRST_CONVERSATION_INSTRUCTIONS


def build_json_first_conversation_agent(settings: Settings):
    from agno.agent import Agent

    agent_kwargs = build_base_agent_kwargs(
        settings=settings,
        name="TurboRefi JSON-First Conversation",
        description="Borrower-facing conversational layer for the JSON-first UC1/UC2 screening workflow.",
        model_id=settings.openai_model_loa,
        instructions=JSON_FIRST_CONVERSATION_INSTRUCTIONS,
        tools=[],
        session_state={},
    )
    agent_kwargs.pop("use_json_mode", None)
    agent_kwargs.pop("show_tool_calls", None)
    return Agent(**agent_kwargs)
