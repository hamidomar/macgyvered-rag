from __future__ import annotations

from turborefi.schemas import SessionState
from turborefi.services.full_application_resolver import is_full_application_decision_pending
from turborefi.services.uc1_uc2_intake_resolver import (
    DeterministicUC1UC2IntakeResolver,
    UC1UC2IntakeResolution,
)


ConversationUpdate = UC1UC2IntakeResolution


def _format_money(value: float | None) -> str | None:
    if value is None:
        return None
    return f"${value:,.0f}"


def _format_percent(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.1f}%"


def _document_label(doc_type: str) -> str:
    return {
        "identity": "government ID",
        "insurance": "homeowners insurance declaration",
        "paystubs": "two most recent paystubs",
        "paystub": "paystub",
        "tax_bill": "property tax bill",
        "w2s": "two W-2s",
        "w2": "W-2",
        "schedule_c": "Schedule C",
        "pmi_statement": "PMI statement",
    }.get(doc_type, doc_type.replace("_", " "))


def _remaining_documents_text(state: SessionState) -> str:
    labels = ", ".join(state.missing_documents)
    return f"Please upload the remaining required documents: {labels}."


def automated_ready_message(state: SessionState) -> str:
    outputs = state.calculated_outputs or {}
    new_payment = _format_money(outputs.get("pitia_total"))
    savings = _format_money(outputs.get("total_monthly_savings"))
    closing_costs = _format_money(outputs.get("closing_costs"))
    break_even = outputs.get("break_even_months")
    dti = _format_percent((outputs.get("screening_dti") or outputs.get("back_dti") or outputs.get("front_dti") or 0) * 100)

    details: list[str] = []
    if new_payment:
        details.append(f"your new monthly housing payment would be about {new_payment} including taxes and insurance")
    if savings:
        details.append(f"that works out to roughly {savings} in monthly savings")

    summary = "Based on everything I’ve reviewed, "
    if details:
        summary += ". ".join(details).capitalize() + ". "

    if closing_costs and isinstance(break_even, (int, float)):
        summary += (
            f"Estimated closing costs are around {closing_costs}, so the break-even point is about {break_even:.0f} months. "
        )
    if dti and dti != "0.0%":
        summary += f"Your screening DTI is about {dti}, which is within the guideline range. "

    if state.use_case == "uc2_pmi_removal":
        summary += "Everything looks good for a refinance with PMI-removal review. "
    else:
        summary += "Everything looks good for a conventional rate-term refinance. "
    summary += "Would you like to proceed to the full application?"
    return summary


def document_upload_follow_up(state: SessionState, doc_type: str) -> str:
    if state.handoff_package is not None or state.unsupported_reason:
        return next_question(state)
    if state.missing_documents:
        return f"Thanks, I’ve got your {_document_label(doc_type)}. {_remaining_documents_text(state)}"
    if is_full_application_decision_pending(state):
        return automated_ready_message(state)
    return next_question(state)


def apply_uc1_uc2_message(state: SessionState, message: str) -> ConversationUpdate:
    return DeterministicUC1UC2IntakeResolver().resolve(state, message)


def opening_message(state: SessionState) -> str:
    received = state.received_mortgage
    if received is None:
        return "I have the intake file. Let me ask a few questions to screen the refinance."
    rate = f"{received.current_rate:.3f}%" if received.current_rate is not None else "the current rate"
    balance = f"${received.current_balance:,.0f}" if received.current_balance is not None else "the current balance"
    address = f" at {received.property_address}" if received.property_address else ""
    ltv_text = f" The working LTV estimate is {received.ltv * 100:.1f}%." if received.ltv is not None else ""
    rate_text = (
        f" Assuming a {state.screening_assumptions.new_rate:.3f}% screening rate, I can estimate savings after documents are in."
        if state.screening_assumptions.new_rate is not None
        else ""
    )

    if state.unsupported_reason:
        return f"I reviewed the received loan data for {balance}{address}. {state.unsupported_reason}"

    if state.use_case == "uc2_pmi_removal":
        if received.pmi_monthly and received.pmi_monthly > 0:
            return (
                f"Hi, I’ve reviewed your mortgage statement. You currently have a {rate} rate on a balance of {balance}{address}. "
                f"I also see ${received.pmi_monthly:,.0f} per month in PMI, so there may be an opportunity to save through a lower rate and PMI removal."
                f"{ltv_text}{rate_text} What is your approximate borrower-reported credit score range?"
            )
        return (
            f"Hi, I’ve reviewed your mortgage statement. You currently have a {rate} rate on a balance of {balance}{address}. "
            "I do not see a separate PMI line item, so I need to clarify whether PMI is built into the rate."
            f"{ltv_text} Do you know if you have borrower-paid or lender-paid PMI?"
        )

    return (
        f"Hi, I’ve reviewed your mortgage statement. You currently have a {rate} rate on a balance of {balance}{address}."
        f"{ltv_text}{rate_text} What is your approximate borrower-reported credit score range?"
    )


def next_question(state: SessionState) -> str:
    facts = state.borrower_facts
    if state.unsupported_reason:
        return "This case should be routed to a human loan officer because it is outside the UC1/UC2 minimal build."
    if state.handoff_package is not None:
        reasons = ", ".join(state.handoff_package.referral_reasons)
        return (
            "I would like to connect you with a loan officer for a closer review. "
            f"This is not a denial. The items needing review are: {reasons}. "
            "I am packaging everything collected so you will not need to repeat it."
        )
    if state.use_case == "uc2_pmi_removal" and facts.pmi_type is None and not (
        state.received_mortgage and state.received_mortgage.pmi_monthly
    ):
        return "Do you know if your PMI is borrower-paid monthly, lender-paid and built into the rate, or unclear?"
    if facts.fico_range is None:
        return "What is your approximate borrower-reported credit score range: below 620, 620-679, 680-719, 720-759, or 760 and above?"
    if facts.tenure_months is None:
        return "How long have you been with your current employer?"
    if facts.single_income_source is None:
        return "Is this your only source of income, with no side jobs, rental properties, or self-employment?"
    if facts.property_type is None:
        return "Is the property a single-family home, townhome, or condo?"
    if state.use_case == "uc2_pmi_removal" and facts.pmi_type is None:
        return "Is your PMI borrower-paid monthly or lender-paid and built into the rate?"
    if (
        state.use_case == "uc2_pmi_removal"
        and facts.purchase_price is None
        and "purchase_price" not in facts.factual_uncertainties
    ):
        return "Do you remember the purchase price and down payment?"
    if state.use_case == "uc2_pmi_removal" and facts.has_second_lien is None:
        return "Do you have a second mortgage or HELOC on the property?"
    if state.missing_documents:
        return _remaining_documents_text(state)
    if state.full_application_intent == "proceed":
        return (
            "This case is marked ready to proceed to the full application. "
            "The preliminary screen and collected documents are complete."
        )
    if state.full_application_intent == "decline":
        return "This case is complete at the preliminary-screen stage."
    if is_full_application_decision_pending(state):
        return automated_ready_message(state)
    return "I have what I need to continue the assessment."
