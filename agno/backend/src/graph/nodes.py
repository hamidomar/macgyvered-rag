from __future__ import annotations

from src.state import TurboRefiState


def extract_mortgage_statement(state: TurboRefiState) -> dict:
    """Invoked after the initial mortgage statement upload."""
    return {"current_phase": "greeting"}


def extract_secondary_documents(state: TurboRefiState) -> dict:
    """
    Template Verification Gateway.
    Checks the uploaded parsed json inside income_docs.
    """
    income_docs = state.get("income_docs", [])
    missing_fields: list[str] = []

    for doc in income_docs:
        if "gross_this_period" in doc:
            if not doc.get("employer_name") or not doc.get("gross_this_period"):
                missing_fields.append("Paystub is missing employer name or gross income.")
        elif "wages_box1" in doc:
            if not doc.get("wages_box1") or not doc.get("tax_year"):
                missing_fields.append("W-2 is missing wages or tax year.")
        elif "net_profit_loss" in doc:
            if not doc.get("net_profit_loss"):
                missing_fields.append("Schedule C is missing net profit/loss.")

    if missing_fields:
        error_msg = (
            "[SYSTEM: Template Verification Failed]\n"
            "The extracted documents are missing required fields (likely bad PDF scan): "
            f"{' '.join(missing_fields)}\n"
            "Do not proceed to RAG assessment until you ask the borrower for these exact missing numbers manually."
        )
        return {
            "current_phase": "greeting",
            "message_content": error_msg,
        }

    return {"current_phase": "assessment", "message_content": None}


def should_continue(response_content: str, state: TurboRefiState) -> str:
    if should_enforce_rag(response_content, state):
        return "enforce_rag"
    return "__end__"


def should_enforce_rag(response_content: str, state: TurboRefiState) -> bool:
    if "borrower_name" in response_content and "qualifying_monthly_income" in response_content:
        tool_call_count = len(state.get("tool_call_history", []))
        return tool_call_count < 2
    return False


def build_enforce_rag_message() -> str:
    return (
        "[SYSTEM: Orchestration Enforcement]\n"
        "You attempted to conclude without calling the required retrieval tools "
        "(list_guide_contents, get_guideline_section). DO NOT GUESS. You must traverse "
        "the guides to find explicit FNMA and FHLMC rules before concluding."
    )


def enforce_rag_node(state: TurboRefiState) -> dict:
    """Forces the LLM to traverse the guide instead of hallucinating."""
    return {"message_content": build_enforce_rag_message()}
