from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from turborefi.schemas import (
    MortgageStatementData,
    PaystubData,
    ScheduleCData,
    SessionState,
    W2Data,
)
from turborefi.services.information_firewall import build_loa_visible_session
from turborefi.services.minimal_assessment import refresh_minimal_uc1_uc2_assessment


def refresh_session_state(state: SessionState) -> SessionState:
    state.updated_at = datetime.now(UTC)
    state.income_type = "w2"
    if state.received_mortgage and state.received_mortgage.pmi_monthly and state.received_mortgage.pmi_monthly > 0:
        state.use_case = "uc2_pmi_removal"
    if state.borrower_facts.pmi_type in {"borrower_paid", "lender_paid", "unknown"}:
        state.use_case = "uc2_pmi_removal"
    state.borrower_name = "Borrower"
    return refresh_minimal_uc1_uc2_assessment(state)


def add_document_to_session(
    state: SessionState,
    *,
    doc_type: str,
    document: MortgageStatementData | PaystubData | W2Data | ScheduleCData | dict[str, Any] | BaseModel,
) -> SessionState:
    next_state = state.model_copy(deep=True)

    if doc_type == "mortgage_statement":
        assert isinstance(document, MortgageStatementData)
        next_state.documents.mortgage_statement = document
    elif doc_type == "paystub":
        assert isinstance(document, PaystubData)
        next_state.documents.paystubs.append(document)
        next_state.documents.paystubs.sort(key=lambda entry: entry.pay_period_end_date)
    elif doc_type == "w2":
        assert isinstance(document, W2Data)
        next_state.documents.w2s.append(document)
        next_state.documents.w2s.sort(key=lambda entry: entry.tax_year)
    elif doc_type == "schedule_c":
        assert isinstance(document, ScheduleCData)
        next_state.documents.schedule_c.append(document)
        next_state.documents.schedule_c.sort(key=lambda entry: entry.tax_year)
    else:
        if isinstance(document, BaseModel):
            payload = document.model_dump(mode="json")
        elif isinstance(document, dict):
            payload = document
        else:
            raise ValueError(f"Unsupported document type: {doc_type}")
        next_state.documents.additional_documents.setdefault(doc_type, []).append(payload)

    return refresh_session_state(next_state)


def session_to_agent_state(state: SessionState) -> dict:
    return build_loa_visible_session(state)
