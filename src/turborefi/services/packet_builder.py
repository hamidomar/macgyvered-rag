from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from turborefi.rules.document_requirements import get_document_status
from turborefi.rules.guideline_map import USE_CASE_MAX_LTV
from turborefi.schemas import (
    BorrowerCase,
    GuidelineCitation,
    LoanRecommendationPacket,
    RetrievalEvent,
    SessionState,
    ToolCallRecord,
)
from turborefi.services.guideline_research import (
    DeterministicGuidelineResearcher,
    GuidelineResearcher,
    required_focus_keys_for_state,
)
from turborefi.services.retrieval_service import RetrievalService
from turborefi.tools.calculators import calc_ltv, calc_pmi_savings, calc_se_income, calc_w2_income


@dataclass
class PacketBuildResult:
    packet: LoanRecommendationPacket
    retrieval_events: list[RetrievalEvent]
    tool_calls: list[ToolCallRecord]


def coerce_loan_packet(raw_response: Any) -> LoanRecommendationPacket:
    content = getattr(raw_response, "content", raw_response)
    if isinstance(content, LoanRecommendationPacket):
        return content
    if isinstance(content, dict):
        return LoanRecommendationPacket.model_validate(content)
    if isinstance(content, str):
        return LoanRecommendationPacket.model_validate(json.loads(content))
    raise TypeError(f"Unsupported LOA response type: {type(content)!r}")


def _tool_call(tool_name: str, inputs: dict[str, Any], result: dict[str, Any]) -> ToolCallRecord:
    return ToolCallRecord(tool=tool_name, inputs=inputs, result=result)


def _property_value(session_state: SessionState) -> float:
    facts_value = session_state.borrower_facts.current_property_value
    statement = session_state.documents.mortgage_statement
    if facts_value and facts_value > 0:
        return facts_value
    if statement and statement.original_property_value and statement.original_property_value > 0:
        return statement.original_property_value
    if statement is None:
        raise ValueError("Mortgage statement is required before property value can be determined.")
    raise ValueError(
        "A property value is required before LTV can be calculated. Provide a statement value or borrower-stated current value."
    )


def _monthly_savings_estimate(session_state: SessionState, use_case: str) -> float:
    statement = session_state.documents.mortgage_statement
    if statement is None:
        return 0.0

    monthly_pmi = statement.monthly_pmi or 0.0
    if use_case == "uc2_pmi_removal" and monthly_pmi > 0:
        return round(monthly_pmi, 2)

    current_rate = statement.current_rate_percent
    target_rate = session_state.borrower_facts.target_rate_percent
    if target_rate is None or current_rate <= 0 or target_rate >= current_rate:
        return round(monthly_pmi, 2)

    proxy_ratio = max(current_rate - target_rate, 0) / current_rate
    return round(statement.monthly_pi * proxy_ratio + monthly_pmi, 2)


def _latest_paystub(session_state: SessionState):
    if not session_state.documents.paystubs:
        return None
    return max(session_state.documents.paystubs, key=lambda entry: entry.pay_period_end_date)


def _build_income_tool_call(session_state: SessionState) -> ToolCallRecord:
    if session_state.income_type == "self_employed":
        schedule_c_docs = sorted(session_state.documents.schedule_c, key=lambda entry: entry.tax_year)
        if len(schedule_c_docs) < 2:
            raise ValueError("Two Schedule C documents are required for self-employed income calculation.")
        yr1_doc, yr2_doc = schedule_c_docs[-2], schedule_c_docs[-1]
        inputs = {
            "yr1_net": yr1_doc.net_profit_loss,
            "yr2_net": yr2_doc.net_profit_loss,
            "depreciation": yr1_doc.depreciation + yr2_doc.depreciation,
            "depletion": 0.0,
            "gse": "fnma",
        }
        result = calc_se_income(**inputs)
        return _tool_call("calc_se_income", inputs, result)

    paystub = _latest_paystub(session_state)
    if paystub is not None:
        inputs = {
            "gross_income": paystub.gross_this_period,
            "pay_frequency": paystub.pay_frequency,
            "gse": "fnma",
        }
    elif session_state.documents.w2s:
        latest_w2 = max(session_state.documents.w2s, key=lambda entry: entry.tax_year)
        inputs = {
            "gross_income": latest_w2.wages_box1,
            "pay_frequency": "annual",
            "gse": "fnma",
        }
    else:
        raise ValueError("W-2 income calculation requires either paystubs or a W-2.")

    result = calc_w2_income(**inputs)
    return _tool_call("calc_w2_income", inputs, result)


