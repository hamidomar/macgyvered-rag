# TurboRefi — Technical Specs for Conversation Flows (UC1, UC2, UC3)

**Purpose:** Engineering reference for building the RAG pipeline, agent prompts, tool integrations, and compliance scoring for the first three use cases.  
**Audience:** Software engineers designing the agent framework and RAG system.  
**Companion:** Use alongside the interactive Conversation Flows artifact (JSX) which shows the live dialogue.

---

## 1. Conversation Architecture: How a Session Flows

Every borrower session follows this lifecycle:

```
[Document Upload] → [Extraction] → [LOA Greeting + Data Review]
    → [LOA Requests Additional Docs] → [Borrower Provides Docs]
    → [RAG Retrieval] → [Tool Calls] → [LOA Assessment]
    → [Handoff to Verifier] → [Independent RAG + Recalc]
    → [Discrepancy Check] → [Compliance Score] → [Final Output]
```

The LOA drives a **natural conversation** — it does not dump all information at once. It follows a turn-by-turn pattern that mirrors how a real loan officer operates:

1. **Acknowledge** what the borrower provided (mortgage statement data).
2. **Identify gaps** — what additional docs are needed (paystubs, W-2, tax returns).
3. **Request** those docs in plain language, citing why (guideline reference internally, not to borrower).
4. **Calculate** once all inputs are available (tool calls).
5. **Assess** eligibility, citing specific guideline sections.
6. **Package** the recommendation for the Verifier.

---

## 2. System Prompt Templates

### 2.1 Loan Officer Agent (LOA) System Prompt

```
You are TurboRefi's Loan Officer Agent. You help mortgage borrowers evaluate
refinance options by following FNMA and FHLMC guidelines precisely.

CORE RULES:
1. NEVER perform math yourself. Always call the appropriate calculator tool.
2. ALWAYS cite the specific FNMA or FHLMC guideline section that supports
   your assessment (e.g., "Per FNMA B3-3.1-01...").
3. For every borrower, evaluate BOTH the FNMA and FHLMC pathways.
4. Collect information conversationally — do not ask for everything at once.
5. After the mortgage statement is parsed, identify what additional documents
   are needed based on the borrower's income type.

CONVERSATION FLOW:
- Turn 1: Review extracted mortgage statement data. Greet borrower. Identify
  income type and ask for required documentation.
- Turn 2: Receive docs. Acknowledge. Begin RAG retrieval for relevant guidelines.
- Turn 3: Present tool-call results and eligibility assessment with citations.
- Turn 4: Package Loan Recommendation Packet (structured JSON) for Verifier.

DOCUMENTATION REQUIREMENTS BY INCOME TYPE:
- W2/Salaried: 2 recent paystubs + most recent W-2 (per B3-3.2-01 / FHLMC 5302.2)
- Self-Employed: 2 years tax returns (1040) + Schedule C/K-1 (per B3-3.3-01 / FHLMC 5304.1)
- Gig/1099: 2 years 1099s + tax returns (per SEL-2025-01 / FHLMC 5303.1(e))
- Rental Income: Schedule E from tax returns (per B3-3.1-09 / FHLMC 5305)

OUTPUT FORMAT: Loan Recommendation Packet (JSON):
{
  "borrower_name": string,
  "use_case": string,
  "fnma_eligible": boolean,
  "fhlmc_eligible": boolean,
  "recommended_gse": "fnma" | "fhlmc",
  "qualifying_monthly_income": number,
  "ltv_percent": number,
  "monthly_savings_estimate": number,
  "guideline_citations": [
    {"section": "B3-3.1-01", "finding": "Income stability confirmed..."}
  ],
  "calculations": {
    "income": { "tool": "calc_w2_income", "inputs": {...}, "result": {...} },
    "ltv": { "tool": "calc_ltv", "inputs": {...}, "result": {...} }
  },
  "documentation_status": {
    "received": ["paystubs", "w2"],
    "pending": ["verbal_voe"],
    "not_required": ["tax_returns"]
  },
  "reasoning_chain": [string]
}
```

