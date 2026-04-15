from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    data_dir: Path
    mock_cases_dir: Path
    runtime_dir: Path
    traces_dir: Path
    sessions_dir: Path
    agno_storage_db: Path
    fnma_index_dir: Path | None
    fhlmc_index_dir: Path | None
    openai_model_extraction: str
    openai_model_loa: str
    openai_model_verifier: str
    playground_host: str
    playground_port: int
    agno_history_length: int
    screening_new_rate: float | None


def _optional_path(value: str | None, base_dir: Path) -> Path | None:
    if value is None or value == "":
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _index_path(value: str | None, base_dir: Path, default_relative: str) -> Path | None:
    configured = _optional_path(value, base_dir)
    if configured is not None and configured.exists():
        return configured

    default_path = (base_dir / default_relative).resolve()
    if default_path.exists():
        return default_path

    return configured


def _optional_float(value: str | None, default: float | None = None) -> float | None:
    if value is None or value.strip() == "":
        return default
    return float(value)


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    data_dir = repo_root / "data"
    mock_cases_dir = data_dir / "mock_cases"
    runtime_dir = repo_root / "runtime"
    traces_dir = runtime_dir / "traces"
    sessions_dir = runtime_dir / "sessions"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    traces_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    agno_storage_value = os.getenv("AGNO_STORAGE_DB", "runtime/agents.db")
    agno_storage_db = _optional_path(agno_storage_value, repo_root)
    assert agno_storage_db is not None
    agno_storage_db.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        repo_root=repo_root,
        data_dir=data_dir,
        mock_cases_dir=mock_cases_dir,
        runtime_dir=runtime_dir,
        traces_dir=traces_dir,
        sessions_dir=sessions_dir,
        agno_storage_db=agno_storage_db,
        fnma_index_dir=_index_path(
            os.getenv("FNMA_INDEX_DIR"),
            repo_root,
            "retrival/output/selling_guide_preprocessed",
        ),
        fhlmc_index_dir=_index_path(
            os.getenv("FHLMC_INDEX_DIR"),
            repo_root,
            "retrival/output/sf_guide_index",
        ),
        openai_model_extraction=os.getenv("OPENAI_MODEL_EXTRACTION", "gpt-4.1"),
        openai_model_loa=os.getenv("OPENAI_MODEL_LOA", "gpt-4.1"),
        openai_model_verifier=os.getenv("OPENAI_MODEL_VERIFIER", "gpt-4.1"),
        playground_host=os.getenv("PLAYGROUND_HOST", "0.0.0.0"),
        playground_port=int(os.getenv("PLAYGROUND_PORT", "7777")),
        agno_history_length=int(os.getenv("AGNO_HISTORY_LENGTH", "12")),
        screening_new_rate=_optional_float(os.getenv("SCREENING_NEW_RATE"), 6.0),
    )
