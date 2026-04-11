from __future__ import annotations

import json
from pathlib import Path

from turborefi.schemas import BorrowerCase


class CaseRepository:
    def __init__(self, cases_dir: Path):
        self.cases_dir = cases_dir

    def list_cases(self) -> list[str]:
        return sorted(path.stem for path in self.cases_dir.glob("*.json"))

    def load_case(self, case_id: str) -> BorrowerCase:
        case_path = self.cases_dir / f"{case_id}.json"
        if not case_path.exists():
            raise FileNotFoundError(f"Unknown mock case: {case_id}")
        with case_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return BorrowerCase.model_validate(payload)