### 2.2 Verifier Agent System Prompt

```
You are TurboRefi's Verifier Agent. You independently verify every claim made
by the Loan Officer Agent (LOA). You receive the raw borrower data AND the
LOA's Loan Recommendation Packet.

CORE RULES:
1. NEVER trust the LOA's intermediate calculations. Re-derive everything.
2. Formulate your OWN RAG queries — do not reuse the LOA's queries.
3. Re-run every calculator tool with the raw inputs (not LOA outputs).
4. For each field, produce a MATCH or MISMATCH verdict.
5. Verify that every guideline citation is real and correctly applied.
6. Produce a Compliance Score (0-100) with weighted components.

VERIFICATION STEPS (execute in order):
Step 1 — Independent RAG Retrieval:
  Query the vector DB for the same guidelines the LOA should have used.
  Verify: (a) LOA cited the correct sections, (b) no sections were missed.

Step 2 — Independent Recalculation:
  Call each calculator tool with the raw borrower data.
  Compare your results against the LOA's reported values.
  Flag any delta > $0 in income or > 0.0% in LTV.

Step 3 — Documentation Completeness Audit:
  Check each required document against the relevant guideline section.
  Flag any missing items (even if they are pre-closing requirements).

Step 4 — Compliance Score Calculation:
  Compute the weighted score per the methodology below.

Step 5 — Generate Verification Report (JSON):
{
  "verification_status": "PASS" | "FAIL" | "FLAG",
  "field_comparisons": [
    {
      "field": string,
      "loa_value": any,
      "verifier_value": any,
      "match": boolean,
      "fnma_section": string,
      "notes": string
    }
  ],
  "compliance_score": {
    "total": number,
    "components": [
      { "component": string, "weight": number, "score": number, "status": string }
    ]
  },
  "re_derivation_steps": [
    {
      "step": string,
      "rag_query": string | null,
      "tool_call": string | null,
      "result": string,
      "verdict": "MATCH" | "MISMATCH" | "FLAG"
    }
  ],
  "audit_notes": [string]
}
```

---

## 3. Compliance Scoring Methodology

### 3.1 Composite Score Formula

```
Compliance Score = (GA × 0.40) + (CA × 0.30) + (DC × 0.20) + (AT × 0.10)

Where:
  GA = Guideline Adherence (0-100)
  CA = Calculation Accuracy (0-100)
  DC = Documentation Completeness (0-100)
  AT = Audit Trail Integrity (0-100)
```

### 3.2 Component Definitions and Scoring Rules

#### Guideline Adherence (GA) — Weight: 40%

Measures whether the LOA cited the correct FNMA/FHLMC sections and applied them correctly.

| Sub-Check | Points Deducted If Failed |
|-----------|--------------------------|
| LOA cited a non-existent section | -20 per instance |
| LOA cited a real section but applied it incorrectly | -15 per instance |
| LOA missed a section that should have been cited | -10 per instance |
| LOA applied an FNMA rule to an FHLMC assessment (cross-contamination) | -25 per instance |
| LOA cited the correct section and applied it correctly | 0 (no deduction) |

**Starting score: 100. Deduct per the table above. Floor: 0.**

#### Calculation Accuracy (CA) — Weight: 30%

Measures whether all tool-based calculations match between the LOA and Verifier.

| Sub-Check | Points Deducted If Failed |
|-----------|--------------------------|
| Income calculation delta > $0 | -25 per instance |
| LTV calculation delta > 0.0% | -25 per instance |
| PMI savings calculation mismatch | -15 per instance |
| NTB calculation mismatch | -25 per instance |
| All calculations match exactly | 100 (full score) |

**Note: Because all calculations use deterministic tools, any mismatch indicates a bug (wrong inputs passed to the tool), not an approximation error. This is why mismatches are penalized heavily.**

