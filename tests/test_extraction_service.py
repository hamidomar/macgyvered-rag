from pathlib import Path
from types import SimpleNamespace

from turborefi.config import Settings
from turborefi.extraction.service import DocumentExtractionService


class FakeOpenAIClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    @staticmethod
    def create(**_kwargs):
        content = """```json
        {
          "borrower_name": "Taylor Brooks",
          "current_rate_percent": 7.1,
          "loan_balance": 320000,
          "servicer_name": "Test Servicer",
          "loan_number": "LN-123",
          "gse_owner": "fnma",
          "monthly_pi": 2200,
          "monthly_pmi": 0,
          "original_property_value": 450000
        }
        ```"""
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


def build_settings(tmp_path: Path) -> Settings:
    runtime_dir = tmp_path / "runtime"
    sessions_dir = runtime_dir / "sessions"
    traces_dir = runtime_dir / "traces"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    traces_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        mock_cases_dir=tmp_path / "data" / "mock_cases",
        runtime_dir=runtime_dir,
        traces_dir=traces_dir,
        sessions_dir=sessions_dir,
        agno_storage_db=runtime_dir / "agents.db",
        fnma_index_dir=None,
        fhlmc_index_dir=None,
        openai_model_extraction="gpt-4.1-mini",
        openai_model_loa="gpt-4.1-mini",
        openai_model_verifier="gpt-4.1-mini",
        playground_host="0.0.0.0",
        playground_port=7777,
        agno_history_length=5,
    )


def test_extract_bytes_from_image_uses_multimodal_client(tmp_path):
    service = DocumentExtractionService(
        settings=build_settings(tmp_path),
        client=FakeOpenAIClient(),
    )

    document = service.extract_bytes(
        "mortgage_statement",
        b"fake-image-bytes",
        mime_type="image/png",
    )

    assert document.borrower_name == "Taylor Brooks"
    assert document.loan_balance == 320000


def test_infer_supporting_doc_type_from_filename(tmp_path):
    service = DocumentExtractionService(
        settings=build_settings(tmp_path),
        client=FakeOpenAIClient(),
    )

    inferred = service.infer_supporting_doc_type(
        b"unused",
        filename="recent_w2.pdf",
        mime_type="application/pdf",
    )

    assert inferred == "w2"
