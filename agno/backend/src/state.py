from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict


class TurboRefiState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    session_id: str
    use_case: str | None
    documents_received: list[str]
    documents_pending: list[str]
    mortgage_data: dict[str, Any] | None
    income_docs: list[dict[str, Any]]
    borrower_name: str | None
    income_result: dict[str, Any] | None
    ltv_result: dict[str, Any] | None
    pmi_result: dict[str, Any] | None
    rag_retrievals: list[dict[str, Any]]
    loan_recommendation_packet: dict[str, Any] | None
    current_phase: str
    error: str | None
    tool_call_history: list[dict[str, Any]]


DEFAULT_SESSION_STATE: TurboRefiState = {
    "messages": [],
    "use_case": None,
    "documents_received": [],
    "documents_pending": [],
    "mortgage_data": None,
    "income_docs": [],
    "borrower_name": None,
    "income_result": None,
    "ltv_result": None,
    "pmi_result": None,
    "rag_retrievals": [],
    "loan_recommendation_packet": None,
    "current_phase": "extraction",
    "error": None,
    "tool_call_history": [],
}

APPEND_ONLY_KEYS = {
    "messages",
    "documents_received",
    "income_docs",
    "rag_retrievals",
    "tool_call_history",
}


def build_session_state(session_id: str | None = None) -> TurboRefiState:
    state = deepcopy(DEFAULT_SESSION_STATE)
    if session_id:
        state["session_id"] = session_id
    return state


def merge_session_state(
    base: TurboRefiState | dict[str, Any] | None,
    updates: TurboRefiState | dict[str, Any] | None,
) -> TurboRefiState:
    merged: TurboRefiState = build_session_state()
    if base:
        for key, value in base.items():
            merged[key] = deepcopy(value)
    if updates:
        for key, value in updates.items():
            if key in APPEND_ONLY_KEYS and value is not None:
                existing = list(merged.get(key, []))
                existing.extend(deepcopy(value))
                merged[key] = existing
            else:
                merged[key] = deepcopy(value)
    return merged