#### Documentation Completeness (DC) — Weight: 20%

Measures whether all required documents have been collected for the borrower's income type.

| Sub-Check | Points Deducted If Failed |
|-----------|--------------------------|
| Required document not received and not flagged by LOA | -20 per instance |
| Required document not received but flagged as pending | -5 per instance |
| Pre-closing requirement noted (e.g., verbal VOE, appraisal) | -5 per instance |
| All documents received and verified | 100 (full score) |

**Pending pre-closing items (verbal VOE, appraisal, business verification) are expected at this stage and only result in a -5 deduction, not a failure.**

#### Audit Trail Integrity (AT) — Weight: 10%

Measures whether every step is logged with inputs, outputs, and timestamps.

| Sub-Check | Points Deducted If Failed |
|-----------|--------------------------|
| A tool call was made but not logged | -20 per instance |
| A RAG retrieval was made but chunks not recorded | -15 per instance |
| Reasoning chain is missing a step | -10 per instance |
| All steps fully logged | 100 (full score) |

### 3.3 Score Interpretation

| Range | Verdict | Action |
|-------|---------|--------|
| 95-100 | PASS — Excellent | Proceed to final output |
| 85-94 | PASS with FLAGS | Review flagged items; proceed if flags are pre-closing items |
| 70-84 | CONDITIONAL | Address flagged items before proceeding |
| Below 70 | FAIL | Re-run LOA with corrections; if 2+ failures, escalate to human |

---

## 4. RAG Query Patterns Per Conversation Turn

### 4.1 UC1: W2 Rate-Term Refi

| Turn | Agent | Trigger | RAG Query | Expected Chunks |
|------|-------|---------|-----------|-----------------|
| 1 | LOA | Mortgage statement parsed; income_type=W2 | `gse="fnma" AND income_type="w2_salary" AND content_type="rule" → "W2 salaried income qualifying stability requirements"` | B3-3.1-01 (income principles) |
| 2 | LOA | Paystubs + W-2 received | `gse="fnma" AND income_type="w2_salary" AND content_type="documentation_requirement" → "W2 employment documentation paystub W2 verification"` | B3-3.2-01 (doc requirements) |
| 3 | LOA | Calculations complete | `gse="fnma" AND use_case_tags="uc1" AND content_type="eligibility_criteria" → "LTV eligibility matrix rate term refinance"` | B2-1.3-01 (LTV thresholds) |
| V1 | Verifier | Independent check | `gse="fnma" AND income_type="w2_salary" → "salaried employee income qualifying documentation"` | B3-3.1-01, B3-3.2-01 |
| V2 | Verifier | LTV check | `gse="fnma" AND section_id="B2-1.3-01" → "eligible LTV CLTV ratios"` | B2-1.3-01 |

### 4.2 UC2: W2 PMI Removal

| Turn | Agent | Trigger | RAG Query | Expected Chunks |
|------|-------|---------|-----------|-----------------|
| 1 | LOA | Statement shows PMI payment | `gse="fnma" AND use_case_tags="uc2" AND content_type="eligibility_criteria" → "PMI removal LTV threshold"` | B2-1.3-01 |
| 2 | LOA | Home value provided | `gse="fnma" AND income_type="w2_salary" → "W2 income qualifying"` | B3-3.1-01, B3-3.2-01 |
| 2b | LOA | FHLMC-owned loan detected | `gse="fhlmc" AND product_type="refi_possible" → "Refi Possible income AMI eligibility"` | FHLMC Refi Possible sheet |
| V1 | Verifier | PMI threshold check | `gse="fnma" AND section_id="B2-1.3-01" → "LTV PMI requirement threshold"` | B2-1.3-01 |
| V2 | Verifier | Refi Possible check | `gse="fhlmc" AND product_type="refi_possible" → "Refi Possible qualifying income AMI"` | FHLMC Refi Possible |

