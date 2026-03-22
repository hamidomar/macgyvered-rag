# TurboRefi V1 — Implementation Plan

## Scope

Build the LOA (Loan Officer Agent) V1: a LangGraph-based agent that drives a multi-turn conversation with a borrower, extracts documents, retrieves FNMA/FHLMC guidelines via `GuideTool`, calls calculator tools, and outputs a structured Loan Recommendation Packet.

**In scope:** LOA agent, document extraction, guideline retrieval tools, calculator tool stubs, LangGraph graph, UC1 end-to-end, FastAPI entry point for local testing.

**Out of scope for V1:** Verifier agent, compliance scoring, DynamoDB persistence, Dockerfile/deployment, frontend UI.

---

## Existing Assets (Do Not Rebuild)

These are already built and working. The implementation should import and wrap them, not rewrite them.

| Asset | Location | What It Does |
|---|---|---|
| `guide_tool.py` | `scripts/guide_tool.py` | `GuideTool` class — `list_contents()`, `get_section()`, `get_sections()`, `get_section_with_references()`, `search_titles()` |
| FNMA index | `output/selling_guide_preprocessed/` | `hierarchy_tree.json`, `structured_sections.json`, `cross_references.json` — 403 leaf sections |
| FHLMC index | `output/mf_guide_index/` | Same structure — 2,603 leaf sections |
| `explore_guide.py` | `scripts/explore_guide.py` | Interactive CLI for testing retrieval (reference only, not used at runtime) |

---

## Project Structure (Target)

```
RAG_Loan_Refinance/
├── data/
│   └── pdfs/                          # raw PDFs (not used at runtime)
├── output/
│   ├── selling_guide_preprocessed/    # FNMA index (existing)
│   └── mf_guide_index/               # FHLMC index (existing)
├── src/
│   ├── __init__.py
│   ├── config.py                      # Step 1: env vars, paths, model config
│   ├── state.py                       # Step 2: LangGraph state schema
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── guide_tools.py             # Step 3: GuideTool wrappers as LangGraph tools
│   │   ├── calculators.py             # Step 4: calculator stubs (trivial math only, rest are placeholders)
│   │   └── extraction.py              # Step 5: document extraction via OpenAI multimodal
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── loa_system_prompt.py       # Step 6: LOA system prompt text
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── nodes.py                   # Step 7: LangGraph node functions
│   │   └── builder.py                 # Step 8: graph construction + compilation
│   └── app.py                         # Step 9: FastAPI entry point
├── tests/
│   ├── test_calculators.py            # Step 4 tests
│   ├── test_guide_tools.py            # Step 3 tests
│   ├── test_extraction.py             # Step 5 tests
│   └── test_graph_uc1.py             # Step 9 integration test
├── scripts/
│   ├── guide_tool.py                  # existing
│   └── explore_guide.py              # existing
└── requirements.txt                   # Step 0
```

---

## Implementation Steps

### Step 0: `requirements.txt`

**IMPORTANT:** Before writing any `requirements.txt`, the coding agent MUST run `pip index versions langgraph` and `pip index versions langchain-openai` (or check PyPI) to get the actual latest stable versions. The versions below are illustrative starting points — use whatever is current at build time.

```
langgraph
langchain-openai
langchain-core
openai
fastapi
uvicorn
python-multipart
pydantic>=2.0
```

Note: `pypdf` and `pdfplumber` are only needed for preprocessing (already done). They are NOT runtime dependencies.

---

### Step 1: `src/config.py` — Configuration

Centralise all configuration: environment variables, file paths, model settings.

```python
# What this file must contain:

OPENAI_API_KEY          # from env var
OPENAI_MODEL            # default "gpt-4o" — used for LOA reasoning
OPENAI_EXTRACTION_MODEL # default "gpt-4o" — used for document extraction

FNMA_INDEX_DIR          # path to output/selling_guide_preprocessed/
FHLMC_INDEX_DIR         # path to output/mf_guide_index/

# Load both GuideTool instances at import time:
# from guide_tool import GuideTool (add scripts/ to sys.path or copy guide_tool.py into src/)
# fnma_guide = GuideTool(FNMA_INDEX_DIR)
# fhlmc_guide = GuideTool(FHLMC_INDEX_DIR)
```

