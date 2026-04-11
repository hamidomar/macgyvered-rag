import json
from pathlib import Path

from turborefi.schemas import BorrowerCase
from turborefi.services.packet_builder import build_deterministic_loan_packet
from turborefi.services.session_state import build_session_state
from turborefi.services.verification_service import VerificationService
from turborefi.testing.fake_retrieval import FakeHierarchyRetrievalService


def load_case(case_name: str) -> BorrowerCase:
    case_path = Path(__file__).resolve().parents[1] / "data" / "mock_cases" / f"{case_name}.json"
    return BorrowerCase.model_validate(json.loads(case_path.read_text(encoding="utf-8")))


def test_verification_service_passes_for_deterministic_packet():
    case = load_case("uc1_sarah_chen")
    session_state = build_session_state(case)
    packet = build_deterministic_loan_packet(session_state, FakeHierarchyRetrievalService()).packet
    session_state.loa_output = packet

    report = VerificationService(FakeHierarchyRetrievalService()).build_report(session_state, packet)

    assert report.verification_status == "PASS"
    assert report.compliance_score is not None
    assert report.compliance_score.total == 100.0