### 4.3 UC3: Self-Employed Rate-Term Refi

| Turn | Agent | Trigger | RAG Query | Expected Chunks |
|------|-------|---------|-----------|-----------------|
| 1 | LOA | income_type=self_employed | `gse="fnma" AND income_type="self_employed" AND content_type="documentation_requirement" → "self employed documentation tax returns Schedule C"` | B3-3.3-01 |
| 2 | LOA | Tax returns received | `gse="fnma" AND section_id="B3-3.3-03" AND content_type="formula" → "self employed income averaging Schedule C depreciation addback"` | B3-3.3-03 |
| 3 | LOA | Income calculated | `gse="fnma" AND section_id="B3-3.3-01" AND content_type="documentation_requirement" → "self employment business verification existence"` | B3-3.3-01 |
| V1 | Verifier | Income recalc | `gse="fnma" AND income_type="self_employed" AND content_type="formula" → "2 year averaging depreciation addback formula"` | B3-3.3-03 |
| V2 | Verifier | Declining income check | `gse="fnma" AND section_id="B3-3.3-03" AND content_type="exception" → "declining income self employed trend analysis"` | B3-3.3-03 |
| V3 | Verifier | Business verification | `gse="fnma" AND section_id="B3-3.3-01" AND content_type="process_step" → "business verification existence 120 days"` | B3-3.3-01 |

---

## 5. Tool Call Specifications Per Use Case

### 5.1 UC1 Tool Calls

```python
# Tool 1: W2 Income Calculator
calc_w2_income(
    gross_monthly=12500,       # From paystub
    pay_frequency="monthly",   # monthly|biweekly|weekly|semimonthly
    gse="fnma"
)
# Returns: { "annual_income": 150000, "monthly_qualifying": 12500 }

# Tool 2: LTV Calculator
calc_ltv(
    loan_amount=450000,        # From mortgage statement
    property_value=600000      # From borrower / appraisal
)
# Returns: { "ltv_ratio": 0.75, "ltv_percent": 75.0 }
```

### 5.2 UC2 Tool Calls

```python
# Tools 1 & 2: Same as UC1 (different values)
calc_w2_income(gross_monthly=6250, pay_frequency="monthly", gse="fnma")
calc_ltv(loan_amount=290000, property_value=400000)

# Tool 3: PMI Savings Calculator
calc_pmi_savings(
    current_pmi_monthly=185,   # From mortgage statement
    years_remaining=22         # Estimated remaining loan term
)
# Returns: { "total_savings": 48840, "monthly_savings": 185 }
```

### 5.3 UC3 Tool Calls

```python
# Tool 1: Self-Employed Income Calculator
calc_self_employed_income(
    yr1_net=95000,             # Schedule C Year 1
    yr2_net=110000,            # Schedule C Year 2
    depreciation=8000,         # Total depreciation addback (both years)
    depletion=0,               # If applicable
    gse="fnma"
)
# Returns: { "qualifying_monthly": 8875.0 }
# Formula: (95000 + 110000 + 8000) / 24 = 8875.00

# Tool 2: LTV Calculator
calc_ltv(loan_amount=380000, property_value=520000)
# Returns: { "ltv_ratio": 0.7308, "ltv_percent": 73.1 }
```

---

## 6. FNMA Section Reference for Audit (UC1-UC3)

This table maps every FNMA section referenced in the conversation flows to its specific audit purpose.

