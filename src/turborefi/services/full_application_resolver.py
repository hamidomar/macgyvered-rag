from __future__ import annotations

import inspect
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from turborefi.config import Settings
from turborefi.schemas import SessionState


logger = logging.getLogger(__name__)

FullApplicationIntent = Literal["proceed", "decline", "unclear"]

FULL_APPLICATION_AGENT_INSTRUCTIONS = [
    "You resolve the borrower's intent for the TurboRefi full-application decision step.",
    "Only classify intent when the preliminary screen is already automated-ready and all required documents are complete.",
    "Use the resolve_full_application_intent tool exactly once.",
    "Valid intents are: proceed, decline, unclear.",
    "Choose proceed when the borrower is clearly agreeing to move forward with the full application.",
    "Choose decline when the borrower is clearly declining or postponing the full application for now.",
    "Choose unclear when the message asks a question, is ambiguous, or does not clearly decide.",
    "Do not output narrative outside the tool call.",
]


@dataclass
class FullApplicationDecisionResolution:
    state: SessionState
    intent: FullApplicationIntent = "unclear"
    confidence: float = 0.0
    tool_trace: list[dict[str, Any]] = field(default_factory=list)


class FullApplicationResolver(Protocol):
    def resolve(
        self,
        state: SessionState,
        message: str,
    ) -> FullApplicationDecisionResolution: ...


def is_full_application_decision_pending(state: SessionState) -> bool:
    return (
        state.lars_result is not None
        and state.lars_result.decision == "AUTOMATED"
        and not state.missing_documents
        and state.handoff_package is None
        and state.full_application_intent is None
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _intent_from_message(message: str) -> tuple[FullApplicationIntent, float]:
    normalized = _normalize_text(message)
    if not normalized:
        return "unclear", 0.0

    proceed_patterns = (
        r"\b(yes|yep|yeah|sure|okay|ok)\b",
        r"\b(proceed|continue|move forward|go ahead)\b",
        r"\b(let'?s do it|let'?s proceed|sounds good|works for me)\b",
        r"\b(i want to apply|i'm ready to apply|ready to proceed)\b",
    )
    decline_patterns = (
        r"\b(no|nope|nah)\b",
        r"\b(not now|maybe later|later on|hold off|wait)\b",
        r"\b(do not proceed|don't proceed|do not continue|don't continue)\b",
        r"\b(not ready|not interested|stop here)\b",
    )
    question_patterns = (
        r"\?",
        r"\b(what happens next|what does that mean|can you explain|how does that work)\b",
    )

    if any(re.search(pattern, normalized) for pattern in question_patterns):
        return "unclear", 0.75
    if any(re.search(pattern, normalized) for pattern in decline_patterns):
        return "decline", 0.9
    if any(re.search(pattern, normalized) for pattern in proceed_patterns):
        return "proceed", 0.9
    return "unclear", 0.35


class DeterministicFullApplicationResolver:
    def resolve(
        self,
        state: SessionState,
        message: str,
    ) -> FullApplicationDecisionResolution:
        intent, confidence = _intent_from_message(message)
        resolution = FullApplicationDecisionResolution(
            state=state,
            intent=intent,
            confidence=confidence,
        )
        resolution.tool_trace.append(
            {
                "tool": "resolve_full_application_intent",
                "arguments": {
                    "message": message,
                    "scope": "automated_ready_full_application_decision",
                },
                "result": {
                    "intent": intent,
                    "confidence": confidence,
                    "source": "deterministic_semantic_fallback",
                },
            }
        )
        return resolution


class AgenticFullApplicationResolver:
    def __init__(
        self,
        settings: Settings,
        *,
        fallback: FullApplicationResolver | None = None,
    ) -> None:
        self.settings = settings
        self.fallback = fallback or DeterministicFullApplicationResolver()

    def resolve(
        self,
        state: SessionState,
        message: str,
    ) -> FullApplicationDecisionResolution:
        if not os.getenv("OPENAI_API_KEY"):
            return self.fallback.resolve(state, message)

        resolution = FullApplicationDecisionResolution(state=state)
        try:
            from agno.agent import Agent
            from agno.tools import tool
            from turborefi.agents.common import build_openai_chat
        except Exception:
            logger.exception("Agno is unavailable for full-application intent resolution")
            return self.fallback.resolve(state, message)

        @tool(show_result=True)
        def resolve_full_application_intent(
            intent: str,
            confidence: float = 1.0,
            evidence: str = "",
        ) -> dict[str, Any]:
            normalized_intent = intent.strip().lower()
            if normalized_intent not in {"proceed", "decline", "unclear"}:
                normalized_intent = "unclear"
            resolution.intent = normalized_intent
            resolution.confidence = confidence
            resolution.tool_trace.append(
                {
                    "tool": "resolve_full_application_intent",
                    "arguments": {
                        "message": message,
                        "scope": "automated_ready_full_application_decision",
                    },
                    "result": {
                        "intent": normalized_intent,
                        "confidence": confidence,
                        "evidence": evidence or message,
                        "source": "agentic_structured_extractor",
                    },
                }
            )
            return resolution.tool_trace[-1]["result"]

        agent_kwargs: dict[str, Any] = {
            "name": "TurboRefi Full Application Resolver",
            "description": "Resolve proceed/decline/unclear intent for the full application decision step.",
            "model": build_openai_chat(self.settings.openai_model_loa),
            "instructions": FULL_APPLICATION_AGENT_INSTRUCTIONS,
            "tools": [resolve_full_application_intent],
            "markdown": False,
        }
        agent_params = inspect.signature(Agent).parameters
        if "session_state" in agent_params:
            agent_kwargs["session_state"] = state.model_dump(mode="json")
        if "add_session_state_to_context" in agent_params:
            agent_kwargs["add_session_state_to_context"] = True
        if "show_tool_calls" in agent_params:
            agent_kwargs["show_tool_calls"] = True

        agent = Agent(**agent_kwargs)
        prompt = (
            f"Borrower message:\n{message}\n\n"
            "Current decision step: automated-ready preliminary screen with all required docs collected.\n"
            "Resolve only whether the borrower wants to proceed to the full application."
        )
        try:
            agent.run(prompt)
        except Exception:
            logger.exception("Agentic full-application intent resolution failed")
            return self.fallback.resolve(state, message)

        if not resolution.tool_trace:
            return self.fallback.resolve(state, message)
        return resolution
