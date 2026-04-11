from pathlib import Path
from types import SimpleNamespace

from turborefi.config import Settings
from turborefi.schemas import MortgageStatementData, PaystubData, ScheduleCData, W2Data
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


def test_session_service_builds_packet_when_docs_complete(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )

    mortgage_statement = MortgageStatementData(
        borrower_name="Taylor Brooks",
        current_rate_percent=7.1,
        loan_balance=320000,
        servicer_name="Test Servicer",
        loan_number="LN-123",
        gse_owner="fnma",
        monthly_pi=2200,
        monthly_pmi=185,
        original_property_value=450000,
    )
    paystub_1 = PaystubData(
        employer_name="Acme Corp",
        gross_this_period=8000,
        pay_frequency="monthly",
        ytd_gross=8000,
        pay_period_end_date="2026-01-31",
    )
    paystub_2 = PaystubData(
        employer_name="Acme Corp",
        gross_this_period=8000,
        pay_frequency="monthly",
        ytd_gross=16000,
        pay_period_end_date="2026-02-28",
    )
    w2 = W2Data(
        employer_name="Acme Corp",
        wages_box1=96000,
        tax_year=2025,
    )

    session_id, response_text, state, trace = service.create_session_from_mortgage_data(mortgage_statement)
    assert state.current_phase == "awaiting_intake"
    assert state.intake_pending == ["income_type", "current_property_value"]
    assert "property value" in response_text.lower()
    assert trace == []
    assert len(state.conversation) == 2
    assert state.conversation[0].content.startswith("Uploaded mortgage statement")

    response_text, state, tool_trace = service.send_message(
        session_id,
        "I'm a W-2 employee at Acme Corp making $96K/year. My home is worth about $500K now.",
    )
    assert state.current_phase == "awaiting_docs"
    assert state.intake_pending == []
    assert state.missing_documents == ["paystubs", "w2s"]
    assert "w-2 refinance path" in response_text.lower()
    assert any(entry["tool"] == "update_borrower_fact" for entry in tool_trace)

    response_text, state, trace = service.upload_secondary_document(session_id, "paystub", paystub_1)
    assert state.current_phase == "awaiting_docs"
    assert state.loa_output is None
    assert trace == []

    response_text, state, trace = service.upload_secondary_document(session_id, "paystub", paystub_2)
    assert state.current_phase == "awaiting_docs"
    assert state.loa_output is None
    assert trace == []

    response_text, state, trace = service.upload_secondary_document(session_id, "w2", w2)
    assert state.current_phase == "verified"
    assert state.loa_output is not None
    assert state.verifier_output is not None
    assert any(entry["tool"] == "list_guide_contents" for entry in trace)
    assert any(entry["tool"] == "get_guideline_section" for entry in trace)
    assert any(entry["arguments"].get("gse") == "fnma" for entry in trace if entry["tool"] == "get_guideline_section")
    assert any(entry["arguments"].get("gse") == "fhlmc" for entry in trace if entry["tool"] == "get_guideline_section")
    assert any(entry["tool"] == "verify_recommendation_packet" for entry in trace)
    assert len(state.conversation) == 10
    assert service.get_result(session_id).recommended_gse == "fnma"
    persisted = service.get_state(session_id)
    assert len(persisted.conversation) == 10