def _build_ltv_tool_call(session_state: SessionState) -> ToolCallRecord:
    statement = session_state.documents.mortgage_statement
    if statement is None:
        raise ValueError("Mortgage statement is required before LTV can be calculated.")
    inputs = {
        "loan_amount": statement.loan_balance,
        "property_value": _property_value(session_state),
    }
    result = calc_ltv(**inputs)
    return _tool_call("calc_ltv", inputs, result)


def _build_pmi_tool_call(session_state: SessionState) -> ToolCallRecord | None:
    statement = session_state.documents.mortgage_statement
    if statement is None:
        return None
    monthly_pmi = statement.monthly_pmi or 0
    if monthly_pmi <= 0:
        return None
    inputs = {"current_pmi_monthly": monthly_pmi, "years_remaining": 1}
    result = calc_pmi_savings(**inputs)
    return _tool_call("calc_pmi_savings", inputs, result)


def _guideline_artifacts(
    session_state: SessionState,
    retrieval_service: RetrievalService,
    guideline_researcher: GuidelineResearcher | None = None,
) -> tuple[list[GuidelineCitation], list[RetrievalEvent], set[str]]:
    researcher = guideline_researcher or DeterministicGuidelineResearcher(retrieval_service)
    research_result = researcher.research(session_state)
    supported_gses = research_result.supported_gses(required_focus_keys_for_state(session_state))
    citations = [citation for citation in research_result.citations if citation.gse in supported_gses]
    return citations, research_result.retrieval_events, supported_gses


def _eligibility_flags(
    session_state: SessionState,
    *,
    qualifying_monthly_income: float,
    ltv_percent: float,
    retrieved_gses: set[str],
) -> tuple[bool, bool]:
    has_docs = not session_state.missing_documents
    has_income = qualifying_monthly_income > 0
    has_ltv = ltv_percent <= USE_CASE_MAX_LTV[session_state.use_case]
    monthly_pmi = (session_state.documents.mortgage_statement.monthly_pmi or 0) if session_state.documents.mortgage_statement else 0
    years_in_business = session_state.borrower_facts.years_in_business or 0

    additional_ok = True
    if session_state.use_case == "uc2_pmi_removal":
        additional_ok = monthly_pmi > 0 and ltv_percent <= USE_CASE_MAX_LTV["uc2_pmi_removal"]
    elif session_state.use_case == "uc3_se_rate_term":
        additional_ok = years_in_business >= 2

    fnma_eligible = "fnma" in retrieved_gses and has_docs and has_income and has_ltv and additional_ok
    fhlmc_eligible = "fhlmc" in retrieved_gses and has_docs and has_income and has_ltv and additional_ok
    return fnma_eligible, fhlmc_eligible


def _recommended_gse(
    session_state: SessionState,
    *,
    fnma_eligible: bool,
    fhlmc_eligible: bool,
) -> str:
    gse_owner = session_state.documents.mortgage_statement.gse_owner if session_state.documents.mortgage_statement else "unknown"
    if gse_owner == "fnma" and fnma_eligible:
        return "fnma"
    if gse_owner == "fhlmc" and fhlmc_eligible:
        return "fhlmc"
    if fnma_eligible:
        return "fnma"
    if fhlmc_eligible:
        return "fhlmc"
    return "fnma"


def _reasoning_chain(
    session_state: SessionState,
    *,
    doc_status: dict[str, list[str]],
    qualifying_monthly_income: float,
    ltv_percent: float,
    fnma_eligible: bool,
    fhlmc_eligible: bool,
    retrieved_gses: set[str],
) -> list[str]:
    steps = [
        f"Income type inferred as {session_state.income_type}.",
        "Required documents were evaluated against deterministic document rules.",
        f"Qualifying monthly income calculated as {qualifying_monthly_income:.2f}.",
        f"LTV calculated as {ltv_percent:.1f}%.",
        f"Expected guideline sections retrieved for available guides: {', '.join(sorted(retrieved_gses)) or 'none'}.",
    ]
    if doc_status["pending"]:
        steps.append(f"Pre-closing items remain pending: {', '.join(doc_status['pending'])}.")
    if not retrieved_gses:
        steps.append("No guide indices were available for retrieval, so guide-backed eligibility is unavailable.")
    steps.append(f"FNMA eligible: {fnma_eligible}. FHLMC eligible: {fhlmc_eligible}.")
    return steps


