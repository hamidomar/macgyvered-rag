from __future__ import annotations

from collections import Counter
import json
import re
import uuid
from inspect import signature
from typing import Any

from src.agent import get_loa_agent
from src.graph.nodes import (
    build_enforce_rag_message,
    extract_mortgage_statement,
    extract_secondary_documents,
    should_enforce_rag,
)
from src.state import TurboRefiState, build_session_state, merge_session_state


def _response_text(run_response: Any) -> str:
    for attr in ("content", "response", "text"):
        value = getattr(run_response, attr, None)
        if isinstance(value, str):
            return value
    return str(run_response)


def _extract_json_block(content: str) -> dict[str, Any] | None:
    stripped = content.strip()
    candidates = [stripped]

    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    candidates.extend(reversed(fenced))

    if "{" in content and "}" in content:
        candidates.append(content[content.find("{") : content.rfind("}") + 1])

    for candidate in candidates:
        try:
            packet = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(packet, dict) and (
            {"borrower_name", "qualifying_monthly_income"}.issubset(packet.keys())
            or {"borrower_name", "use_case", "fnma_eligible"}.issubset(packet.keys())
        ):
            return packet
    return None


def _explicit_retrieval_gses(state: TurboRefiState) -> set[str]:
    gses: set[str] = set()
    for entry in state.get("rag_retrievals", []):
        if entry.get("tool") not in {"get_guideline_section", "get_section_with_references"}:
            continue
        arguments = entry.get("arguments", {})
        gse = arguments.get("gse")
        if isinstance(gse, str):
            gses.add(gse)
    return gses


def _missing_required_documents(state: TurboRefiState) -> list[str]:
    received = Counter(state.get("documents_received", []))

    # Current supported salaried path: 2 paystubs + 1 W-2 before assessment.
    if received["paystub"] > 0 or received["w2"] > 0:
        missing: list[str] = []
        if received["paystub"] < 2:
            missing.extend(["paystub"] * (2 - received["paystub"]))
        if received["w2"] < 1:
            missing.append("w2")
        return missing

    return []


def _format_missing_documents(missing_documents: list[str]) -> str:
    missing = Counter(missing_documents)
    labels: list[str] = []
    if missing["paystub"] == 2:
        labels.append("2 recent paystubs")
    elif missing["paystub"] == 1:
        labels.append("1 more recent paystub")
    if missing["w2"] == 1:
        labels.append("the most recent W-2")
    return ", ".join(labels)


def _build_missing_documents_message(state: TurboRefiState, missing_documents: list[str]) -> str:
    received = Counter(state.get("documents_received", []))
    already_received: list[str] = []
    if received["w2"] > 0:
        already_received.append("the W-2")
    if received["paystub"] > 0:
        already_received.append(
            "1 paystub" if received["paystub"] == 1 else f"{received['paystub']} paystubs"
        )

    prefix = "I’ve received " + " and ".join(already_received) + ", but " if already_received else ""
    return (
        f"{prefix}I cannot proceed to eligibility yet. "
        f"For a salaried/W-2 borrower, I still need {_format_missing_documents(missing_documents)} "
        "before assessment, per FNMA B3-3.2-01. "
        "Please upload the remaining required documents and then I’ll continue."
    )


def _normalize_packet(packet: dict[str, Any], state: TurboRefiState) -> dict[str, Any]:
    normalized = dict(packet)

    borrower_name = state.get("borrower_name")
    if borrower_name:
        normalized["borrower_name"] = borrower_name

    income_result = state.get("income_result")
    if income_result:
        if "monthly_qualifying" in income_result:
            normalized["qualifying_monthly_income"] = income_result["monthly_qualifying"]
        elif "qualifying_monthly" in income_result:
            normalized["qualifying_monthly_income"] = income_result["qualifying_monthly"]

    ltv_result = state.get("ltv_result")
    if ltv_result and "ltv_percent" in ltv_result:
        normalized["ltv_percent"] = ltv_result["ltv_percent"]

    documentation_status = dict(normalized.get("documentation_status") or {})
    if documentation_status:
        documentation_status["received"] = state.get("documents_received", [])
        documentation_status["pending"] = state.get("documents_pending", [])
        normalized["documentation_status"] = documentation_status

    return normalized


