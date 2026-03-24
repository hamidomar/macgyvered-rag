# TurboRefi — Agent Technical Design

## Overview

This document covers the technical design of the LOA (Loan Officer Agent) — how it is initialised, how it accesses guideline documents, how it is prompted, and how the conversation loop is structured in code.

---

## Guideline Document Storage and Agent Initialisation

### How the guides are stored

The FNMA and FHLMC regulatory guides are preprocessed into structured index directories — one directory per guide. Each index contains a section tree (hierarchy of parts, subparts, chapters, sections, topics), leaf section files with full extracted text, and a cross-reference graph.

```
guides/
├── selling_guide_index/       ← FNMA Selling Guide
│   ├── tree.json              ← full hierarchy
│   ├── sections/              ← one JSON file per leaf section
│   │   ├── B3-3.1-01.json
│   │   ├── B3-3.2-01.json
│   │   └── ...
│   └── xrefs.json             ← cross-reference graph
└── fhlmc_guide_index/         ← FHLMC Guide (same structure)
```

This preprocessing has already been done. `GuideTool` reads these index directories at load time.

### How the agent accesses them

The guides are **not injected into the agent's context window at startup**. Injecting both full guides would exceed any context limit and is unnecessary — the agent only ever needs a few sections at a time.

Instead, `GuideTool` is exposed to the agent as a set of callable tools. The agent retrieves sections on demand, mid-conversation, at the moment it needs to justify a claim. This is the same pattern as any other tool call.

**Initialisation sequence:**

```python
from guide_tool import GuideTool

# Load both guides at server/session startup — once, not per turn
fnma_guide = GuideTool("./guides/selling_guide_index")
fhlmc_guide = GuideTool("./guides/fhlmc_guide_index")
```

Both `GuideTool` instances are loaded once when the application starts (or once per session) and remain in memory. Individual agent calls then query these instances via tool functions.

---

## Tool Definitions

The agent has access to the following tools. Each is a Python function wrapped for the agent framework.

### Guideline retrieval tools

```python
def get_guideline_section(section_id: str, gse: str) -> dict:
    """
    Retrieve the full text of a specific guideline section by ID.
    
    Args:
        section_id: e.g. "B3-3.1-01" for FNMA, "5302.2" for FHLMC
        gse: "fnma" or "fhlmc"
    
    Returns:
        {
            "section_id": str,
            "title": str,
            "text": str,
            "references": [str],   # sections this one cites
            "cited_by": [str]      # sections that cite this one
        }
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    return guide.get_section(section_id)


def search_guideline_titles(query: str, gse: str) -> list[dict]:
    """
    Search section titles by keyword across a guide.
    
    Args:
        query: keyword string, e.g. "self employed income averaging"
        gse: "fnma" or "fhlmc"
    
    Returns:
        List of { "section_id", "title", "text_length" } sorted by relevance
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    return guide.search_titles(query)


def get_section_with_references(section_id: str, gse: str) -> dict:
    """
    Retrieve a section plus all sections it directly references (1-hop expansion).
    Useful when the agent needs full context around a guideline.
    
    Returns:
        {
            "sections": [{ section data }],
            "total_text_length": int
        }
    """
    guide = fnma_guide if gse == "fnma" else fhlmc_guide
    return guide.get_section_with_references(section_id, depth=1)
```

### Calculator stubs (V1)

```python
def calc_w2_income(gross_monthly: float, pay_frequency: str, gse: str) -> dict:
    # TODO: implement pay frequency conversion
    return {"monthly_qualifying": gross_monthly, "annual_income": gross_monthly * 12}

def calc_ltv(loan_amount: float, property_value: float) -> dict:
    ltv = round((loan_amount / property_value) * 100, 1)
    return {"ltv_ratio": ltv / 100, "ltv_percent": ltv}

def calc_pmi_savings(current_pmi_monthly: float, years_remaining: int) -> dict:
    return {"monthly_savings": current_pmi_monthly, "total_savings": current_pmi_monthly * years_remaining * 12}

def calc_se_income(yr1_net: float, yr2_net: float, depreciation: float, depletion: float, gse: str) -> dict:
    # TODO: implement GSE-specific addback rules
    monthly = round((yr1_net + yr2_net + depreciation + depletion) / 24, 2)
    return {"qualifying_monthly": monthly}
```

---

## System Prompt

The system prompt is the agent's complete operating instruction. It is set once at session initialisation and does not change during the conversation.

