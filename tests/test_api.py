from pathlib import Path

from fastapi.testclient import TestClient

from turborefi.api import build_api
from turborefi.config import Settings
from turborefi.extraction.service import UnsupportedDocumentError
from turborefi.schemas import PaystubData, W2Data
from turborefi.services.full_application_resolver import DeterministicFullApplicationResolver
from turborefi.services.gse_analysis import DeterministicGSEAnalyzer
from turborefi.services.session_service import TurboRefiSessionService
from turborefi.services.uc1_uc2_intake_resolver import DeterministicUC1UC2IntakeResolver
from turborefi.testing.fake_retrieval import FakeHierarchyRetrievalService


class FallbackConversationAgent:
    def run(self, *_args, **_kwargs):
        raise RuntimeError("force deterministic fallback")


class FakeExtractionService:
    def extract_upload(self, *, filename, doc_type=None, **_kwargs):
        lowered = (filename or "").lower()
        if doc_type == "paystub" or "paystub" in lowered:
            suffix = "2" if "prior" in lowered or "2" in lowered else "1"
            ytd_gross = 28846.15 if suffix == "2" else 25000
            pay_period_end_date = "2026-04-14" if suffix == "2" else "2026-03-31"
            return (
                "paystub",
                PaystubData(
                    employer_name="Acme Manufacturing",
                    gross_this_period=3846.15,
                    pay_frequency="biweekly",
                    ytd_gross=ytd_gross,
                    pay_period_end_date=pay_period_end_date,
                    base_pay=3846.15,
                ),
            )
        if doc_type == "w2" or "w2" in lowered:
            tax_year = 2023 if "2023" in lowered else 2024
            wages = 96000 if tax_year == 2023 else 98000
            return (
                "w2",
                W2Data(
                    employer_name="Acme Manufacturing",
                    wages_box1=wages,
                    tax_year=tax_year,
                ),
            )
        if "driver" in lowered or doc_type == "identity":
            return ("identity", {"document_present": True, "document_type": "driver_license"})
        if "insurance" in lowered or doc_type == "insurance":
            return ("insurance", {"insurance_annual": 1800})
        if "tax" in lowered or doc_type == "tax_bill":
            return ("tax_bill", {"tax_bill_annual": 5400})
        raise UnsupportedDocumentError("Could not determine the supporting document type.")


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


def build_service(tmp_path: Path) -> TurboRefiSessionService:
    retrieval = FakeHierarchyRetrievalService()
    return TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=retrieval,
        extraction_service=FakeExtractionService(),
        json_first_conversation_agent=FallbackConversationAgent(),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
        full_application_resolver=DeterministicFullApplicationResolver(),
        gse_analyzer=DeterministicGSEAnalyzer(retrieval),
    )


def uc1_payload() -> dict:
    return {
        "core": {
            "rate": 7.5,
            "balance": 290000,
            "monthlyPaymentPI": 2026.08,
            "monthlyPMI": 0,
            "propertyAddress": "1247 Maple Ridge Dr, North Olmsted, OH 44070",
        },
        "propertyLookup": {"estimatedValue": 375000},
    }


def test_api_json_first_flow_with_supporting_uploads(tmp_path):
    client = TestClient(build_api(build_service(tmp_path)))

    create_response = client.post(
        "/session/from-json",
        json={"payload": uc1_payload(), "new_rate": 6.0},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    message_response = client.post(
        f"/session/{session_id}/message",
        json={
            "message": "I think I'm around 740, I've been with my employer for 7 years, and this is my only income.",
        },
    )
    assert message_response.status_code == 200
    assert any(
        entry["tool"] == "resolve_uc1_uc2_intake"
        for entry in message_response.json()["tool_trace"]
    )

    for filename in (
        "02_Paystub_Recent.pdf",
        "03_Paystub_Prior.pdf",
        "04_W2_2024.pdf",
        "05_W2_2023.pdf",
        "06_Tax_Bill.pdf",
        "07_Insurance_Dec.pdf",
        "08_Drivers_License.pdf",
    ):
        upload_response = client.post(
            "/ingest",
            data={"session_id": session_id},
            files={"file": (filename, b"document", "application/pdf")},
        )
        assert upload_response.status_code == 200

    status_response = client.get(f"/session/{session_id}/status")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["current_phase"] == "assessment"
    assert body["documents_pending"] == []
    assert "verification_status" not in body
    assert "received_mortgage" in body
    assert "mortgage_data" not in body

    not_ready_response = client.get(f"/session/{session_id}/result")
    assert not_ready_response.status_code == 400
    assert "after the borrower elects to proceed" in not_ready_response.json()["detail"]

    proceed_response = client.post(
        f"/session/{session_id}/message",
        json={"message": "Yes lets proceed"},
    )
    assert proceed_response.status_code == 200
    assert "Recommendation summary:" in proceed_response.json()["response"]
    assert any(
        entry["tool"] == "build_json_first_recommendation_packet"
        for entry in proceed_response.json()["tool_trace"]
    )

    result_response = client.get(f"/session/{session_id}/result")
    assert result_response.status_code == 200
    result = result_response.json()
    assert result["recommended_gse"] in {"fnma", "fhlmc"}
    assert result["recommended_gse_reason"]

    detail_response = client.get(f"/refi/sessions/{session_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["recommendation_packet"]["recommended_gse_reason"]
    assert "verification_report" not in detail
    assert "mortgage_data" not in detail


def test_api_rejects_supporting_upload_without_session(tmp_path):
    client = TestClient(build_api(build_service(tmp_path)))

    upload_response = client.post(
        "/ingest",
        files={"file": ("02_Paystub_Recent.pdf", b"document", "application/pdf")},
    )

    assert upload_response.status_code == 400
    assert "create a session from received json" in upload_response.json()["detail"].lower()


def test_api_returns_400_for_unsupported_supporting_document(tmp_path):
    client = TestClient(build_api(build_service(tmp_path)))
    create_response = client.post(
        "/session/from-json",
        json={"payload": uc1_payload(), "new_rate": 6.0},
    )
    session_id = create_response.json()["session_id"]

    upload_response = client.post(
        "/ingest",
        data={"session_id": session_id},
        files={"file": ("mystery.pdf", b"document", "application/pdf")},
    )

    assert upload_response.status_code == 400
    assert "could not determine" in upload_response.json()["detail"].lower()
