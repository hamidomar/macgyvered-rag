import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from turborefi.api import build_api
from turborefi.config import Settings
from turborefi.schemas import PaystubData, ReceivedMortgageData, SessionState, W2Data
from turborefi.services.calculations import income, ltv, mortgage, savings
from turborefi.services.conversation_flows import apply_uc1_uc2_message, next_question
from turborefi.services.full_application_resolver import (
    DeterministicFullApplicationResolver,
    is_full_application_decision_pending,
)
from turborefi.services.information_firewall import build_loa_visible_session
from turborefi.services.lars_engine import evaluate_lars
from turborefi.services.received_input import parse_received_json
from turborefi.services.session_service import TurboRefiSessionService
from turborefi.services.uc1_uc2_intake_resolver import (
    DeterministicUC1UC2IntakeResolver,
    validate_and_apply_uc1_uc2_fact,
)
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
        screening_new_rate=6.0,
    )


def uc1_clean_payload():
    return {
        "core": {
            "balance": 290000,
            "rate": 7.5,
            "monthlyPayment": 2027.64,
            "paymentBreakdown": {"principal": 2027.64, "interest": 0, "escrow": None, "pmi": None},
            "loanNumber": "LN-UC1",
            "propertyAddress": "1247 Maple Ridge Dr, North Olmsted OH",
            "servicer": "Test Servicer",
            "loanType": "conventional",
            "rateType": "fixed",
            "originalLoanAmount": 300000,
            "propertyValue": 435000,
            "propertyData": {"estimatedValue": 435000, "propertyType": "Single Family"},
        },
        "propertyLookup": {
            "estimatedValue": 435000,
            "propertyType": "Single Family",
            "source": "fixture",
        },
        "statement": {"statementDateRaw": "2026-03-15", "borrowerName": "Sarah Chen"},
    }


def referred_uc1_payload():
    return {
        "core": {
            "balance": 185000,
            "rate": 7.25,
            "monthlyPayment": 1262.47,
            "paymentBreakdown": {"principal": 1262.47, "interest": 0, "escrow": None, "pmi": None},
            "loanNumber": "LN-REF",
            "propertyAddress": "892 Brookpark Rd, Apt 4B, Parma, OH 44134",
            "servicer": "Test Servicer",
            "loanType": "conventional",
            "rateType": "fixed",
            "originalLoanAmount": 190000,
            "propertyValue": 225000,
            "propertyData": {"estimatedValue": 225000, "propertyType": "Condo"},
        },
        "propertyLookup": {
            "estimatedValue": 225000,
            "propertyType": "Condo",
            "source": "fixture",
        },
        "statement": {"statementDateRaw": "2026-03-15", "borrowerName": "Jamie Smith"},
    }


def complete_json_first_uc1_case(service: TurboRefiSessionService) -> str:
    session_id, _response, _state, _trace = service.create_session_from_received_json(
        uc1_clean_payload(),
        new_rate=6.0,
    )
    service.send_message(
        session_id,
        "I am around 740, I have been with my employer for 7 years, it is my only income, single-family home.",
    )
    service.upload_document_json(
        session_id,
        "paystub",
        {
            "employer_name": "Acme Manufacturing",
            "gross_this_period": 3846.15,
            "pay_frequency": "biweekly",
            "ytd_gross": 25000,
            "pay_period_end_date": "2026-03-31",
            "base_pay": 3846.15,
        },
    )
    service.upload_document_json(
        session_id,
        "paystub",
        {
            "employer_name": "Acme Manufacturing",
            "gross_this_period": 3846.15,
            "pay_frequency": "biweekly",
            "ytd_gross": 21153.85,
            "pay_period_end_date": "2026-03-15",
            "base_pay": 3846.15,
        },
    )
    service.upload_document_json(
        session_id,
        "w2",
        {
            "tax_year": 2024,
            "wages_box1": 98000,
            "employer_name": "Acme Manufacturing",
        },
    )
    service.upload_document_json(
        session_id,
        "w2",
        {
            "tax_year": 2023,
            "wages_box1": 95000,
            "employer_name": "Acme Manufacturing",
        },
    )
    service.upload_document_json(
        session_id,
        "tax_bill",
        {
            "tax_bill_annual": 5400,
            "tax_year": 2025,
            "property_address": "1247 Maple Ridge Dr, North Olmsted OH",
        },
    )
    service.upload_document_json(
        session_id,
        "insurance",
        {
            "insurance_annual": 1800,
            "carrier_name": "Test Insurance",
        },
    )
    service.upload_document_json(
        session_id,
        "identity",
        {
            "document_present": True,
            "document_type": "drivers_license",
            "issuing_state": "OH",
            "id_last4": "1234",
        },
    )
    return session_id