def _packet_validation_errors(packet: dict[str, Any], state: TurboRefiState) -> list[str]:
    errors: list[str] = []

    missing_documents = _missing_required_documents(state)
    if missing_documents:
        errors.append(
            "Missing required supporting documents: "
            + _format_missing_documents(missing_documents)
            + "."
        )

    if state.get("income_result") is None:
        errors.append("Missing income calculator output from calc_w2_income or calc_se_income.")
    if state.get("ltv_result") is None:
        errors.append("Missing LTV calculator output from calc_ltv.")

    retrieved_gses = _explicit_retrieval_gses(state)
    if "fnma" not in retrieved_gses:
        errors.append("Missing an explicit FNMA guideline retrieval via get_guideline_section or get_section_with_references.")

    borrower_name = state.get("borrower_name")
    if borrower_name and packet.get("borrower_name") != borrower_name:
        errors.append("Borrower name does not match the extracted mortgage statement data.")

    return errors


def _build_packet_enforcement_message(errors: list[str]) -> str:
    bullet_list = "\n".join(f"- {error}" for error in errors)
    return (
        "[SYSTEM: Orchestration Enforcement]\n"
        "Do not finalize yet. The draft packet is invalid for these reasons:\n"
        f"{bullet_list}\n"
        "You must fix the gaps by requesting any missing documents and/or calling the required retrieval and calculator tools. "
        "Only return the final JSON packet after every gap is resolved."
    )


