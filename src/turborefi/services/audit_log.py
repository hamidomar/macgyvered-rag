from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def write_trace(traces_dir: Path, session_id: str, trace_name: str, payload: dict[str, Any]) -> Path:
    traces_dir.mkdir(parents=True, exist_ok=True)
    trace_path = traces_dir / f"{session_id}_{trace_name}.json"
    with trace_path.open("w", encoding="utf-8") as handle:
        json.dump(_json_safe(payload), handle, indent=2)
    return trace_path

