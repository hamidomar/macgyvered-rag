import json
from pathlib import Path

from turborefi.schemas import BorrowerCase
from turborefi.services.packet_builder import build_deterministic_loan_packet
from turborefi.services.session_state import build_session_state
from turborefi.testing.fake_retrieval import FakeHierarchyRetrievalService


def load_case(case_name: str) -> BorrowerCase:
    case_path = Path(__file__).resolve().parents[1] / "data" / "mock_cases" / f"{case_name}.json"
    return BorrowerCase.model_validate(json.loads(case_path.read_text(encoding="utf-8")))


def test_build_deterministic_packet_for_uc1():
    case = load_case("uc1_sarah_chen")
    session_state = build_session_state(case)

    result = build_deterministic_loan_packet(session_state, FakeHierarchyRetrievalService())

    assert result.packet.borrower_name == "Sarah Chen"
    assert result.packet.use_case == "uc1_rate_term_refi"
    assert result.packet.qualifying_monthly_income == 12500.0
    assert result.packet.ltv_percent == 75.0
    assert result.packet.fnma_eligible is True
    assert result.packet.fhlmc_eligible is True
    assert result.packet.recommended_gse == "fnma"
    assert len(result.packet.guideline_citations) >= 3
    assert any(citation.section == "B2-1.3-02" for citation in result.packet.guideline_citations)
    assert any(citation.section == "4301.4" for citation in result.packet.guideline_citations)
    assert any(event.tool == "list_guide_contents" for event in result.retrieval_events)
    assert any(event.tool == "get_guideline_section" for event in result.retrieval_events)
    assert any(event.gse == "fhlmc" for event in result.retrieval_events)