def test_uc1_spec_clean_calculators():
    gmi = income.gross_monthly_income(3846.15, "biweekly")
    annualized = income.paystub_annualized(3846.15, "biweekly")
    diff = income.w2_paystub_diff_pct(annualized, 98000)
    old_pi = savings.old_pi(290000, 7.5)
    new_pi = savings.new_pi(290000, 6.0)
    tax = mortgage.tax_monthly(5400)
    insurance = mortgage.insurance_monthly(1800)
    pitia = mortgage.pitia_total(new_pi, tax, insurance)

    assert gmi == 8333.33
    assert annualized == 99999.9
    assert round(diff * 100, 2) == 2.04
    assert ltv.ltv_percent(290000, 435000) == 66.7
    assert old_pi == 2027.72
    assert new_pi == 1738.7
    assert pitia == 2338.7
    assert savings.rate_savings(old_pi, new_pi) == 289.02


def test_uc2_lars_precedence_straddle_not_b10():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        use_case="uc2_pmi_removal",
        income_type="w2",
        received_mortgage=ReceivedMortgageData(
            current_balance=312000,
            api_value=415000,
            estimated_property_value=415000,
            ltv=0.7518,
        ),
        calculated_outputs={"ltv": 0.7518},
    )
    state.borrower_facts.pmi_type = "unknown"
    state.borrower_facts.has_second_lien = True
    state.borrower_facts.second_lien_balance = 25000
    state.borrower_facts.factual_uncertainties.append("purchase_price")

    result = evaluate_lars(state)
    codes = [event.factor_code for event in result.events]

    assert result.final_score == 55
    assert result.decision == "REFERRED"
    assert codes == ["U2.1", "U2.2", "U2.3", "U2.4"]
    assert "B10" not in codes
    assert "B4" not in codes


def test_fico_uncertainty_reply_triggers_b4():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        use_case="uc1_rate_term_refi",
        income_type="w2",
    )

    update = DeterministicUC1UC2IntakeResolver().resolve(
        state,
        "I'm not totally sure. Maybe around 700? I haven't checked in a while.",
    )
    result = evaluate_lars(state)

    assert state.borrower_facts.fico_range == "680_719"
    assert state.borrower_facts.fico_uncertain is True
    assert "fico_uncertain" in update.changed_fields
    assert result.final_score == 85
    assert [event.factor_code for event in result.events] == ["B4"]


def test_factual_uncertainty_for_fico_also_sets_fico_uncertain():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        use_case="uc1_rate_term_refi",
        income_type="w2",
    )
    state.borrower_facts.fico_range = "680_719"

    result, changed_field = validate_and_apply_uc1_uc2_fact(
        state,
        field_name="factual_uncertainty",
        value="fico_range",
    )

    assert result["status"] == "accepted"
    assert changed_field == "fico_uncertain"
    assert state.borrower_facts.fico_uncertain is True
    assert evaluate_lars(state).final_score == 85