**Important:** `guide_tool.py` currently lives in `scripts/`. Either copy it into `src/` or add `scripts/` to `sys.path` in `config.py`. Copying is cleaner.

---

### Step 2: `src/state.py` — LangGraph State Schema

Define the state that flows through every node. Use `Annotated` with `add_messages` for the messages list (the current LangGraph pattern for message state).

**IMPORTANT:** Before writing this, consult the current LangGraph docs for `MessagesState` or the `add_messages` reducer pattern. The verified pattern as of early 2026 is:

```python
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages

class TurboRefiState(TypedDict):
    # --- Conversation (managed by LangGraph's add_messages reducer) ---
    messages: Annotated[list, add_messages]

    # --- Session metadata ---
    session_id: str
    use_case: Optional[str]                    # "uc1" | "uc2" | "uc3" | None

    # --- Document tracking ---
    documents_received: list[str]              # ["mortgage_statement", "paystub_1", "paystub_2", "w2"]
    documents_pending: list[str]               # ["paystub_1", "paystub_2", "w2"]

    # --- Extracted data ---
    mortgage_data: Optional[dict]              # output of mortgage statement extraction
    income_docs: list[dict]                    # list of extracted paystub/W2/1040 data
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
```

**Key point:** `Annotated[list, add_messages]` is the current LangGraph way to get automatic message appending. Each node returns `{"messages": [new_message]}` and LangGraph appends it to the existing list rather than overwriting.

---

### Step 3: `src/tools/guide_tools.py` — GuideTool Wrappers

Wrap the existing `GuideTool` methods as tools the LLM can call. Use the `@tool` decorator from `langchain_core.tools`.

**Verified current pattern:**

```python
from langchain_core.tools import tool
from src.config import fnma_guide, fhlmc_guide

@tool
def get_guideline_section(section_id: str, gse: str) -> str:
    """Retrieve the full text of a specific guideline section by ID.

    Args:
        section_id: The section identifier.
                    FNMA examples: "B3-3.1-01", "B2-1.3-01"
                    FHLMC examples: "1.3", "17.2", "1.3.a"
        gse: Which guide to search — "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    result = guide.get_section(section_id)
    import json
    return json.dumps(result, indent=2)


@tool
def search_guideline_titles(query: str, gse: str) -> str:
    """Search section titles by keyword across a guide.

    Args:
        query: Space-separated keywords (AND logic). E.g. "income verification W2"
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    results = guide.search_titles(query)
    import json
    return json.dumps(results[:20], indent=2)  # cap at 20 results


@tool
def list_guide_contents(path: str, gse: str) -> str:
    """Show one level of the guide hierarchy for navigation.

    Args:
        path: A nav_id to drill into, or empty string for top level.
              FNMA examples: "A", "A2", "A2-1"
              FHLMC examples: "01", "1.3"
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    results = guide.list_contents(path if path else None)
    import json
    return json.dumps(results, indent=2)


@tool
def get_section_with_references(section_id: str, gse: str) -> str:
    """Retrieve a section AND all sections it references (1 hop).

    Args:
        section_id: The section to expand
        gse: "fnma" or "fhlmc"
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    result = guide.get_section_with_references(section_id)
    import json
    return json.dumps(result, indent=2)
```

**Note on `@tool`:** The `@tool` decorator from `langchain_core.tools` automatically generates the tool schema from the function signature and docstring. The docstring `Args:` section becomes the parameter descriptions that the LLM sees. Return type should be `str`.

**Test:** `tests/test_guide_tools.py` — call each function with known section IDs (e.g., `get_guideline_section.invoke({"section_id": "B3-3.1-01", "gse": "fnma"})`) and assert the returned string contains expected keywords.