It contains three sections:

**1. Role and rules**
Who the agent is, what it must never do (inline math), what it must always do (cite sections, evaluate both GSEs), and what tools it has access to.

**2. Conversation flow**
The 4-turn structure the agent must follow, including what triggers each turn and what the expected output of each turn is.

**3. Output schema**
The Loan Recommendation Packet JSON structure, with field names, types, and inline comments explaining what populates each field. The agent is instructed that its Turn 4 output must be a valid JSON object matching this schema exactly.

```python
SYSTEM_PROMPT = """
You are TurboRefi's Loan Officer Agent. You help mortgage borrowers evaluate
refinance options by following FNMA and FHLMC guidelines precisely.

CORE RULES:
1. NEVER perform math yourself. Always call the appropriate calculator tool.
2. ALWAYS cite the specific FNMA or FHLMC guideline section that supports
   your assessment (e.g., "Per FNMA B3-3.1-01...").
3. For every borrower, evaluate BOTH the FNMA and FHLMC pathways.
4. Collect information conversationally — do not ask for everything at once.
5. After the mortgage statement is parsed, identify income type and request
   only the documents required for that income type.

TOOLS AVAILABLE:
- get_guideline_section(section_id, gse) — retrieve full text of a section
- search_guideline_titles(query, gse) — search section titles by keyword
- get_section_with_references(section_id, gse) — retrieve section + its refs
- calc_w2_income(gross_monthly, pay_frequency, gse)
- calc_ltv(loan_amount, property_value)
- calc_pmi_savings(current_pmi_monthly, years_remaining)
- calc_se_income(yr1_net, yr2_net, depreciation, depletion, gse)

DOCUMENTATION REQUIREMENTS BY INCOME TYPE:
- W2/Salaried: 2 recent paystubs + most recent W-2 (B3-3.2-01 / FHLMC 5302.2)
- Self-Employed: 2 years 1040 + Schedule C/K-1 (B3-3.3-01 / FHLMC 5304.1)
- Gig/1099: 2 years 1099s + tax returns (SEL-2025-01 / FHLMC 5303.1(e))
- Rental Income: Schedule E from tax returns (B3-3.1-09 / FHLMC 5305)

CONVERSATION FLOW:
Turn 1 — Mortgage statement data provided:
  - Acknowledge the extracted data
  - Identify income type
  - Request the required secondary documents (one ask, not a list dump)

Turn 2 — Secondary documents received:
  - Acknowledge receipt
  - Call get_guideline_section or search_guideline_titles for relevant sections
  - Begin eligibility assessment

Turn 3 — Assessment:
  - Call calculator tools with extracted data
  - Present findings with section citations
  - Flag any pending pre-closing items (verbal VOE, appraisal, business verification)

Turn 4 — Package:
  - Output the Loan Recommendation Packet as a JSON object
  - This must be the last thing in your Turn 4 response
  - The JSON must exactly match the schema below

OUTPUT SCHEMA (Loan Recommendation Packet):
{
  "borrower_name": "<string>",
  "use_case": "<uc1_rate_term_refi | uc2_pmi_removal | uc3_se_rate_term>",
  "fnma_eligible": <boolean>,
  "fhlmc_eligible": <boolean>,
  "recommended_gse": "<fnma | fhlmc>",
  "qualifying_monthly_income": <number — from calculator tool output>,
  "ltv_percent": <number — from calc_ltv output>,
  "monthly_savings_estimate": <number>,
  "guideline_citations": [
    { "section": "<section ID>", "finding": "<what this section confirms>" }
  ],
  "calculations": {
    "income": { "tool": "<tool name>", "inputs": {}, "result": {} },
    "ltv": { "tool": "calc_ltv", "inputs": {}, "result": {} }
  },
  "documentation_status": {
    "received": ["<doc names>"],
    "pending": ["<pre-closing items>"],
    "not_required": ["<docs not needed for this income type>"]
  },
  "reasoning_chain": ["<ordered list of reasoning steps>"]
}
"""
```

---

## Conversation Loop

The session is a standard multi-turn messages array. The orchestrator manages it.

