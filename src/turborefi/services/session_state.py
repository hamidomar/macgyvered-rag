from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from turborefi.rules.document_requirements import get_document_status
from turborefi.schemas import (
    BorrowerCase,
    BorrowerFacts,
    DocumentSet,
    MortgageStatementData,
    PaystubData,
    ScheduleCData,
    SessionState,
    W2Data,
)
from turborefi.services.intake_service import get_intake_pending
from turborefi.services.information_firewall import build_loa_visible_session
from turborefi.services.minimal_assessment import refresh_minimal_uc1_uc2_assessment


def infer_income_type(state: SessionState) -> str:
    documents = state.documents
    declared = state.borrower_facts.declared_income_type
    if declared and declared != "unknown":
        return declared
    if documents.schedule_c:
        return "self_employed"
    if documents.paystubs or documents.w2s:
        return "w2"
    return "unknown"


def infer_use_case(state: SessionState) -> str:
    if state.income_type == "self_employed":
        return "uc3_se_rate_term"

    monthly_pmi = state.documents.mortgage_statement.monthly_pmi if state.documents.mortgage_statement else 0
    if monthly_pmi and monthly_pmi > 0:
        return "uc2_pmi_removal"
    return "uc1_rate_term_refi"


def _document_counts(documents: DocumentSet) -> dict[str, int]:
    return {
        "mortgage_statement": documents.category_count("mortgage_statement"),
        "paystubs": documents.category_count("paystubs"),
        "w2s": documents.category_count("w2s"),
        "schedule_c": documents.category_count("schedule_c"),
        "tax_returns": documents.category_count("tax_returns"),
        "1099s": documents.category_count("1099s"),
        "schedule_e": documents.category_count("schedule_e"),
    }


def refresh_session_state(state: SessionState) -> SessionState:
    documents = state.documents
    state.updated_at = datetime.now(UTC)

    if state.source_mode == "received_json_uc1_uc2":
        state.income_type = "w2"
        if state.received_mortgage and state.received_mortgage.pmi_monthly and state.received_mortgage.pmi_monthly > 0:
            state.use_case = "uc2_pmi_removal"
        if state.borrower_facts.pmi_type in {"borrower_paid", "lender_paid", "unknown"}:
            state.use_case = "uc2_pmi_removal"
        state.borrower_name = "Borrower"
        return refresh_minimal_uc1_uc2_assessment(state)

    state.income_type = infer_income_type(state)
    state.use_case = infer_use_case(state)

    if documents.mortgage_statement:
        state.borrower_name = (
            documents.mortgage_statement.borrower_name
            or state.borrower_name
            or "Borrower"
        )

    document_status = get_document_status(state.income_type, _document_counts(documents))
    state.intake_pending = get_intake_pending(state)
    state.received_documents = document_status["received"]
    state.missing_documents = document_status["missing"]
    state.pending_documents = document_status["pending"]

    if state.verifier_output is not None:
        state.current_phase = "verified"
    elif state.loa_output is not None:
        state.current_phase = "complete"
    elif documents.mortgage_statement is None:
        state.current_phase = "extraction"
    elif state.intake_pending:
        state.current_phase = "awaiting_intake"
    elif state.missing_documents:
        state.current_phase = "awaiting_docs"
    else:
        state.current_phase = "assessment"

    if state.session_name is None:
        state.session_name = state.borrower_name

    return state


def build_session_state(case: BorrowerCase) -> SessionState:
    state = SessionState(
        borrower_case_id=case.case_id,
        session_name=case.borrower_name,
        borrower_name=case.borrower_name,
        use_case=case.use_case,
        income_type=case.income_type,
        borrower_facts=case.borrower_facts.model_copy(deep=True),
        documents=case.documents.model_copy(deep=True),
    )
    return refresh_session_state(state)


def build_upload_session_state(
    mortgage_statement: MortgageStatementData,
    *,
    borrower_name: str | None = None,
    session_name: str | None = None,
    borrower_facts: BorrowerFacts | None = None,
    session_id: str | None = None,
) -> SessionState:
    state = SessionState(
        session_id=session_id or SessionState().session_id,
        session_name=session_name or borrower_name or mortgage_statement.borrower_name,
        borrower_name=borrower_name or mortgage_statement.borrower_name or "Borrower",
        borrower_facts=borrower_facts.model_copy(deep=True) if borrower_facts else BorrowerFacts(),
        documents=DocumentSet(mortgage_statement=mortgage_statement),
    )
    return refresh_session_state(state)


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
    if state.source_mode == "received_json_uc1_uc2":
        return build_loa_visible_session(state)
    return state.model_dump(mode="json")