def test_received_json_redacts_borrower_name_from_loa_context():
    parsed = parse_received_json(uc1_clean_payload(), new_rate=6.0)
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        borrower_name="Borrower",
        borrower_id_token=parsed.borrower_id_token,
        received_mortgage=parsed.received_mortgage,
        screening_assumptions=parsed.screening_assumptions,
    )

    visible = build_loa_visible_session(state)
    visible_text = str(visible)

    assert parsed.borrower_id_token.startswith("borrower_")
    assert "Sarah Chen" not in visible_text
    assert "borrower_name" not in visible_text


def test_json_first_uc1_clean_service_flow(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
    )

    session_id, response, state, _trace = service.create_session_from_received_json(
        uc1_clean_payload(),
        new_rate=6.0,
    )
    assert state.source_mode == "received_json_uc1_uc2"
    assert state.use_case == "uc1_rate_term_refi"
    assert state.borrower_name == "Borrower"
    assert "Sarah Chen" not in response

    response, state, _trace = service.send_message(
        session_id,
        "I am around 740, I have been with my employer for 7 years, it is my only income, single-family home.",
    )
    assert state.borrower_facts.fico_range == "720_759"
    assert state.borrower_facts.tenure_months == 84
    assert "720 to 759" in response
    assert "7 years" in response
    assert "only income source" in response

    paystub_1 = PaystubData(
        employer_name="Acme Manufacturing",
        gross_this_period=3846.15,
        pay_frequency="biweekly",
        ytd_gross=25000,
        pay_period_end_date="2026-03-31",
        base_pay=3846.15,
    )
    paystub_2 = PaystubData(
        employer_name="Acme Manufacturing",
        gross_this_period=3846.15,
        pay_frequency="biweekly",
        ytd_gross=28846.15,
        pay_period_end_date="2026-04-14",
        base_pay=3846.15,
    )
    w2_2024 = W2Data(employer_name="Acme Manufacturing", wages_box1=98000, tax_year=2024)
    w2_2023 = W2Data(employer_name="Acme Manufacturing", wages_box1=96000, tax_year=2023)

    service.upload_document_json(session_id, "paystub", paystub_1.model_dump(mode="json"))
    service.upload_document_json(session_id, "paystub", paystub_2.model_dump(mode="json"))
    service.upload_document_json(session_id, "w2", w2_2024.model_dump(mode="json"))
    service.upload_document_json(session_id, "w2", w2_2023.model_dump(mode="json"))
    service.upload_document_json(session_id, "tax_bill", {"tax_bill_annual": 5400})
    service.upload_document_json(session_id, "insurance", {"insurance_annual": 1800})
    response, state, trace = service.upload_document_json(session_id, "identity", {"document_present": True})

    assert "Would you like to proceed to the full application?" in response
    assert state.loa_output is None
    assert not any(entry["tool"] == "list_guide_contents" for entry in trace)
    with pytest.raises(ValueError, match="available after the borrower elects to proceed"):
        service.get_result(session_id)

    proceed_response, state, proceed_trace = service.send_message(session_id, "Yes, let's proceed.")
    packet = service.get_result(session_id)
    state = service.get_state(session_id)

    assert state.full_application_intent == "proceed"
    assert "Recommendation summary:" in proceed_response
    assert packet.borrower_name == "Borrower"
    assert state.lars_result.final_score == 100
    assert state.lars_result.decision == "AUTOMATED"
    assert packet.recommended_gse == "fnma"
    assert packet.recommended_gse_reason
    assert "supportable" in packet.recommended_gse_reason.lower() or "selected because" in packet.recommended_gse_reason.lower()
    assert len(packet.guideline_citations) >= 3
    assert any(citation.section == "B2-1.3-02" for citation in packet.guideline_citations)
    assert any(citation.section == "4301.4" for citation in packet.guideline_citations)
    assert any(event.tool == "list_guide_contents" for event in state.retrieval_events)
    assert any(event.tool == "get_guideline_section" for event in state.retrieval_events)
    assert any(event.gse == "fhlmc" for event in state.retrieval_events)
    assert any(entry["tool"] == "list_guide_contents" for entry in proceed_trace)
    assert state.calculated_outputs["gmi"] == 8333.33
    assert state.calculated_outputs["ltv_percent"] == 66.7
    assert state.calculated_outputs["pitia_total"] == 2338.7
    assert state.calculated_outputs["total_monthly_savings"] == 289.02


