from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from turborefi.api import build_api
from turborefi.config import Settings
from turborefi.extraction.service import UnsupportedDocumentError
from turborefi.schemas import MortgageStatementData, PaystubData, W2Data
from turborefi.services.intake_resolver import DeterministicIntakeResolver
from turborefi.services.session_service import TurboRefiSessionService
from turborefi.testing.fake_retrieval import FakeHierarchyRetrievalService


class FakeAgent:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.session_states = {}

    def update_session_state(self, session_id=None, session_state_updates=None):
        self.session_states[session_id] = session_state_updates or {}

    def run(self, message, session_id=None, session_state=None):
        self.session_states[session_id] = session_state or {}
        return SimpleNamespace(content=f"{self.prefix}:{message}")


class FakeExtractionService:
    def extract_upload(self, *, filename, doc_type=None, is_new_session=False, **_kwargs):
        if is_new_session or doc_type == "mortgage_statement":
            return (
                "mortgage_statement",
                MortgageStatementData(
                borrower_name="Taylor Brooks",
                current_rate_percent=7.1,
                loan_balance=320000,
                servicer_name="Test Servicer",
                loan_number="LN-123",
                gse_owner="fnma",
                monthly_pi=2200,
                monthly_pmi=185,
                original_property_value=350000,
            ),
        )
        if doc_type == "paystub" or (filename and "paystub" in filename.lower()):
            suffix = "2" if filename and "2" in filename else "1"
            ytd_gross = 16000 if suffix == "2" else 8000
            pay_period_end_date = "2026-02-28" if suffix == "2" else "2026-01-31"
            return (
                "paystub",
                PaystubData(
                    employer_name="Acme Corp",
                    gross_this_period=8000,
                    pay_frequency="monthly",
                    ytd_gross=ytd_gross,
                    pay_period_end_date=pay_period_end_date,
                ),
            )
        if filename and "driver" in filename.lower():
            return (
                "identity",
                {"document_present": True, "document_type": "driver_license"},
            )
        return (
            "w2",
            W2Data(
                employer_name="Acme Corp",
                wages_box1=96000,
                tax_year=2025,
            ),
        )


class UnsupportedExtractionService(FakeExtractionService):
    def extract_upload(self, *, filename, doc_type=None, is_new_session=False, **kwargs):
        if filename and "mystery" in filename.lower() and not is_new_session:
            raise UnsupportedDocumentError("Could not determine the supporting document type.")
        return super().extract_upload(
            filename=filename,
            doc_type=doc_type,
            is_new_session=is_new_session,
            **kwargs,
        )


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
        screening_new_rate=6.0,
    )


def test_api_ingest_status_result_and_verify(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        extraction_service=FakeExtractionService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )
    client = TestClient(build_api(service))

    create_response = client.post(
        "/ingest",
        files={"file": ("statement.pdf", b"statement", "application/pdf")},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    list_response = client.get("/refi/sessions")
    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["session_id"] == session_id

    status_response = client.get(f"/session/{session_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["current_phase"] == "awaiting_intake"
    assert status_response.json()["intake_pending"] == ["income_type", "current_property_value"]

    message_response = client.post(
        f"/session/{session_id}/message",
        json={
            "message": "I'm a W-2 teacher making $75K/year. My home is worth about $400K now."
        },
    )
    assert message_response.status_code == 200
    assert "w-2 refinance path" in message_response.json()["response"].lower()
    assert any(
        entry["tool"] == "update_borrower_fact"
        for entry in message_response.json()["tool_trace"]
    )

    status_response = client.get(f"/session/{session_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["current_phase"] == "awaiting_docs"
    assert status_response.json()["intake_pending"] == []

    for filename in ("paystub1.pdf", "paystub2.pdf", "w2.pdf"):
        upload_response = client.post(
            "/ingest",
            data={"session_id": session_id},
            files={"file": (filename, b"document", "application/pdf")},
        )
        assert upload_response.status_code == 200

    status_response = client.get(f"/session/{session_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["current_phase"] == "verified"
    assert status_response.json()["verification_status"] == "PASS"

    result_response = client.get(f"/session/{session_id}/result")
    assert result_response.status_code == 200
    assert result_response.json()["recommended_gse"] == "fnma"

    detail_response = client.get(f"/refi/sessions/{session_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["session_id"] == session_id
    assert len(detail_response.json()["messages"]) == 10
    assert detail_response.json()["recommendation_packet"]["recommended_gse"] == "fnma"
    assert detail_response.json()["verification_report"]["verification_status"] == "PASS"
    final_tool_names = [tool["tool_name"] for tool in detail_response.json()["messages"][-1]["tool_calls"]]
    assert "list_guide_contents" in final_tool_names
    assert "get_guideline_section" in final_tool_names
    assert "verify_recommendation_packet" in final_tool_names

    verify_response = client.post(f"/session/{session_id}/verify")
    assert verify_response.status_code == 200
    assert verify_response.json()["verification_status"] == "PASS"


def test_api_allows_identity_uploads_in_existing_session(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        extraction_service=FakeExtractionService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )
    client = TestClient(build_api(service))

    create_response = client.post(
        "/ingest",
        files={"file": ("statement.pdf", b"statement", "application/pdf")},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    upload_response = client.post(
        "/ingest",
        data={"session_id": session_id},
        files={"file": ("08_Drivers_License.pdf", b"document", "application/pdf")},
    )

    assert upload_response.status_code == 200
    assert upload_response.json()["document_type"] == "identity"


def test_api_returns_400_for_unsupported_supporting_document(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        extraction_service=UnsupportedExtractionService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )
    client = TestClient(build_api(service))

    create_response = client.post(
        "/ingest",
        files={"file": ("statement.pdf", b"statement", "application/pdf")},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    upload_response = client.post(
        "/ingest",
        data={"session_id": session_id},
        files={"file": ("mystery.pdf", b"document", "application/pdf")},
    )

    assert upload_response.status_code == 400
    assert "could not determine" in upload_response.json()["detail"].lower()
