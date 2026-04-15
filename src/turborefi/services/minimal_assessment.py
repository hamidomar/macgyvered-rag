from __future__ import annotations

from datetime import date
from typing import Any

from turborefi.schemas import LoanRecommendationPacket, SessionState, ToolCallRecord
from turborefi.services.calculations import debts, income, ltv, mortgage, pmi, savings, variable_income
from turborefi.services.lars_engine import build_handoff_package, evaluate_lars
from turborefi.services.uc1_uc2_intake_resolver import expected_uc1_uc2_field


UC1_UC2_REQUIRED_DOCS = {
    "paystubs": 2,
    "w2s": 2,
    "identity": 1,
    "tax_bill": 1,
    "insurance": 1,
}


def _additional_count(state: SessionState, key: str) -> int:
    return state.documents.category_count(key)


def refresh_uc1_uc2_document_status(state: SessionState) -> None:
    received: list[str] = []
    missing: list[str] = []
    for key, required in UC1_UC2_REQUIRED_DOCS.items():
        if state.documents.category_count(key) >= required:
            received.append(key)
        else:
            missing.append(key)
    if state.use_case == "uc2_pmi_removal" and state.borrower_facts.pmi_type in {None, "unknown"}:
        if _additional_count(state, "pmi_statement") > 0:
            received.append("pmi_statement")
        else:
            missing.append("pmi_statement")
    state.received_documents = sorted(received)
    state.missing_documents = sorted(missing)
    state.pending_documents = []


def _latest_paystub(state: SessionState):
    if not state.documents.paystubs:
        return None
    return max(state.documents.paystubs, key=lambda entry: entry.pay_period_end_date)


def _latest_w2s(state: SessionState):
    return sorted(state.documents.w2s, key=lambda entry: entry.tax_year, reverse=True)


def _first_doc_value(state: SessionState, doc_type: str, *keys: str) -> float | None:
    docs = state.documents.additional_documents.get(doc_type) or []
    if not docs:
        return None
    payload = docs[-1]
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace("$", "").replace(",", ""))
            except ValueError:
                continue
    return None


def _today(state: SessionState) -> date:
    return state.screening_assumptions.today or date.today()


def calculate_uc1_uc2_outputs(state: SessionState) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    received = state.received_mortgage
    if received is not None and received.current_balance and received.estimated_property_value:
        outputs["ltv"] = ltv.ltv(received.current_balance, received.estimated_property_value)
        outputs["ltv_percent"] = round(outputs["ltv"] * 100, 1)
        received.ltv = outputs["ltv"]
        outputs["b11_status"] = ltv.b11_status_for_single_source()

    paystub = _latest_paystub(state)
    if paystub is not None:
        outputs["gmi"] = income.gross_monthly_income(paystub.gross_this_period, paystub.pay_frequency)
        outputs["paystub_annualized"] = income.paystub_annualized(paystub.gross_this_period, paystub.pay_frequency)
        base = paystub.base_pay if paystub.base_pay is not None else paystub.gross_this_period
        outputs["variable_income_pct"] = variable_income.variable_income_pct(
            paystub.overtime_pay,
            paystub.bonus_pay,
            paystub.commission_pay,
            base,
        )
        outputs["paystub_ytd_valid"] = income.validate_paystub_ytd(paystub.ytd_gross, paystub.gross_this_period)
        outputs["paystub_recent"] = income.validate_paystub_recency(paystub.pay_period_end_date, _today(state))
        if paystub.ocr_confidence is not None:
            outputs.setdefault("ocr_confidences", []).append(paystub.ocr_confidence)

    w2s = _latest_w2s(state)
    if len(w2s) >= 2:
        latest, prior = w2s[0], w2s[1]
        outputs["w2_income_trend"] = income.w2_income_trend(latest.wages_box1, prior.wages_box1)
        outputs["usable_w2_income"] = income.usable_w2_income(latest.wages_box1, prior.wages_box1)
        outputs["w2_years_valid"] = income.validate_w2_years(
            [entry.tax_year for entry in w2s],
            state.screening_assumptions.expected_w2_years,
        )
        if outputs.get("paystub_annualized") is not None:
            outputs["w2_paystub_diff_pct"] = income.w2_paystub_diff_pct(
                outputs["paystub_annualized"],
                latest.wages_box1,
            )
        outputs.setdefault("ocr_confidences", []).extend(
            entry.ocr_confidence for entry in w2s if entry.ocr_confidence is not None
        )

    tax_annual = _first_doc_value(state, "tax_bill", "tax_bill_annual", "annual_amount", "amount")
    insurance_annual = _first_doc_value(state, "insurance", "insurance_annual", "annual_amount", "amount")
    if received is not None and received.property_tax_annual and tax_annual is None:
        tax_annual = received.property_tax_annual
    if tax_annual is not None:
        outputs["tax_monthly"] = mortgage.tax_monthly(tax_annual)
    if insurance_annual is not None:
        outputs["insurance_monthly"] = mortgage.insurance_monthly(insurance_annual)

    if received is not None and received.current_balance and received.current_rate:
        outputs["old_pi"] = savings.old_pi(
            received.current_balance,
            received.current_rate,
            state.screening_assumptions.term_months,
        )
        if state.screening_assumptions.new_rate is not None:
            outputs["new_pi"] = savings.new_pi(
                received.current_balance,
                state.screening_assumptions.new_rate,
                state.screening_assumptions.term_months,
            )
            outputs["rate_savings"] = savings.rate_savings(outputs["old_pi"], outputs["new_pi"])
            outputs["closing_costs"] = savings.closing_cost_estimate(
                received.current_balance,
                state.screening_assumptions.closing_cost_pct,
            )

    if {"new_pi", "tax_monthly", "insurance_monthly"}.issubset(outputs):
        new_pmi = mortgage.new_pmi_for_screening(
            state.use_case,
            outputs.get("ltv"),
            received.pmi_monthly if received else None,
        )
        outputs["new_pmi"] = new_pmi
        outputs["pitia_total"] = mortgage.pitia_total(
            outputs["new_pi"],
            outputs["tax_monthly"],
            outputs["insurance_monthly"],
            hoa=state.screening_assumptions.hoa_monthly or 0.0,
            pmi=new_pmi,
        )
        if outputs.get("gmi"):
            outputs["front_dti"] = debts.front_dti(outputs["pitia_total"], outputs["gmi"])
            outputs["screening_dti"] = debts.screening_dti(
                outputs["pitia_total"],
                outputs["gmi"],
                state.screening_assumptions.monthly_debts,
            )
            if state.screening_assumptions.monthly_debts is not None:
                outputs["back_dti"] = outputs["screening_dti"]

    if state.use_case == "uc2_pmi_removal" and received is not None:
        if state.borrower_facts.purchase_price and state.borrower_facts.down_payment_amount is not None:
            outputs["original_ltv"] = pmi.original_ltv(
                state.borrower_facts.purchase_price,
                state.borrower_facts.down_payment_amount,
            )
        if received.estimated_property_value and received.current_balance:
            outputs["equity_gained"] = pmi.equity_gained(
                received.estimated_property_value,
                received.current_balance,
            )
            if state.borrower_facts.has_second_lien:
                outputs["combined_ltv"] = pmi.combined_ltv(
                    received.current_balance,
                    state.borrower_facts.second_lien_balance,
                    received.estimated_property_value,
                )
        outputs["pmi_savings"] = pmi.pmi_savings(received.pmi_monthly)
        if outputs.get("rate_savings") is not None:
            outputs["total_monthly_savings"] = pmi.total_savings_with_pmi(
                outputs["rate_savings"],
                outputs["pmi_savings"],
            )
    elif outputs.get("rate_savings") is not None:
        outputs["total_monthly_savings"] = outputs["rate_savings"]

    if outputs.get("closing_costs") is not None and outputs.get("total_monthly_savings") is not None:
        outputs["break_even_months"] = savings.break_even_months(
            outputs["closing_costs"],
            outputs["total_monthly_savings"],
        )

    return outputs