def test_full_application_resolver_returns_unclear_for_follow_up_question():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        full_application_intent=None,
    )
    state.lars_result = evaluate_lars(state)
    state.lars_result.decision = "AUTOMATED"
    state.missing_documents = []

    assert is_full_application_decision_pending(state) is True

    resolution = DeterministicFullApplicationResolver().resolve(
        state,
        "What happens next if I do that?",
    )

    assert resolution.intent == "unclear"
    assert resolution.tool_trace[0]["tool"] == "resolve_full_application_intent"


def test_automated_ready_yes_response_does_not_repeat_same_question(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
    )

    session_id, _response, _state, _trace = service.create_session_from_received_json(
        uc1_clean_payload(),
        new_rate=6.0,
    )
    service.send_message(
        session_id,
        "I am around 740, I have been with my employer for 7 years, it is my only income, single-family home.",
    )

    paystub_1 = PaystubData(
        employer_name="Acme Manufacturing",
        gross_this_period=3846.15,
        pay_frequency="biweekly",
        ytd_gross=25000,
        pay_period_end_date="2026-03-31",
        base_pay=3846.15,
    )
    paystub_2 = PaystubData(
        employer_name="Acme Manufacturing",
        gross_this_period=3846.15,
        pay_frequency="biweekly",
        ytd_gross=28846.15,
        pay_period_end_date="2026-04-14",
        base_pay=3846.15,
    )
    w2_2024 = W2Data(employer_name="Acme Manufacturing", wages_box1=98000, tax_year=2024)
    w2_2023 = W2Data(employer_name="Acme Manufacturing", wages_box1=96000, tax_year=2023)

    service.upload_document_json(session_id, "paystub", paystub_1.model_dump(mode="json"))
    service.upload_document_json(session_id, "paystub", paystub_2.model_dump(mode="json"))
    service.upload_document_json(session_id, "w2", w2_2024.model_dump(mode="json"))
    service.upload_document_json(session_id, "w2", w2_2023.model_dump(mode="json"))
    service.upload_document_json(session_id, "tax_bill", {"tax_bill_annual": 5400})
    service.upload_document_json(session_id, "insurance", {"insurance_annual": 1800})
    response, state, trace = service.upload_document_json(session_id, "identity", {"document_present": True})

    assert "Would you like to proceed to the full application?" in response
    assert "monthly savings" in response
    assert not any(entry["tool"] == "list_guide_contents" for entry in trace)

    response, state, proceed_trace = service.send_message(session_id, "Yes, let's do it.")

    assert state.full_application_intent == "proceed"
    assert response.startswith("Understood. I marked this case as ready to proceed")
    assert "Recommendation summary:" in response
    assert "FNMA support covers" in response
    assert "FHLMC support covers" in response
    assert "### Packet Overview" in response
    assert "| Field | Value |" in response
    assert "### FNMA Guideline Basis" in response
    assert "### FHLMC Guideline Basis" in response
    assert any(entry["tool"] == "list_guide_contents" for entry in proceed_trace)

    follow_up_response, _state, trace = service.send_message(session_id, "Yes")
    assert trace == []
    assert "We are already in the full-application-ready state" in follow_up_response
    assert "### Packet Overview" in follow_up_response


def test_uc2_bare_no_answers_second_lien_question():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        use_case="uc2_pmi_removal",
        income_type="w2",
        received_mortgage=ReceivedMortgageData(pmi_monthly=175),
    )
    state.borrower_facts.fico_range = "720_759"
    state.borrower_facts.tenure_months = 84
    state.borrower_facts.single_income_source = True
    state.borrower_facts.property_type = "sfr"
    state.borrower_facts.pmi_type = "borrower_paid"
    state.borrower_facts.purchase_price = 350000
    state.borrower_facts.down_payment_amount = 35000

    assert next_question(state) == "Do you have a second mortgage or HELOC on the property?"

    update = apply_uc1_uc2_message(state, "no")

    assert state.borrower_facts.has_second_lien is False
    assert "has_second_lien" in update.changed_fields
    assert next_question(state) != "Do you have a second mortgage or HELOC on the property?"