class TurboRefiSessionService:
    def __init__(self, agent=None) -> None:
        self.agent = agent or get_loa_agent()

    def _raw_session_state(self, session_id: str) -> TurboRefiState | dict[str, Any] | None:
        get_state_fn = getattr(self.agent, "get_session_state", None)
        if not callable(get_state_fn):
            return None
        try:
            try:
                return get_state_fn(session_id=session_id)
            except TypeError:
                return get_state_fn(session_id)
        except Exception as exc:
            if "session not found" in str(exc).lower():
                return None
            raise

    def session_exists(self, session_id: str) -> bool:
        stored = self._raw_session_state(session_id)
        return stored is not None

    def _update_session_state(self, session_id: str, updates: dict[str, Any]) -> TurboRefiState:
        if not updates:
            return self.get_state(session_id)

        merged_state = merge_session_state(self.get_state(session_id), updates)
        update_fn = getattr(self.agent, "update_session_state", None)
        if callable(update_fn):
            params = signature(update_fn).parameters
            if "session_state_updates" in params:
                update_fn(session_id=session_id, session_state_updates=merged_state)
            else:
                update_fn(session_id, merged_state)
        return merged_state

    def get_state(self, session_id: str) -> TurboRefiState:
        state = build_session_state(session_id)
        stored = self._raw_session_state(session_id)
        if stored:
            state = merge_session_state(state, stored)
        return state

    def _run_agent(self, session_id: str, message: str, state_updates: dict[str, Any] | None = None):
        if state_updates:
            existing_state = self._raw_session_state(session_id)
            if existing_state is None:
                session_state = merge_session_state(build_session_state(session_id), state_updates)
            else:
                session_state = merge_session_state(self.get_state(session_id), state_updates)
        else:
            session_state = self.get_state(session_id)
        return self.agent.run(message, session_id=session_id, session_state=session_state)

    def _finalize_run(
        self,
        session_id: str,
        response_text: str,
        preferred_phase: str | None = None,
        allow_rag_enforcement: bool = True,
    ) -> tuple[str, TurboRefiState]:
        state = self.get_state(session_id)
        missing_documents = _missing_required_documents(state)

        if missing_documents:
            updates = {
                "documents_pending": missing_documents,
                "current_phase": "awaiting_docs",
            }
            state = self._update_session_state(session_id, updates)
            return _build_missing_documents_message(state, missing_documents), state

        if allow_rag_enforcement and should_enforce_rag(response_text, state):
            rerun = self._run_agent(session_id, build_enforce_rag_message())
            response_text = _response_text(rerun)
            state = self.get_state(session_id)

        updates: dict[str, Any] = {}
        if preferred_phase and state.get("current_phase") != "complete":
            updates["current_phase"] = preferred_phase

        packet = _extract_json_block(response_text)
        if packet:
            packet = _normalize_packet(packet, state)
            validation_errors = _packet_validation_errors(packet, state)
            if validation_errors:
                if allow_rag_enforcement:
                    rerun = self._run_agent(session_id, _build_packet_enforcement_message(validation_errors))
                    response_text = _response_text(rerun)
                    state = self.get_state(session_id)
                    packet = _extract_json_block(response_text)
                    if packet:
                        packet = _normalize_packet(packet, state)
                        validation_errors = _packet_validation_errors(packet, state)

                if validation_errors:
                    updates["current_phase"] = "assessment"
                    if updates:
                        state = self._update_session_state(session_id, updates)
                    return _build_packet_enforcement_message(validation_errors), state

            updates["loan_recommendation_packet"] = packet
            updates["borrower_name"] = packet.get("borrower_name")
            updates["use_case"] = packet.get("use_case")
            updates["documents_pending"] = []
            updates["current_phase"] = "complete"
            response_text = json.dumps(packet, indent=2)

        if updates:
            state = self._update_session_state(session_id, updates)
        return response_text, state

    def create_session_from_mortgage_data(
        self, extracted_data: dict[str, Any], session_id: str | None = None
    ) -> tuple[str, str, TurboRefiState]:
        session_id = session_id or str(uuid.uuid4())
        initial_updates = merge_session_state(
            build_session_state(session_id),
            {
                "documents_received": ["mortgage_statement"],
                "documents_pending": [],
                "mortgage_data": extracted_data,
                "borrower_name": extracted_data.get("borrower_name"),
                **extract_mortgage_statement({}),
            },
        )
        message = f"[SYSTEM: Document received - mortgage_statement]\n{json.dumps(extracted_data, indent=2)}"
        run_response = self._run_agent(session_id, message, state_updates=initial_updates)
        response_text = _response_text(run_response)
        response_text, state = self._finalize_run(session_id, response_text, preferred_phase="greeting")
        return session_id, response_text, state

    def upload_secondary_document(
        self, session_id: str, doc_type: str, extracted_data: dict[str, Any]
    ) -> tuple[str, TurboRefiState]:
        state_updates = {
            "documents_received": [doc_type],
            "income_docs": [extracted_data],
        }
        validation_state = merge_session_state(self.get_state(session_id), state_updates)
        missing_documents = _missing_required_documents(validation_state)
        if missing_documents:
            updates = {
                "documents_received": [doc_type],
                "income_docs": [extracted_data],
                "documents_pending": missing_documents,
                "current_phase": "awaiting_docs",
            }
            state = self._update_session_state(session_id, updates)
            return _build_missing_documents_message(state, missing_documents), state

        validation_result = extract_secondary_documents(validation_state)
        preferred_phase = validation_result.get("current_phase", "assessment")

        if validation_result.get("message_content"):
            message = validation_result["message_content"]
        else:
            message = f"[SYSTEM: Document received - {doc_type}]\n{json.dumps(extracted_data, indent=2)}"

        run_response = self._run_agent(
            session_id,
            message,
            state_updates=merge_session_state(state_updates, {"current_phase": preferred_phase}),
        )
        response_text = _response_text(run_response)
        return self._finalize_run(session_id, response_text, preferred_phase=preferred_phase)

    def send_message(self, session_id: str, message: str) -> tuple[str, TurboRefiState]:
        state = self.get_state(session_id)
        missing_documents = _missing_required_documents(state)
        if missing_documents:
            updates = {
                "documents_pending": missing_documents,
                "current_phase": "awaiting_docs",
            }
            state = self._update_session_state(session_id, updates)
            return _build_missing_documents_message(state, missing_documents), state

        run_response = self._run_agent(session_id, message)
        response_text = _response_text(run_response)
        return self._finalize_run(session_id, response_text)

    def run_message_with_state(
        self, session_id: str, message: str, state_updates: dict[str, Any] | None = None
    ) -> tuple[str, TurboRefiState]:
        run_response = self._run_agent(session_id, message, state_updates=state_updates)
        response_text = _response_text(run_response)
        preferred_phase = None
        if state_updates and "current_phase" in state_updates:
            preferred_phase = state_updates["current_phase"]
        return self._finalize_run(session_id, response_text, preferred_phase=preferred_phase)