| FNMA Section | Title | Audit Purpose | Used In |
|-------------|-------|---------------|---------|
| B3-3.1-01 | General Income Information | Validates income stability principle: 2-year history, consistent earnings, continuance for 3+ years | UC1, UC2, UC3 |
| B3-3.2-01 | Standards for Employment Documentation | Validates document requirements: paystubs (30-day coverage), W-2 (most recent year), VOE option | UC1, UC2 |
| B3-3.1-07 | Verbal Verification of Employment | Validates verbal VOE within 10 business days of closing | UC1, UC2, UC3 |
| B3-3.1-02 | Tax Return and Transcript Requirements | Validates when tax returns are required (SE, commission >25%, etc.) | UC3 |
| B3-3.1-06 | IRS Form 4506-C Requirements | Validates IRS transcript request for tax return validation | UC3 |
| B3-3.3-01 | Underwriting Factors for SE Borrowers | Validates SE definition (25% ownership), business verification (120-day window), and general SE requirements | UC3 |
| B3-3.3-03 | Income Analysis: Individual Tax Returns | Validates Schedule C analysis, 2-year averaging formula, depreciation/depletion addbacks, declining income rules | UC3 |
| B2-1.3-01 | Eligible LTV/CLTV/HCLTV Ratios | Validates LTV eligibility matrices, PMI thresholds (80%), product-specific LTV limits | UC1, UC2 |
| B4-1.3-04 | Property Valuation (Appraisal) | Validates that property value requires formal appraisal (not just borrower estimate) | UC2 |
| B5-7-01 | High LTV Refinance Overview | Reference for comparing VA IRRRL against FNMA streamline product | (UC5 comparison) |

---

## 7. FHLMC Parallel References

| FNMA Section | Equivalent FHLMC Section | Key Difference |
|-------------|--------------------------|----------------|
| B3-3.1-01 | 5301.1 | FHLMC has explicit Charts A/B/C for income continuance |
| B3-3.2-01 | 5302.2 | FHLMC has dedicated 10-day PCV subsection |
| B3-3.1-01 (pay conversion) | 5303.1(c)(i) | FHLMC has standalone pay period conversion table |
| B3-3.3-01 | 5304.1 | FHLMC 5304.1(c) adds explicit <2yr SE rules |
| B3-3.3-03 | 5304.2 | Addback treatment may differ; check depreciation |
| B2-1.3-01 | Eligibility matrices | Different product-level LTV grids |
| — | Refi Possible product sheet | FHLMC-only: income ≤100% AMI, loan must be FHLMC-owned |
| — | Bulletin 2025-6 | Refactored 5304/5305; must use post-May-2025 version |

---

## 8. Edge Cases the Engineer Must Handle

### 8.1 UC1 Edge Cases

| Edge Case | What Happens | Guideline Reference |
|-----------|-------------|---------------------|
| Borrower recently changed jobs (< 2 years) | LOA must document justification per B3-3.1-01: same industry? Higher income? School-to-work? | B3-3.1-01 |
| Pay frequency is biweekly (not monthly) | calc_w2_income must convert: biweekly × 26 / 12 ≠ biweekly × 2 | B3-3.2-01, FHLMC 5303.1(c)(i) |
| Overtime or bonus income present | LOA must determine if consistent for 2+ years; if <25% of base, may not need separate analysis | B3-3.1-01 |
| Verbal VOE reveals borrower was terminated | Eligibility is invalidated; LOA must reject | B3-3.1-07 |

### 8.2 UC2 Edge Cases

| Edge Case | What Happens | Guideline Reference |
|-----------|-------------|---------------------|
| Borrower estimate of home value differs from appraisal | Use appraisal value; if LTV > 80%, PMI cannot be removed | B4-1.3-04, B2-1.3-01 |
| Loan is FHLMC-owned but income exceeds AMI | Refi Possible is not available; standard conventional refi only | FHLMC Refi Possible sheet |
| Second lien exists (HELOC) | Must calculate CLTV, not just LTV; may affect eligibility | B2-1.3-01 |
| PMI is lender-paid (LPMI) | Cannot be "removed" via refi — it's built into the rate; different savings calculation | B2-1.3-01 |

### 8.3 UC3 Edge Cases

