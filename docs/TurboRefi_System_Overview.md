# TurboRefi — System Overview

## What We Are Building

TurboRefi is an AI-powered mortgage refinance advisor. A borrower uploads their mortgage documents and receives a structured eligibility assessment across both FNMA (Fannie Mae) and FHLMC (Freddie Mac) pathways, with every finding cited to the specific guideline section that supports it.

The system is not a chatbot in the general sense. It follows a deterministic conversation structure — the agent knows exactly what it needs, asks for it in the right order, and produces a structured output at the end.

---

## High-Level Architecture

```
[Document Upload]
        ↓
[Extraction Layer]       ← multimodal LLM reads PDFs, outputs structured JSON
        ↓
[LOA Agent]              ← reasoning agent drives the conversation
        ↓                   retrieves guidelines, calls calc tools, builds assessment
[Loan Recommendation Packet]   ← structured JSON output
```

---

## The Two Phases

### Phase 1 — Document Extraction

A multimodal LLM reads uploaded documents and extracts structured data from them. This phase does no loan reasoning — it is purely "read this document, return these fields as JSON."

**Documents and what we extract:**

| Document | Key Fields Extracted |
|---|---|
| Mortgage Statement | Rate, balance, servicer, loan number, GSE ownership (FNMA/FHLMC), monthly P&I, PMI if present |
| Paystubs (×2) | Employer name, gross monthly income, YTD gross, pay frequency, hire date |
| W-2 | Annual income, employer name, tax year |
| 1040 + Schedule C (self-employed) | Net income year 1 and year 2, depreciation, business type |

**Standardisation note:**
W-2s and 1040s are IRS forms with fixed layouts — extraction is reliable. Paystubs vary by payroll provider but always contain the required fields. Mortgage statements are the least standardised; servicer layout varies significantly, and GSE ownership may need to be asked of the borrower directly if not present in the document.

**Flow:**
- Mortgage statement is uploaded first, always. Extraction triggers the LOA's first turn.
- Secondary documents (paystubs, W-2, tax returns) are uploaded in response to LOA requests. Each arrives, gets extracted, and the structured result is passed back into the conversation.

---

### Phase 2 — LOA Agent Reasoning

The Loan Officer Agent (LOA) drives a multi-turn conversation. It receives structured data from the extraction layer and reasons about eligibility using the regulatory guides.

**Conversation structure (4 turns):**

| Turn | What Happens |
|---|---|
| 1 | LOA reviews mortgage statement data, greets borrower, identifies income type, requests correct secondary documents |
| 2 | Secondary docs received, extraction runs, LOA acknowledges and begins guideline retrieval |
| 3 | LOA presents calculations and eligibility assessment with guideline citations |
| 4 | LOA packages the Loan Recommendation Packet JSON |

**Rules the LOA follows:**
- Never perform inline math — always call a calculator tool (or stub)
- Always cite the specific FNMA or FHLMC guideline section for every finding
- Evaluate both FNMA and FHLMC pathways for every borrower
- Collect information conversationally — one request at a time, not a dump
- Flag pending pre-closing items (verbal VOE, appraisal, business verification) explicitly — these are expected and do not block the recommendation

---

## Use Cases in Scope (V1)

| UC | Borrower Type | Key Complexity |
|---|---|---|
| UC1 | W2 salaried — rate-term refi | Baseline flow, simplest income type |
| UC2 | W2 salaried — PMI removal | Adds PMI calc, FHLMC Refi Possible check |
| UC3 | Self-employed — rate-term refi | 2-year income averaging, Schedule C addbacks, business verification |

---

## Guideline Retrieval

The LOA has access to `GuideTool` — a structured index built from the FNMA Selling Guide and FHLMC Guide. It supports:

- Lookup by section ID (e.g. `B3-3.1-01`) — returns full section text
- Keyword search across section titles
- Cross-reference traversal — given a section, find what it cites and what cites it
- Multi-guide support — FNMA and FHLMC loaded as separate instances