---

### Step 4: `src/tools/calculators.py` — Calculator Tool Stubs

**IMPORTANT SCOPE RULE:** Only implement the actual math if it is trivially obvious arithmetic (division, multiplication). If the calculation requires domain knowledge about mortgage qualification rules, income averaging conventions, or regulatory formulas, implement it as a **stub that returns a plausible hardcoded result** and mark it with a `# TODO: implement real logic` comment.

```python
from langchain_core.tools import tool

@tool
def calc_ltv(loan_amount: float, property_value: float) -> str:
    """Calculate Loan-to-Value ratio.

    Args:
        loan_amount: Current loan balance
        property_value: Current estimated property value
    """
    # REAL IMPLEMENTATION — this is trivial division
    ltv_ratio = loan_amount / property_value
    ltv_percent = round(ltv_ratio * 100, 1)
    import json
    return json.dumps({"ltv_ratio": round(ltv_ratio, 4), "ltv_percent": ltv_percent})


@tool
def calc_w2_income(gross_monthly: float, pay_frequency: str, gse: str) -> str:
    """Calculate qualifying monthly income from W2/salaried employment.

    Args:
        gross_monthly: Gross income for the most recent pay period
        pay_frequency: "weekly" | "biweekly" | "semimonthly" | "monthly"
        gse: "fnma" or "fhlmc"
    """
    # STUB — pay frequency conversion may have GSE-specific nuances
    # TODO: validate against FNMA B3-3.1-01 and FHLMC 5302.2 for edge cases
    multipliers = {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12}
    annual = gross_monthly * multipliers.get(pay_frequency, 12)
    monthly_qualifying = round(annual / 12, 2)
    import json
    return json.dumps({"annual_income": round(annual, 2), "monthly_qualifying": monthly_qualifying})


@tool
def calc_pmi_savings(current_pmi_monthly: float, years_remaining: float) -> str:
    """Calculate total and monthly savings from PMI removal.

    Args:
        current_pmi_monthly: Current monthly PMI payment
        years_remaining: Estimated remaining years on the loan
    """
    # STUB — real PMI elimination depends on LTV thresholds, lender policies
    # TODO: implement full PMI removal eligibility logic per B2-1.3-01
    total_savings = round(current_pmi_monthly * years_remaining * 12, 2)
    import json
    return json.dumps({"total_savings": total_savings, "monthly_savings": current_pmi_monthly})


@tool
def calc_se_income(yr1_net: float, yr2_net: float, depreciation: float, depletion: float, gse: str) -> str:
    """Calculate qualifying monthly income for self-employed borrowers.

    Args:
        yr1_net: Year 1 net profit/loss from Schedule C
        yr2_net: Year 2 net profit/loss from Schedule C
        depreciation: Total depreciation addback (both years combined)
        depletion: Total depletion addback (both years combined, often 0)
        gse: "fnma" or "fhlmc"
    """
    # STUB — real SE income calc has declining income rules, minimum years in business, etc.
    # TODO: implement full logic per B3-3.3-03 (FNMA) and FHLMC 5304.1
    qualifying_monthly = round((yr1_net + yr2_net + depreciation + depletion) / 24, 2)
    import json
    return json.dumps({"qualifying_monthly": qualifying_monthly})
```

**Test:** `tests/test_calculators.py` — only test `calc_ltv` with real assertions. For the stubs, test that they return valid JSON with the expected keys, not that the values are "correct."

---

### Step 5: `src/tools/extraction.py` — Document Extraction

Uses OpenAI's multimodal API to read uploaded documents and return structured JSON.

