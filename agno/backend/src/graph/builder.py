from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from src.runtime import TurboRefiSessionService


@dataclass
class SessionSnapshot:
    values: dict[str, Any]


class AgnoGraphCompat:
    """
    Lightweight compatibility wrapper so the copied tests and old API shape
    can keep calling `build_graph().invoke(...)` while the runtime is now Agno.
    """

    def __init__(self) -> None:
        self.service = TurboRefiSessionService()

    def invoke(self, state: dict[str, Any], config: dict | None = None) -> dict[str, Any]:
        config = config or {}
        thread_id = config.get("configurable", {}).get("thread_id")
        session_id = state.get("session_id") or thread_id
        if not session_id:
            raise ValueError("A session_id or configurable.thread_id is required.")

        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None
        content = getattr(last_message, "content", last_message) if last_message is not None else ""

        response_text, session_state = self.service.run_message_with_state(
            session_id=session_id,
            message=str(content),
            state_updates={k: v for k, v in state.items() if k != "messages"},
        )
        return {
            **session_state,
            "messages": [SimpleNamespace(content=response_text)],
        }

    def get_state(self, config: dict | None = None) -> SessionSnapshot:
        config = config or {}
        session_id = config.get("configurable", {}).get("thread_id")
        if not session_id:
            raise ValueError("configurable.thread_id is required.")
        return SessionSnapshot(values=self.service.get_state(session_id))


def build_graph():
    return AgnoGraphCompat()
