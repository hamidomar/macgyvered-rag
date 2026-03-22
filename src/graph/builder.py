from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
import os

from src.state import TurboRefiState
from src.prompts.loa_system_prompt import LOA_SYSTEM_PROMPT
from src.tools.guide_tools import (
    list_guide_contents,
    get_guideline_section,
    search_guideline_titles,
    get_section_with_references
)
from src.tools.calculators import (
    calc_w2_income,
    calc_ltv,
    calc_pmi_savings,
    calc_se_income
)
from src.graph.nodes import (
    loa_call,
    should_continue,
    extract_mortgage_statement,
    extract_secondary_documents,
    enforce_rag_node
)
from src.config import OPENAI_MODEL

# Initialize tools
tools = [
    list_guide_contents,
    get_guideline_section,
    search_guideline_titles,
    get_section_with_references,
    calc_w2_income,
    calc_ltv,
    calc_pmi_savings,
    calc_se_income
]

llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"))
llm_with_tools = llm.bind_tools(tools)

def build_graph():
    graph = StateGraph(TurboRefiState)
    
    # Add nodes
    graph.add_node("loa_call", loa_call)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("extract_initial_docs", extract_mortgage_statement)
    graph.add_node("extract_docs", extract_secondary_documents)
    graph.add_node("enforce_rag", enforce_rag_node)
    
    # Add start logic
    graph.set_entry_point("extract_initial_docs")
    graph.add_edge("extract_initial_docs", "loa_call")
    
    # Add edges
    graph.add_conditional_edges("loa_call", should_continue, ["tools", "enforce_rag", "__end__"])
    graph.add_edge("tools", "loa_call")
    graph.add_edge("enforce_rag", "loa_call")
    
    graph.add_edge("extract_docs", "loa_call")
    
    # Compile
    checkpointer = InMemorySaver()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["extract_docs"]
    )