```python
# This module contains:

EXTRACTION_PROMPTS = {
    "mortgage_statement": """...""",   # copy exact text from TurboRefi_Agent_Technical_Design.md
    "paystub": """...""",
    "w2": """...""",
    "schedule_c": """...""",
}

def extract_document(file_bytes: bytes, doc_type: str, mime_type: str = "application/pdf") -> dict:
    """
    Send a document to OpenAI's multimodal endpoint for structured extraction.

    Args:
        file_bytes: raw bytes of the uploaded file
        doc_type: key into EXTRACTION_PROMPTS
        mime_type: MIME type of the file

    Returns: parsed JSON dict of extracted fields

    Implementation:
        1. Base64-encode the file_bytes
        2. Build a messages array with:
           - image_url content block (base64 data URI) for the document
           - text content block with the extraction prompt
        3. Call openai.chat.completions.create() with the extraction model
        4. Parse the response as JSON
        5. Validate expected fields are present
        6. Return the dict

    Error handling:
        - If JSON parsing fails, retry once
        - If fields are missing, return partial result with "extraction_warnings" key
    """
```

**Copy the exact extraction prompts** from the `TurboRefi_Agent_Technical_Design.md` document in the repo.

**Test:** `tests/test_extraction.py` — mock the OpenAI response and validate the JSON parsing/validation logic.

---

### Step 6: `src/prompts/loa_system_prompt.py` — LOA System Prompt

Store the LOA system prompt as a Python string constant. The full prompt is specified in `docs/TurboRefi_Agent_Technical_Design.md` under the LOA System Prompt section. **Copy it exactly** including core rules, tool descriptions, documentation requirements by income type, conversation flow (Turns 1-4), and the Loan Recommendation Packet JSON schema.

```python
LOA_SYSTEM_PROMPT = """
You are TurboRefi's Loan Officer Agent...
"""
```

This is a data file, not logic. Just store the string.

---

### Step 7: `src/graph/nodes.py` — LangGraph Node Functions

Each node is a function that takes `TurboRefiState` and returns a partial state update dict.

**Verified current pattern for LLM + tools node:**

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TurboRefiState
from src.prompts.loa_system_prompt import LOA_SYSTEM_PROMPT
from src.tools.guide_tools import (
    get_guideline_section, search_guideline_titles,
    list_guide_contents, get_section_with_references,
)
from src.tools.calculators import calc_ltv, calc_w2_income, calc_pmi_savings, calc_se_income

# Collect all tools into a list
ALL_TOOLS = [
    get_guideline_section, search_guideline_titles,
    list_guide_contents, get_section_with_references,
    calc_ltv, calc_w2_income, calc_pmi_savings, calc_se_income,
]

# Create the LLM with tools bound
# ChatOpenAI.bind_tools() returns a new runnable with tools available
llm = ChatOpenAI(model="gpt-4o", temperature=0)
llm_with_tools = llm.bind_tools(ALL_TOOLS)


def loa_call(state: TurboRefiState) -> dict:
    """
    The main LOA reasoning node. Calls the LLM with:
    - LOA_SYSTEM_PROMPT prepended as a SystemMessage
    - state["messages"] as the conversation history
    - All tools bound to the model

    Returns: {"messages": [ai_response]}
    (LangGraph's add_messages reducer appends this to existing messages)
    """
    system_msg = SystemMessage(content=LOA_SYSTEM_PROMPT)
    response = llm_with_tools.invoke([system_msg] + state["messages"])
    return {"messages": [response]}
```

**Verified current pattern for tool execution node:**

```python
from langgraph.prebuilt import ToolNode

# ToolNode automatically dispatches tool calls from the last AIMessage
tool_node = ToolNode(ALL_TOOLS)
```

**Routing function (determines: call tools, or end):**

```python
from langgraph.graph import END

def should_continue(state: TurboRefiState) -> str:
    """
    Check the last message. If it has tool_calls, route to the tool node.
    Otherwise, the LOA is done with this turn — check if we're complete.
    """
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    # Check if the LOA produced a Loan Recommendation Packet
    # (parse from the last message content — look for the JSON block)
    if state.get("loan_recommendation_packet"):
        return END
    return "wait_for_input"