The agent retrieves sections at the point it needs to justify a specific claim. Retrieval and reasoning are interleaved — not a separate pre-fetch step.

---

## Output: Loan Recommendation Packet

The final output of the LOA is a structured JSON object. The agent fills this out from its own reasoning — no fields are hard-coded by us. We provide the schema as part of the system prompt; the agent populates it.

```json
{
  "borrower_name": "Sarah Chen",
  "use_case": "uc1_rate_term_refi",
  "fnma_eligible": true,
  "fhlmc_eligible": true,
  "recommended_gse": "fnma",
  "qualifying_monthly_income": 12500,
  "ltv_percent": 75.0,
  "monthly_savings_estimate": 420,
  "guideline_citations": [
    { "section": "B3-3.1-01", "finding": "Income stability confirmed — 6 years at employer exceeds 2-year minimum" },
    { "section": "B3-3.2-01", "finding": "Documentation complete — paystubs and W-2 received" },
    { "section": "B2-1.3-01", "finding": "LTV 75% within eligible range, PMI not required" }
  ],
  "calculations": {
    "income": { "tool": "calc_w2_income", "inputs": { "gross_monthly": 12500, "pay_frequency": "monthly" }, "result": { "monthly_qualifying": 12500 } },
    "ltv": { "tool": "calc_ltv", "inputs": { "loan_amount": 450000, "property_value": 600000 }, "result": { "ltv_percent": 75.0 } }
  },
  "documentation_status": {
    "received": ["mortgage_statement", "paystub_1", "paystub_2", "w2"],
    "pending": ["verbal_voe"],
    "not_required": ["tax_returns"]
  },
  "reasoning_chain": [
    "Mortgage statement parsed: FNMA-owned, 7.5% rate, $450K balance",
    "Income type identified: W2 salaried",
    "Documents requested and received: 2 paystubs + W-2",
    "B3-3.1-01 retrieved: income stability confirmed",
    "B3-3.2-01 retrieved: documentation requirements met",
    "calc_w2_income called: $12,500/month qualifying",
    "calc_ltv called: 75.0% LTV",
    "B2-1.3-01 retrieved: 75% LTV eligible, no PMI",
    "FNMA and FHLMC both eligible; FNMA recommended (loan already FNMA-owned)"
  ]
}
```

---

## What Is Out of Scope for V1

- **Verifier Agent** — the second independent agent that re-derives everything and produces a compliance score. Planned for V2.
- **DynamoDB persistence** — the session state object will be designed now but wired to storage later.
- **FHLMC Refi Possible AMI lookup** — requires an external area median income data source.
- **Full calculator tool implementations** — stubs are used in V1; real implementations in V2.

---

## Calculator Stubs (V1)

Each tool is a simple Python function that takes the required inputs and returns a deterministic result. The LOA calls these rather than doing inline math, keeping the architecture clean for when real implementations replace the stubs.

```python
def calc_w2_income(gross_monthly, pay_frequency, gse):
    # TODO: implement pay frequency conversion (biweekly, semimonthly etc.)
    return {"monthly_qualifying": gross_monthly, "annual_income": gross_monthly * 12}

def calc_ltv(loan_amount, property_value):
    ltv = round((loan_amount / property_value) * 100, 1)
    return {"ltv_ratio": ltv / 100, "ltv_percent": ltv}

def calc_pmi_savings(current_pmi_monthly, years_remaining):
    return {"monthly_savings": current_pmi_monthly, "total_savings": current_pmi_monthly * years_remaining * 12}

def calc_se_income(yr1_net, yr2_net, depreciation, depletion, gse):
    # TODO: implement GSE-specific addback rules
    monthly = round((yr1_net + yr2_net + depreciation + depletion) / 24, 2)
    return {"qualifying_monthly": monthly}
```
