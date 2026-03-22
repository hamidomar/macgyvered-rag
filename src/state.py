import operator
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages

class TurboRefiState(TypedDict):
    # --- Conversation (managed by LangGraph's add_messages reducer) ---
    messages: Annotated[list, add_messages]

    # --- Session metadata ---
    session_id: str
    use_case: Optional[str]                    # "uc1" | "uc2" | "uc3" | None

    # --- Document tracking ---
    documents_received: Annotated[list[str], operator.add]
    documents_pending: list[str]               # ["paystub_1", "paystub_2", "w2"]

    # --- Extracted data ---
    mortgage_data: Optional[dict]              # output of mortgage statement extraction
    income_docs: Annotated[list[dict], operator.add]
    borrower_name: Optional[str]

    # --- Computation results ---
    income_result: Optional[dict]              # output of calculator tool
    ltv_result: Optional[dict]                 # output of calc_ltv
    pmi_result: Optional[dict]                 # output of calc_pmi_savings (UC2 only)

    # --- RAG tracking ---
    rag_retrievals: list[dict]                 # log of every guideline retrieval

    # --- Output ---
    loan_recommendation_packet: Optional[dict]

    # --- Flow control ---
    current_phase: str                         # "extraction" | "greeting" | "awaiting_docs" | "assessment" | "packaging" | "complete"
    error: Optional[str]