| Edge Case | What Happens | Guideline Reference |
|-----------|-------------|---------------------|
| Income is declining (Year 2 < Year 1) | LOA must use the LOWER of the two years (not the average) or document why decline is non-recurring | B3-3.3-03 |
| Self-employment < 2 years | Requires additional documentation; FHLMC 5304.1(c) has specific rules | B3-3.3-01, FHLMC 5304.1(c) |
| Borrower has both W-2 and SE income | Must qualify both streams separately and combine; rental income adds a third stream (becomes UC6) | B3-3.1-01, B3-3.3-01 |
| Business shows a net loss in one year | Loss must be deducted from other income; if combined income is negative, borrower cannot qualify | B3-3.3-03 |
| Depreciation is on a rental property (not business) | Different addback rules; rental depreciation uses Schedule E, not Schedule C | B3-3.1-09 |
| K-1 income (S-Corp or Partnership) | Different analysis form: B3-3.3-04 (S-Corp) or B3-3.3-05 (Partnership); not Schedule C | B3-3.3-04, B3-3.3-05 |

---

## Appendix A: Mock Borrower Profiles (UC1-UC3)

### A.1 UC1 — Sarah Chen

```json
{
  "name": "Sarah Chen",
  "income_type": "w2",
  "employer": "Microsoft Corp",
  "hire_date": "2020-01-15",
  "annual_salary": 150000,
  "pay_frequency": "monthly",
  "gross_monthly": 12500,
  "current_rate": 7.5,
  "loan_balance": 450000,
  "property_value": 600000,
  "gse_owner": "fnma",
  "servicer": "Wells Fargo",
  "loan_number": "2019-88431",
  "credit_score": 780,
  "pmi": false,
  "monthly_pi": 3146
}
```

### A.2 UC2 — James Wilson

```json
{
  "name": "James Wilson",
  "income_type": "w2",
  "employer": "Lakewood City School District",
  "hire_date": "2018-08-20",
  "annual_salary": 75000,
  "pay_frequency": "monthly",
  "gross_monthly": 6250,
  "current_rate": 7.25,
  "loan_balance": 290000,
  "original_home_value": 350000,
  "current_home_value": 400000,
  "property_value_source": "borrower_estimate",
  "gse_owner": "fhlmc",
  "servicer": "US Bank",
  "loan_number": "2021-45219",
  "credit_score": 740,
  "pmi": true,
  "pmi_monthly": 185,
  "monthly_pi": 1978,
  "original_down_payment_pct": 10
}
```

### A.3 UC3 — Maria Garcia

```json
{
  "name": "Maria Garcia",
  "income_type": "self_employed",
  "business_name": "Garcia Design LLC",
  "business_type": "sole_proprietor",
  "years_in_business": 4,
  "tax_returns": {
    "year_1": {
      "tax_year": 2023,
      "schedule_c_net": 95000,
      "depreciation": 4000,
      "depletion": 0
    },
    "year_2": {
      "tax_year": 2024,
      "schedule_c_net": 110000,
      "depreciation": 4000,
      "depletion": 0
    }
  },
  "income_trend": "increasing",
  "yoy_change_pct": 15.8,
  "current_rate": 6.75,
  "loan_balance": 380000,
  "property_value": 520000,
  "gse_owner": "fnma",
  "servicer": "PennyMac",
  "loan_number": "2020-71033",
  "credit_score": 760,
  "pmi": false,
  "monthly_pi": 2464
}
```

---

## Appendix B: Compliance Score Worked Examples

### B.1 UC1 Score Derivation (Score: 97)

| Component | Weight | Raw Score | Deductions | Weighted |
|-----------|--------|-----------|------------|----------|
| Guideline Adherence | 40% | 98 | -2: LOA could have also cited B3-3.1-07 (VOE) proactively | 39.2 |
| Calculation Accuracy | 30% | 100 | None: all calcs match exactly | 30.0 |
| Documentation Completeness | 20% | 95 | -5: Verbal VOE pending (pre-closing) | 19.0 |
| Audit Trail Integrity | 10% | 90 | -10: Reasoning chain could include explicit DTI check | 9.0 |
| **Total** | **100%** | | | **97.2 → 97** |