def test_uc1_uc2_resolver_handles_natural_income_and_property_phrasing():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        use_case="uc1_rate_term_refi",
        income_type="w2",
    )
    resolver = DeterministicUC1UC2IntakeResolver()

    update = resolver.resolve(
        state,
        "Credit is probably around 740. I started with my employer 7 years ago. "
        "My W-2 job is all I have, no other earnings. It is a detached house.",
    )

    assert state.borrower_facts.fico_range == "720_759"
    assert state.borrower_facts.fico_uncertain is True
    assert state.borrower_facts.tenure_months == 84
    assert state.borrower_facts.single_income_source is True
    assert state.borrower_facts.property_type == "sfr"
    assert {"fico_range", "fico_uncertain", "tenure_months", "single_income_source", "property_type"}.issubset(
        update.changed_fields
    )


def test_uc1_uc2_resolver_handles_side_income_without_only_keyword():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        use_case="uc1_rate_term_refi",
        income_type="w2",
    )

    update = DeterministicUC1UC2IntakeResolver().resolve(
        state,
        "I do some DoorDash occasionally in addition to my payroll job.",
    )

    assert state.borrower_facts.single_income_source is False
    assert "single_income_source" in update.changed_fields


def test_uc2_resolver_handles_natural_second_lien_and_purchase_phrasing():
    state = SessionState(
        source_mode="received_json_uc1_uc2",
        use_case="uc2_pmi_removal",
        income_type="w2",
        received_mortgage=ReceivedMortgageData(pmi_monthly=175),
    )
    resolver = DeterministicUC1UC2IntakeResolver()

    purchase_update = resolver.resolve(state, "We put ten percent down on a 350k purchase.")
    lien_update = resolver.resolve(state, "No line of credit, just the first mortgage.")

    assert state.borrower_facts.purchase_price == 350000
    assert state.borrower_facts.down_payment_amount == 35000
    assert state.borrower_facts.has_second_lien is False
    assert {"purchase_price", "down_payment_amount"}.issubset(purchase_update.changed_fields)
    assert "has_second_lien" in lien_update.changed_fields


def test_json_first_message_stream_emits_tool_and_content_events(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
    )
    client = TestClient(build_api(service))
    create_response = client.post(
        "/session/from-json",
        json={"payload": uc1_clean_payload(), "new_rate": 6.0},
    )
    session_id = create_response.json()["session_id"]

    with client.stream(
        "POST",
        f"/session/{session_id}/message/stream",
        json={"message": "My credit is 740 and this is my only income."},
    ) as response:
        body = "".join(response.iter_text())

    events = [json.loads(line) for line in body.splitlines() if line.strip()]
    event_names = [event["event"] for event in events]

    assert response.status_code == 200
    assert "RunStarted" in event_names
    assert "ToolCallCompleted" in event_names
    assert "RunContent" in event_names
    assert event_names[-1] == "RunCompleted"
    assert any(
        event.get("tool", {}).get("tool_name") == "resolve_uc1_uc2_intake"
        for event in events
    )


def test_json_first_proceed_stream_emits_stage_messages(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
        full_application_resolver=DeterministicFullApplicationResolver(),
    )
    session_id = complete_json_first_uc1_case(service)
    client = TestClient(build_api(service))

    with client.stream(
        "POST",
        f"/session/{session_id}/message/stream",
        json={"message": "Yes lets proceed."},
    ) as response:
        body = "".join(response.iter_text())

    events = [json.loads(line) for line in body.splitlines() if line.strip()]
    run_content = [event["content"] for event in events if event["event"] == "RunContent"]

    assert response.status_code == 200
    assert any("Reviewing FNMA guidance..." in content for content in run_content)
    assert any("Reviewing FHLMC guidance..." in content for content in run_content)
    assert any("Building recommendation packet..." in content for content in run_content)
    assert events[-1]["event"] == "RunCompleted"


