from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TurboRefiState
from src.logger import get_logger
import re

logger = get_logger("orchestrator")

def loa_call(state: TurboRefiState) -> dict:
    from src.graph.builder import llm_with_tools 
    from src.prompts.loa_system_prompt import LOA_SYSTEM_PROMPT
    
    messages = state["messages"]
    
    # Prepend the system prompt if not present to ensure persona
    if not messages or getattr(messages[0], "type", "") != "system":
        messages = [SystemMessage(content=LOA_SYSTEM_PROMPT)] + messages
        
    response = llm_with_tools.invoke(messages)
    
    # Trace Goal Logging: Parse and extract the agent's thought framework
    thought_match = re.search(r"<thought>(.*?)</thought>", response.content, re.DOTALL)
    if thought_match:
        logger.info(f"[AGENT THOUGHT]: {thought_match.group(1).strip()}")
    else:
        logger.debug("[AGENT THOUGHT]: Proceeded directly without explicit <thought> wrapper.")
        
    return {"messages": [response]}

def should_continue(state: TurboRefiState) -> str:
    messages = state["messages"]
    last_message = messages[-1]

    if getattr(last_message, "tool_calls", None):
        logger.info("[ROUTING] Next Step: Agent elected to invoke TOOLS.")
        return "tools"
        
    # Enforced Iterative RAG Routing logic
    if "borrower_name" in last_message.content and "qualifying_monthly_income" in last_message.content:
        # Count tool calls in history
        tool_call_count = sum(1 for m in messages if hasattr(m, "tool_calls") and getattr(m, "tool_calls"))
        if tool_call_count < 2:
            logger.warning("[ROUTING INTERCEPT] Agent halted attempting premature conclusion without necessary guide traversal.")
            return "enforce_rag"

    logger.info("[ROUTING] Assessment concluding. Returning to user.")
    return "__end__"

def extract_mortgage_statement(state: TurboRefiState) -> dict:
    """Invoked after the initial mortgage statement upload."""
    return {"current_phase": "greeting"}

def extract_secondary_documents(state: TurboRefiState) -> dict:
    """
    Template Verification Gateway.
    Checks the uploaded parsed json inside income_docs.
    """
    income_docs = state.get("income_docs", [])
    
    missing_fields = []
    
    for doc in income_docs:
        # Infer doc type based on keys to run template validation
        if "gross_this_period" in doc: # Paystub
            if not doc.get("employer_name") or not doc.get("gross_this_period"):
                missing_fields.append("Paystub is missing employer name or gross income.")
        elif "wages_box1" in doc: # W2
            if not doc.get("wages_box1") or not doc.get("tax_year"):
                missing_fields.append("W-2 is missing wages or tax year.")
        elif "net_profit_loss" in doc: # Schedule C
            if not doc.get("net_profit_loss"):
                missing_fields.append("Schedule C is missing net profit/loss.")
                
    if missing_fields:
        error_msg = f"[SYSTEM: Template Verification Failed]\nThe extracted documents are missing required fields (likely bad PDF scan): {' '.join(missing_fields)}\nDo not proceed to RAG assessment until you ask the borrower for these exact missing numbers manually."
        return {
            "current_phase": "greeting",
            "messages": [HumanMessage(content=error_msg)]
        }
        
    return {"current_phase": "assessment"}

def enforce_rag_node(state: TurboRefiState) -> dict:
    """Forces the LLM to traverse the guide instead of hallucinating."""
    msg = "[SYSTEM: Orchestration Enforcement]\nYou attempted to conclude without calling the required retrieval tools (list_guide_contents, get_guideline_section). DO NOT GUESS. You must traverse the guides to find explicit FNMA and FHLMC rules before concluding."
    return {"messages": [HumanMessage(content=msg)]}
