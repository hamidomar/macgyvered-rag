from __future__ import annotations

import json

from turborefi.agents.common import build_base_agent_kwargs
from turborefi.config import Settings
from turborefi.prompts import RUNNER_INSTRUCTIONS
from turborefi.workflow import TurboRefiWorkflow


def build_runner_agent(settings: Settings, workflow: TurboRefiWorkflow):
    from agno.agent import Agent
    from agno.tools import tool

    @tool(show_result=True)
    def list_mock_cases() -> list[str]:
        """List the available mock TurboRefi cases for playground testing."""
        return workflow.list_cases()

    @tool(show_result=True)
    def show_case(case_id: str) -> dict:
        """Show a high-level summary for a mock case."""
        return workflow.get_case_summary(case_id)

    @tool(show_result=True)
    def run_fixture_assessment(case_id: str) -> str:
        """Run the LOA fixture assessment flow for a mock case and return JSON."""
        result = workflow.run_fixture_assessment(case_id)
        return json.dumps(result, indent=2, default=str)

    @tool(show_result=True)
    def run_fixture_verification(case_id: str) -> str:
        """Run the deterministic verification flow for a mock case and return JSON."""
        result = workflow.run_fixture_verification(case_id)
        return json.dumps(result, indent=2, default=str)

    agent_kwargs = build_base_agent_kwargs(
        settings=settings,
        name="TurboRefi Runner",
        description="Local runner for TurboRefi fixtures and verification flows.",
        model_id=settings.openai_model_loa,
        instructions=RUNNER_INSTRUCTIONS,
        tools=[list_mock_cases, show_case, run_fixture_assessment, run_fixture_verification],
        session_state={},
    )
    return Agent(**agent_kwargs)