def refresh_minimal_uc1_uc2_assessment(state: SessionState) -> SessionState:
    refresh_uc1_uc2_document_status(state)
    state.calculated_outputs = calculate_uc1_uc2_outputs(state)
    state.lars_result = evaluate_lars(state)
    state.referral_decision = state.lars_result.decision
    intake_complete = expected_uc1_uc2_field(state) is None
    docs_complete = not state.missing_documents
    handoff_ready = intake_complete and docs_complete
    state.handoff_package = build_handoff_package(state) if handoff_ready else None
    if state.handoff_package is not None:
        state.current_phase = "handoff"
        state.state_machine_state = "S7_DECISION"
    elif state.unsupported_reason:
        state.current_phase = "handoff"
        state.state_machine_state = "S7_DECISION"
    elif state.missing_documents:
        state.current_phase = "awaiting_docs"
        state.state_machine_state = "S2_DOCS"
    else:
        state.current_phase = "assessment"
        state.state_machine_state = "S6_CALC"
    return state


def _tool_call(tool: str, inputs: dict[str, Any], result: dict[str, Any]) -> ToolCallRecord:
    return ToolCallRecord(tool=tool, inputs=inputs, result=result)


def build_minimal_packet(state: SessionState) -> tuple[LoanRecommendationPacket, list[ToolCallRecord]]:
    outputs = state.calculated_outputs
    use_case_threshold = 75.0 if state.use_case == "uc2_pmi_removal" else 80.0
    ltv_percent = float(outputs.get("ltv_percent") or 0.0)
    lars = state.lars_result
    fnma_eligible = bool(lars and lars.decision == "AUTOMATED" and ltv_percent <= use_case_threshold)
    fhlmc_eligible = fnma_eligible
    monthly_income = float(outputs.get("gmi") or 0.0)
    monthly_savings = float(outputs.get("total_monthly_savings") or 0.0)
    tool_calls = [
        _tool_call("calculate_uc1_uc2_outputs", {}, outputs),
        _tool_call("evaluate_lars", {}, lars.model_dump(mode="json") if lars else {}),
    ]
    packet = LoanRecommendationPacket(
        borrower_name="Borrower",
        borrower_id_token=state.borrower_id_token,
        use_case=state.use_case,
        fnma_eligible=fnma_eligible,
        fhlmc_eligible=fhlmc_eligible,
        recommended_gse="fnma",
        qualifying_monthly_income=monthly_income,
        ltv_percent=ltv_percent,
        monthly_savings_estimate=monthly_savings,
        calculations={record.tool: record for record in tool_calls},
        documentation_status={
            "received": state.received_documents,
            "pending": state.pending_documents,
            "not_required": [],
        },
        reasoning_chain=[
            "UC1/UC2 JSON-first packet built from deterministic calculators.",
            f"LARS decision: {lars.decision if lars else 'not evaluated'}.",
        ],
        calculated_outputs=outputs,
        lars_result=lars,
        handoff_package=state.handoff_package,
        screening_assumptions=state.screening_assumptions,
        source_data_warnings=state.source_data_warnings,
    )
    return packet, tool_calls