### B.2 UC2 Score Derivation (Score: 91)

| Component | Weight | Raw Score | Deductions | Weighted |
|-----------|--------|-----------|------------|----------|
| Guideline Adherence | 40% | 95 | -5: Refi Possible eligibility stated as "potential" without AMI lookup | 38.0 |
| Calculation Accuracy | 30% | 100 | None | 30.0 |
| Documentation Completeness | 20% | 78 | -10: Appraisal not yet ordered; -5: AMI lookup pending; -5: VOE pending | 15.6 |
| Audit Trail Integrity | 10% | 88 | -12: Missing FHLMC pathway comparison detail | 8.8 |
| **Total** | **100%** | | | **92.4 → 91** |

### B.3 UC3 Score Derivation (Score: 93)

| Component | Weight | Raw Score | Deductions | Weighted |
|-----------|--------|-----------|------------|----------|
| Guideline Adherence | 40% | 96 | -4: Could have cited B3-3.1-06 (4506-C) proactively | 38.4 |
| Calculation Accuracy | 30% | 100 | None | 30.0 |
| Documentation Completeness | 20% | 80 | -10: Business verification pending; -5: 4506-C pending; -5: VOE pending | 16.0 |
| Audit Trail Integrity | 10% | 92 | -8: Declining income analysis could be more explicitly logged | 9.2 |
| **Total** | **100%** | | | **93.6 → 93** |

---

## Appendix C: Conversation State Object (Per-Turn Snapshot)

The Orchestrator maintains this state object throughout the session. The engineer should persist this to DynamoDB after each node execution.

```json
{
  "session_id": "uuid",
  "borrower_id": "uuid",
  "timestamp": "ISO-8601",
  "use_case_id": "uc1",
  "current_node": "fnma_eligibility",
  "borrower_data": { /* raw extracted data */ },
  "documents_received": ["mortgage_statement", "paystub_1", "paystub_2", "w2"],
  "documents_pending": ["verbal_voe"],
  "rag_retrievals": [
    {
      "agent": "loa",
      "query": "W2 salaried income qualifying...",
      "gse_filter": "fnma",
      "chunks_returned": ["chk-fnma-b33101-0003", "chk-fnma-b33201-0001"],
      "timestamp": "ISO-8601"
    }
  ],
  "tool_calls": [
    {
      "agent": "loa",
      "tool": "calc_w2_income",
      "inputs": { "gross_monthly": 12500, "pay_frequency": "monthly", "gse": "fnma" },
      "outputs": { "annual_income": 150000, "monthly_qualifying": 12500 },
      "timestamp": "ISO-8601"
    }
  ],
  "loa_output": { /* Loan Recommendation Packet */ },
  "verifier_output": { /* Verification Report */ },
  "compliance_score": { /* Scored components */ },
  "final_status": "PASS" | "FLAG" | "FAIL",
  "retry_count": 0
}
```

---

## Appendix D: Implementation Priority

| Priority | What to Build First | Why |
|----------|-------------------|-----|
| P0 | RAG pipeline with UC1 queries returning B3-3.1-01 and B3-3.2-01 | Nothing else works without guidelines in the vector DB |
| P0 | calc_w2_income + calc_ltv tools with unit tests | Agents cannot assess eligibility without calculations |
| P0 | LOA system prompt + UC1 conversation flow | Validates the end-to-end agent pipeline |
| P1 | Verifier system prompt + discrepancy check | Validates the dual-agent architecture |
| P1 | Compliance scoring engine | Validates the audit/compliance framework |
| P1 | UC2 (adds PMI calc + Refi Possible RAG) | Adds meaningful complexity and FHLMC pathway |
| P2 | UC3 (adds SE income calc + B3-3.3 RAG) | Most complex income type in the first 3 UCs |
| P2 | DynamoDB audit trail persistence | Needed for demo but not for core logic validation |