```python
class LOASession:
    def __init__(self):
        self.messages = []          # full conversation history
        self.extracted_docs = {}    # structured data from extraction layer
        self.tools = build_tool_list()   # guideline + calc tools

    def add_document(self, doc_type: str, extracted_data: dict):
        """Called by the extraction layer after each document is parsed."""
        self.extracted_docs[doc_type] = extracted_data
        # Inject as a system message so the agent sees the parsed data
        self.messages.append({
            "role": "user",
            "content": f"[SYSTEM: Document received — {doc_type}]\n{json.dumps(extracted_data, indent=2)}"
        })

    def send(self, user_message: str) -> str:
        """Send a user turn and get the agent's response."""
        self.messages.append({"role": "user", "content": user_message})
        
        response = anthropic_client.messages.create(
            model="claude-opus-4-5",   # use Opus for final implementation
            system=SYSTEM_PROMPT,
            messages=self.messages,
            tools=self.tools,
            max_tokens=4096
        )
        
        # Handle tool calls if any
        while response.stop_reason == "tool_use":
            tool_results = execute_tool_calls(response.content)
            self.messages.append({"role": "assistant", "content": response.content})
            self.messages.append({"role": "user", "content": tool_results})
            response = anthropic_client.messages.create(
                model="claude-opus-4-5",
                system=SYSTEM_PROMPT,
                messages=self.messages,
                tools=self.tools,
                max_tokens=4096
            )
        
        assistant_message = extract_text(response.content)
        self.messages.append({"role": "assistant", "content": assistant_message})
        return assistant_message
```

---

## Document Extraction Layer

Extraction is a separate step that runs before the agent sees any document content. It uses a multimodal model (accepts PDF or image input).

```python
EXTRACTION_PROMPTS = {
    "mortgage_statement": """
        Extract the following fields from this mortgage statement.
        Return ONLY a JSON object with no explanation.
        
        {
            "current_rate_percent": <number>,
            "loan_balance": <number>,
            "servicer_name": "<string>",
            "loan_number": "<string>",
            "gse_owner": "<fnma | fhlmc | unknown>",
            "monthly_pi": <number>,
            "monthly_pmi": <number or null>,
            "original_property_value": <number or null>
        }
    """,
    
    "paystub": """
        Extract the following fields from this paystub.
        Return ONLY a JSON object with no explanation.
        
        {
            "employer_name": "<string>",
            "gross_this_period": <number>,
            "pay_frequency": "<weekly | biweekly | semimonthly | monthly>",
            "ytd_gross": <number>,
            "pay_period_end_date": "<YYYY-MM-DD>"
        }
    """,
    
    "w2": """
        Extract the following fields from this W-2 form.
        Return ONLY a JSON object with no explanation.
        
        {
            "employer_name": "<string>",
            "wages_box1": <number>,
            "tax_year": <number>
        }
    """,
    
    "schedule_c": """
        Extract the following fields from this Schedule C (Form 1040).
        Return ONLY a JSON object with no explanation.
        
        {
            "tax_year": <number>,
            "net_profit_loss": <number>,
            "depreciation": <number>,
            "business_name": "<string>"
        }
    """
}

def extract_document(pdf_bytes: bytes, doc_type: str) -> dict:
    """
    Run the extraction prompt against a document.
    Returns structured JSON or raises on parse failure.
    """
    response = anthropic_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(pdf_bytes).decode()
                    }
                },
                {
                    "type": "text",
                    "text": EXTRACTION_PROMPTS[doc_type]
                }
            ]
        }]
    )
    
    raw = response.content[0].text.strip()
    # Strip markdown fences if model wraps output
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)
```

---

## Module Structure

```
turborefi/
├── guides/
│   ├── selling_guide_index/     ← preprocessed FNMA index (GuideTool reads this)
│   └── fhlmc_guide_index/       ← preprocessed FHLMC index
├── guide_tool.py                ← existing GuideTool implementation
├── explore_guide.py             ← existing CLI explorer (dev/debug tool)
├── extraction.py                ← document extraction layer
├── tools.py                     ← guideline retrieval + calc stubs, wrapped for agent
├── prompts.py                   ← SYSTEM_PROMPT and OUTPUT_SCHEMA
├── session.py                   ← LOASession class, conversation loop
└── main.py                      ← entry point / API surface
```

---

## Notes for V2

- Replace calc stubs in `tools.py` with real implementations — no changes needed elsewhere
- Add `VerifierSession` class alongside `LOASession` in `session.py` — same loop pattern
- Add `DynamoDBPersistence` wrapper around `LOASession` — intercept `add_document` and `send` to persist state
- FHLMC Refi Possible AMI lookup: add as an additional tool `lookup_ami(zip_code)` once data source is confirmed
