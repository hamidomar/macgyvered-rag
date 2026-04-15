from __future__ import annotations

import hashlib
from typing import Any

from turborefi.schemas import SessionState


BLOCKED_LOA_KEYS = {
    "borrower_name",
    "borrowername",
    "name",
    "profession",
    "occupation",
    "job_title",
    "jobtitle",
    "race",
    "ethnicity",
    "sex",
    "gender",
    "age",
    "marital_status",
    "national_origin",
    "language",
    "disability_status",
    "disability",
}


def tokenize_borrower(name: str | None, salt: str) -> str:
    seed = f"{salt}|{name or 'borrower'}"
    return "borrower_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _is_blocked_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return normalized in BLOCKED_LOA_KEYS


def redact_for_loa_prompt(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: redact_for_loa_prompt(value)
            for key, value in payload.items()
            if not _is_blocked_key(str(key))
        }
    if isinstance(payload, list):
        return [redact_for_loa_prompt(value) for value in payload]
    return payload


def assert_no_blocked_loa_fields(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _is_blocked_key(str(key)):
                raise ValueError(f"Blocked LOA field present: {key}")
            assert_no_blocked_loa_fields(value)
    elif isinstance(payload, list):
        for value in payload:
            assert_no_blocked_loa_fields(value)


def build_loa_visible_session(state: SessionState) -> dict[str, Any]:
    payload = {
        "session_id": state.session_id,
        "borrower_id_token": state.borrower_id_token,
        "source_mode": state.source_mode,
        "use_case": state.use_case,
        "income_type": state.income_type,
        "state_machine_state": state.state_machine_state,
        "current_phase": state.current_phase,
        "received_mortgage": (
            state.received_mortgage.model_dump(mode="json")
            if state.received_mortgage is not None
            else None
        ),
        "screening_assumptions": state.screening_assumptions.model_dump(mode="json"),
        "borrower_facts": state.borrower_facts.model_dump(
            mode="json",
            exclude={"factual_uncertainties"},
        ),
        "documents_received": state.received_documents,
        "documents_missing": state.missing_documents,
        "calculated_outputs": state.calculated_outputs,
        "lars_result": state.lars_result.model_dump(mode="json") if state.lars_result else None,
        "handoff_package": state.handoff_package.model_dump(mode="json") if state.handoff_package else None,
        "source_data_warnings": state.source_data_warnings,
    }
    redacted = redact_for_loa_prompt(payload)
    assert_no_blocked_loa_fields(redacted)
    return redacted