def test_json_first_uses_configured_screening_rate_when_request_omits_rate(tmp_path):
    settings = build_settings(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "screening_new_rate": 5.875,
        }
    )
    service = TurboRefiSessionService(
        settings=settings,
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
    )

    _session_id, response, state, _trace = service.create_session_from_received_json(
        uc1_clean_payload(),
    )

    assert state.screening_assumptions.new_rate == 5.875
    assert "5.875% screening rate" in response


def test_referred_lars_does_not_stop_conversation_before_intake_complete(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
    )

    session_id, _response, state, _trace = service.create_session_from_received_json(
        referred_uc1_payload(),
        new_rate=6.0,
    )
    assert state.borrower_facts.property_type == "condo"

    response, state, _trace = service.send_message(
        session_id,
        "I'm not totally sure. Maybe around 700? I haven't checked in a while.",
    )

    assert state.lars_result.final_score == 60
    assert state.referral_decision == "REFERRED"
    assert state.handoff_package is None
    assert "680 to 719" in response
    assert "approximate" in response
    assert response.endswith("How long have you been with your current employer?")


def test_referred_case_handoffs_only_after_docs_complete(tmp_path):
    service = TurboRefiSessionService(
        settings=build_settings(tmp_path),
        retrieval_service=FakeHierarchyRetrievalService(),
        loa_agent=FakeAgent("loa"),
        verifier_agent=FakeAgent("verifier"),
        uc1_uc2_intake_resolver=DeterministicUC1UC2IntakeResolver(),
    )

    session_id, _response, _state, _trace = service.create_session_from_received_json(
        referred_uc1_payload(),
        new_rate=6.0,
    )

    response, state, _trace = service.send_message(
        session_id,
        "I'm not totally sure. Maybe around 700? I haven't checked in a while.",
    )
    assert response.endswith("How long have you been with your current employer?")

    response, state, _trace = service.send_message(
        session_id,
        "I've been with my employer for 7 years and this is my only income.",
    )
    assert "Please upload the remaining required documents: identity, insurance, paystubs, tax_bill, w2s." in response
    assert state.handoff_package is None

    paystub_1 = PaystubData(
        employer_name="Acme Manufacturing",
        gross_this_period=3846.15,
        pay_frequency="biweekly",
        ytd_gross=25000,
        pay_period_end_date="2026-03-31",
        base_pay=3846.15,
    )
    paystub_2 = PaystubData(
        employer_name="Acme Manufacturing",
        gross_this_period=3846.15,
        pay_frequency="biweekly",
        ytd_gross=28846.15,
        pay_period_end_date="2026-04-14",
        base_pay=3846.15,
    )
    w2_2024 = W2Data(employer_name="Acme Manufacturing", wages_box1=98000, tax_year=2024)
    w2_2023 = W2Data(employer_name="Acme Manufacturing", wages_box1=96000, tax_year=2023)

    service.upload_document_json(session_id, "paystub", paystub_1.model_dump(mode="json"))
    service.upload_document_json(session_id, "paystub", paystub_2.model_dump(mode="json"))
    service.upload_document_json(session_id, "w2", w2_2024.model_dump(mode="json"))
    service.upload_document_json(session_id, "w2", w2_2023.model_dump(mode="json"))
    service.upload_document_json(session_id, "tax_bill", {"tax_bill_annual": 5400})
    service.upload_document_json(session_id, "insurance", {"insurance_annual": 1800})
    response, state, _trace = service.upload_document_json(session_id, "identity", {"document_present": True})

    assert state.handoff_package is not None
    assert state.current_phase == "handoff"
    assert "I would like to connect you with a loan officer" in response
