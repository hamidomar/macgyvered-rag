from __future__ import annotations

from typing import Any

from turborefi.agents.common import build_base_agent_kwargs
from turborefi.config import Settings
from turborefi.prompts import LOA_INSTRUCTIONS
from turborefi.services.retrieval_service import RetrievalService
from turborefi.services.session_state import session_to_agent_state
from turborefi.schemas import SessionState
from turborefi.tools.calculators import build_calculator_tools
from turborefi.tools.document_tools import build_document_tools
from turborefi.tools.guideline_tools import build_guideline_tools


def build_loan_officer_agent(
    settings: Settings,
    retrieval_service: RetrievalService,
    session_state: SessionState | None = None,
    response_model: type[Any] | None = None,
):
    from agno.agent import Agent

    tools = [
        *build_guideline_tools(retrieval_service),
        *build_document_tools(),
        *build_calculator_tools(),
    ]
    agent_kwargs = build_base_agent_kwargs(
        settings=settings,
        name="TurboRefi LOA",
        description="TurboRefi loan officer for refinance assessments and borrower Q&A.",
        model_id=settings.openai_model_loa,
        instructions=LOA_INSTRUCTIONS,
        tools=tools,
        session_state=session_to_agent_state(session_state) if session_state is not None else {},
        response_model=response_model,
    )
    return Agent(**agent_kwargs)
