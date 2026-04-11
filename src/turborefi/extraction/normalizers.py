from __future__ import annotations

from typing import Any


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        return stripped
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    return value


def normalize_document_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: _normalize_value(value) for key, value in payload.items()}