```

**Additional nodes:**

```python
def extract_mortgage_statement(state: TurboRefiState) -> dict:
    """
    Triggered when a mortgage statement is uploaded.
    Calls extraction.extract_document() on the uploaded file.
    Updates state with mortgage_data.
    """
    # Implementation: read file from last message, call extract_document()
    # Return: {"mortgage_data": {...}, "documents_received": [...], "current_phase": "greeting"}


def extract_secondary_documents(state: TurboRefiState) -> dict:
    """
    Triggered when secondary docs are uploaded.
    Calls extraction.extract_document() for each new doc.
    """
    # Implementation: extract each doc, append to income_docs
    # Return: {"income_docs": [...], "documents_received": [...], "documents_pending": [...]}
```

---

### Step 8: `src/graph/builder.py` — Graph Construction

Build and compile the LangGraph `StateGraph`.

**Verified current LangGraph API pattern:**

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import InMemorySaver

from src.state import TurboRefiState
from src.graph.nodes import (
    loa_call,
    should_continue,
    extract_mortgage_statement,
    extract_secondary_documents,
    ALL_TOOLS,
)


def build_graph():
    """
    Construct the TurboRefi LOA graph.

    Graph structure:

        [START]
            ↓
        [extract_mortgage]
            ↓
        [loa_call]  ←─────────────────┐
            ↓                          │
        (should_continue)              │
            ↓                          │
        ┌───┴──────────┐               │
        ↓              ↓               │
      [tools]    [wait_for_input]      │
        │              ↓               │
        └──→ loa_call  [human input]   │
                       ↓               │
                 [extract_docs]        │
                       └───────────────┘

        should_continue == END → graph terminates

    Returns: compiled graph with in-memory checkpointing
    """

    graph = StateGraph(TurboRefiState)

    # Add nodes
    graph.add_node("extract_mortgage", extract_mortgage_statement)
    graph.add_node("loa_call", loa_call)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_node("extract_docs", extract_secondary_documents)

    # Entry point
    graph.add_edge(START, "extract_mortgage")
    graph.add_edge("extract_mortgage", "loa_call")

    # After LOA call: route based on tool calls or completion
    graph.add_conditional_edges(
        "loa_call",
        should_continue,
        {
            "tools": "tools",
            "wait_for_input": "extract_docs",  # will interrupt before this node
            END: END,
        }
    )

    # After tool execution, loop back to LOA for continued reasoning
    graph.add_edge("tools", "loa_call")

    # After extracting secondary docs, back to LOA
    graph.add_edge("extract_docs", "loa_call")

    # Compile with checkpointer and human-in-the-loop interrupt
    checkpointer = InMemorySaver()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["extract_docs"],  # pause here waiting for human upload
    )
```

**IMPORTANT for the coding agent:** The exact `StateGraph`, `START`, `END`, `ToolNode`, `InMemorySaver` imports and their behavior should be verified against the installed version's docs. The pattern above is verified against LangGraph docs as of early 2026. If the API has changed, adapt accordingly — the *structure* (nodes, conditional edges, tool loop, interrupt) is correct even if specific import paths shift.

---

### Step 9: `src/app.py` — FastAPI Entry Point

A minimal API for local testing. Endpoints:

```python
# POST /session
# Accepts mortgage statement file upload.
# Creates graph, runs extract_mortgage + loa_call.
# Returns: session_id + LOA's first response (greeting + doc request)

# POST /session/{session_id}/upload
# Uploads secondary documents to an existing session.
# Resumes graph from interrupt, triggers extraction + LOA continuation.
# Returns: LOA's next response

# POST /session/{session_id}/message
# Sends a text message from the borrower.
# Returns: LOA's next response

# GET /session/{session_id}/status
# Returns current phase, docs received/pending, whether complete

# GET /session/{session_id}/result
# Returns the Loan Recommendation Packet (only when phase == "complete")
```

For local dev, use LangGraph's `InMemorySaver` (already configured in `builder.py`).