def test_session_service_self_employed_intake_path(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )

    mortgage_statement = MortgageStatementData(
        borrower_name="Maria Garcia",
        current_rate_percent=6.75,
        loan_balance=380000,
        servicer_name="Test Servicer",
        loan_number="LN-456",
        gse_owner="fnma",
        monthly_pi=2464,
        monthly_pmi=0,
        original_property_value=520000,
    )
    schedule_c_2023 = ScheduleCData(
        tax_year=2023,
        net_profit_loss=95000,
        depreciation=4000,
        business_name="Garcia Design LLC",
    )
    schedule_c_2024 = ScheduleCData(
        tax_year=2024,
        net_profit_loss=110000,
        depreciation=4000,
        business_name="Garcia Design LLC",
    )

    session_id, response_text, state, trace = service.create_session_from_mortgage_data(mortgage_statement)
    assert state.current_phase == "awaiting_intake"
    assert state.intake_pending == ["income_type"]
    assert "w-2 or self-employed" in response_text.lower()
    assert trace == []

    response_text, state, tool_trace = service.send_message(
        session_id,
        "I'm self-employed. Business is Garcia Design LLC and I've been freelancing for 4 years.",
    )
    assert state.current_phase == "awaiting_docs"
    assert state.income_type == "self_employed"
    assert state.borrower_facts.years_in_business == 4
    assert state.missing_documents == ["schedule_c"]
    assert "self-employed refinance path" in response_text.lower()
    assert any(entry["tool"] == "update_borrower_fact" for entry in tool_trace)

    service.upload_secondary_document(session_id, "schedule_c", schedule_c_2023)
    response_text, state, trace = service.upload_secondary_document(session_id, "schedule_c", schedule_c_2024)
    assert state.current_phase == "verified"
    assert state.loa_output is not None
    assert state.verifier_output is not None
    assert any(entry["tool"] == "list_guide_contents" for entry in trace)
    assert any(entry["tool"] == "get_guideline_section" for entry in trace)
    assert any(entry["tool"] == "verify_recommendation_packet" for entry in trace)


def test_session_service_prompts_for_property_value_when_statement_has_none(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )

    mortgage_statement = MortgageStatementData(
        borrower_name="Adam and Mary Jones",
        current_rate_percent=4.75,
        loan_balance=264776.43,
        servicer_name="Springside Mortgage",
        loan_number="LN-789",
        gse_owner="unknown",
        monthly_pi=1434.53,
        monthly_pmi=0,
        original_property_value=None,
    )

    _session_id, response_text, state, trace = service.create_session_from_mortgage_data(mortgage_statement)
    assert state.current_phase == "awaiting_intake"
    assert state.intake_pending == ["income_type", "current_property_value"]
    assert "current property value" in response_text.lower()
    assert trace == []


def test_session_service_accepts_standalone_property_value_reply(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )

    mortgage_statement = MortgageStatementData(
        borrower_name="Adam and Mary Jones",
        current_rate_percent=4.75,
        loan_balance=264776.43,
        servicer_name="Springside Mortgage",
        loan_number="LN-790",
        gse_owner="unknown",
        monthly_pi=1434.53,
        monthly_pmi=0,
        original_property_value=None,
    )

    session_id, _response_text, state, _trace = service.create_session_from_mortgage_data(mortgage_statement)
    assert state.intake_pending == ["income_type", "current_property_value"]

    response_text, state, tool_trace = service.send_message(
        session_id,
        "Yes salaried w2 income. Employer microsoft and salary 150000",
    )
    assert state.current_phase == "awaiting_intake"
    assert state.borrower_facts.annual_income == 150000
    assert state.borrower_facts.current_property_value is None
    assert "property's current value" in response_text.lower()
    assert any(entry["tool"] == "update_borrower_fact" for entry in tool_trace)

    response_text, state, tool_trace = service.send_message(session_id, "600000")
    assert state.current_phase == "awaiting_docs"
    assert state.borrower_facts.current_property_value == 600000
    assert "w-2 refinance path" in response_text.lower()
    assert any(entry["tool"] == "update_borrower_fact" for entry in tool_trace)


def test_session_service_flags_implausible_property_value(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        intake_resolver=DeterministicIntakeResolver(),
    )

    mortgage_statement = MortgageStatementData(
        borrower_name="Adam and Mary Jones",
        current_rate_percent=4.75,
        loan_balance=264776.43,
        servicer_name="Springside Mortgage",
        loan_number="LN-791",
        gse_owner="unknown",
        monthly_pi=1434.53,
        monthly_pmi=0,
        original_property_value=None,
    )

    session_id, _response_text, _state, _trace = service.create_session_from_mortgage_data(mortgage_statement)
    service.send_message(
        session_id,
        "Yes salaried w2 income. Employer microsoft and salary 150000",
    )

    response_text, state, tool_trace = service.send_message(session_id, "40000")
    assert state.current_phase == "awaiting_intake"
    assert state.borrower_facts.current_property_value is None
    assert "much lower than the current loan balance" in response_text.lower()
    assert any(
        entry["tool"] == "update_borrower_fact"
        and entry["result"]["status"] == "needs_confirmation"
        for entry in tool_trace
    )