def build_deterministic_loan_packet(
    session_state: SessionState,
    retrieval_service: RetrievalService,
    guideline_researcher: GuidelineResearcher | None = None,
) -> PacketBuildResult:
    if session_state.documents.mortgage_statement is None:
        raise ValueError("Mortgage statement must be present before building a recommendation packet.")
    if session_state.missing_documents:
        raise ValueError(f"Missing required documents: {', '.join(session_state.missing_documents)}")

    doc_status = get_document_status(
        session_state.income_type,
        {
            "mortgage_statement": session_state.documents.category_count("mortgage_statement"),
            "paystubs": session_state.documents.category_count("paystubs"),
            "w2s": session_state.documents.category_count("w2s"),
            "schedule_c": session_state.documents.category_count("schedule_c"),
        },
    )

    income_call = _build_income_tool_call(session_state)
    ltv_call = _build_ltv_tool_call(session_state)
    pmi_call = _build_pmi_tool_call(session_state)

    income_result = income_call.result
    qualifying_monthly_income = income_result.get("monthly_qualifying") or income_result.get("qualifying_monthly")
    if qualifying_monthly_income is None:
        raise ValueError("Income calculator did not return a qualifying monthly income.")

    citations, retrieval_events, retrieved_gses = _guideline_artifacts(
        session_state,
        retrieval_service,
        guideline_researcher=guideline_researcher,
    )
    fnma_eligible, fhlmc_eligible = _eligibility_flags(
        session_state,
        qualifying_monthly_income=float(qualifying_monthly_income),
        ltv_percent=float(ltv_call.result["ltv_percent"]),
        retrieved_gses=retrieved_gses,
    )

    calculations = {
        "income": income_call,
        "ltv": ltv_call,
    }
    tool_calls = [income_call, ltv_call]
    if pmi_call is not None:
        calculations["pmi"] = pmi_call
        tool_calls.append(pmi_call)

    packet = LoanRecommendationPacket(
        borrower_name=session_state.borrower_name,
        use_case=session_state.use_case,
        fnma_eligible=fnma_eligible,
        fhlmc_eligible=fhlmc_eligible,
        recommended_gse=_recommended_gse(
            session_state,
            fnma_eligible=fnma_eligible,
            fhlmc_eligible=fhlmc_eligible,
        ),
        qualifying_monthly_income=float(qualifying_monthly_income),
        ltv_percent=float(ltv_call.result["ltv_percent"]),
        monthly_savings_estimate=_monthly_savings_estimate(session_state, session_state.use_case),
        guideline_citations=citations,
        calculations=calculations,
        documentation_status={
            "received": doc_status["received"],
            "pending": doc_status["pending"],
            "not_required": doc_status["not_required"],
        },
        reasoning_chain=_reasoning_chain(
            session_state,
            doc_status=doc_status,
            qualifying_monthly_income=float(qualifying_monthly_income),
            ltv_percent=float(ltv_call.result["ltv_percent"]),
            fnma_eligible=fnma_eligible,
            fhlmc_eligible=fhlmc_eligible,
            retrieved_gses=retrieved_gses,
        ),
    )
    return PacketBuildResult(
        packet=packet,
        retrieval_events=retrieval_events,
        tool_calls=tool_calls,
    )


def build_fixture_assessment_result(
    borrower_case: BorrowerCase,
    session_state: SessionState,
    loan_packet: LoanRecommendationPacket,
) -> dict[str, Any]:
    return {
        "case_id": borrower_case.case_id,
        "session_id": session_state.session_id,
        "borrower_name": borrower_case.borrower_name,
        "use_case": borrower_case.use_case,
        "received_documents": session_state.received_documents,
        "missing_documents": session_state.missing_documents,
        "loan_recommendation_packet": loan_packet.model_dump(mode="json"),
    }


def build_verification_result(
    borrower_case: BorrowerCase,
    session_state: SessionState,
    verification_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": borrower_case.case_id,
        "session_id": session_state.session_id,
        "borrower_name": borrower_case.borrower_name,
        "use_case": borrower_case.use_case,
        "verification_report": verification_payload,
    }