**Test:** `tests/test_graph_uc1.py` — end-to-end test for UC1:
1. Create session with mock mortgage statement data (skip actual file upload, inject pre-extracted JSON)
2. Assert LOA greets and requests paystubs + W-2
3. Inject mock paystub + W-2 data
4. Assert LOA retrieves guideline sections (B3-3.1-01 and/or B3-3.2-01)
5. Assert LOA calls `calc_w2_income` and `calc_ltv`
6. Assert LOA produces a Loan Recommendation Packet with expected structure

---

## Build Order & Dependencies

```
Step 0: requirements.txt                          # no dependencies
Step 1: config.py                                  # depends on: guide_tool.py (copy into src/)
Step 2: state.py                                   # depends on: langgraph
Step 3: guide_tools.py + tests                     # depends on: Step 1 (config with loaded GuideTool)
Step 4: calculators.py + tests                     # depends on: nothing (stubs)
Step 5: extraction.py + tests                      # depends on: Step 1 (OpenAI config)
Step 6: loa_system_prompt.py                       # depends on: nothing (data file)
Step 7: nodes.py                                   # depends on: Steps 2-6
Step 8: builder.py                                 # depends on: Step 7
Step 9: app.py + integration test                  # depends on: Step 8
```

Steps 3, 4, 5, and 6 are independent of each other and can be built in parallel.
Steps 7 and 8 require all of 2-6 to be done.
Step 9 requires 8.

---

## Validation Criteria

The V1 is "done" when `test_graph_uc1.py` passes — meaning:

1. Mortgage statement data is extracted (or mock-injected) and the LOA acknowledges it.
2. LOA correctly identifies the borrower as W2/salaried and requests paystubs + W-2.
3. After receiving income docs, LOA retrieves FNMA sections (e.g., B3-3.1-01, B3-3.2-01) via `get_guideline_section`.
4. LOA calls `calc_w2_income` and `calc_ltv` with values from the extracted data.
5. LOA produces a Loan Recommendation Packet JSON matching the schema in the system prompt.
6. The packet contains at least 2 guideline citations with real section IDs.
7. Calculator outputs in the packet are present (correctness of stub values is not asserted beyond structure).

---

## API Version Note for Coding Agent

**Do not assume import paths or function signatures from this document are frozen.** LangGraph and langchain-openai are actively evolving. Before implementing each step:

1. Check the installed package version (`pip show langgraph`, `pip show langchain-openai`).
2. Consult the official docs or source for that version if any import fails.
3. The *patterns* described here (StateGraph with TypedDict, `@tool` decorator, `ToolNode` for dispatch, `bind_tools` for LLM, `InMemorySaver` for checkpointing, `interrupt_before` for human-in-the-loop) are stable concepts. The exact module paths may shift between minor versions.

Key verified patterns as of LangGraph ~0.2.x / langchain-openai ~1.1.x:
- `from langgraph.graph import StateGraph, START, END`
- `from langgraph.graph.message import add_messages`
- `from langgraph.prebuilt import ToolNode`
- `from langgraph.checkpoint.memory import InMemorySaver`
- `from langchain_openai import ChatOpenAI`
- `from langchain_core.tools import tool`
- `llm.bind_tools([tool1, tool2])` to attach tools
- `ToolNode([tool1, tool2])` for automatic tool dispatch
- Conditional edges via `graph.add_conditional_edges("node", routing_fn, {"key": "target_node"})`

---

## Reference Documents

The coding agent should read these for detailed specifications:

| Document | What It Contains |
|---|---|
| `docs/TurboRefi_System_Overview.md` | High-level architecture, use cases, extraction details, conversation structure |
| `docs/TurboRefi_Agent_Technical_Design.md` | Exact system prompt, tool signatures, extraction prompts, conversation loop code |
| `docs/TurboRefi_TechnicalSpecs_UC1-UC3.md` | RAG query specs per UC, tool call specs with exact I/O, FNMA section references |
| `TurboRefi_ConversationFlows.jsx` | Interactive conversation examples for UC1/UC2/UC3 — use as ground truth for expected agent behavior |
