# TurboRefi Minimal UC1/UC2 Implementation Plan

## Purpose

This is the fast-iteration implementation plan for the current target:

- UC1: W2 Employee Rate-Term Refinance
- UC2: W2 Employee PMI Removal Refinance

Everything else from the full plan is intentionally deferred:

- UC3 self-employed
- UC4 gig worker
- UC5 VA IRRRL
- UC6 W2 + rental
- Verifier Agent
- Compliance Agent/TCS
- multi-source property valuation spread

The goal is to converge quickly on the JSON-first LOA workflow, deterministic
calculations, LARS, FNMA/FHLMC `guide_tool` retrieval, and human LO handoff for
UC1 and UC2.

## Source Inputs

Use these docs as source of truth:

- `new_docs/TurboRefi_UC1UC2_Spec.docx`
- `new_docs/TurboRefi_ConversationFlows.docx`
- `new_docs/TurboRefi_Engineering_DataSpec Share.docx`
- `new_docs/TurboRefi_Formula_CheatSheet.docx`
- `new_docs/TurboRefi_Engineer_Spec.docx`
- `new_docs/TurboRefi_Expert_Review_v2.docx`

Precedence for this minimal build:

- `TurboRefi_UC1UC2_Spec.docx` controls UC1/UC2 data fields, formulas, LARS
  factors, factor weights, document checklist, and numeric test cases.
- `TurboRefi_ConversationFlows.docx` controls borrower-facing question order,
  handoff language, and the four golden conversation flows.
- Broader docs are used only where they do not conflict with the UC1/UC2-only
  docs or the product decisions below.

Use these as received JSON examples:

- `example_json_inputs/High Balance ARM.json`
- `example_json_inputs/Low Equity.json`
- `example_json_inputs/High Rate FHA.json`
- `example_json_inputs/Near Payoff.json`
- `example_json_inputs/VA Good Rate.json`

For this minimal plan, only conventional/FHA-like W2 paths are implemented as
UC1/UC2. VA and non-W2 inputs can be classified as unsupported/deferred.

## Product Decisions

- The app starts from received JSON, not mortgage statement OCR.
- Only one subject property address and one property lookup/value are used.
  Ignore doc language about 2-3 public valuation sources or multiple property
  addresses.
- Do not implement API spread scoring. B11 is recorded as
  `not_evaluated_single_source` for audit only, not as a scored LARS factor.
- Implement UC2 U2.1 as the single-LTV borderline check from the UC1/UC2 spec:
  `0.73 <= ltv <= 0.77`. This does not require multiple property values.
- Keep Compliance Agent/TCS aside for now.
- Do not build or keep a target Verifier Agent.
- LOA must not keep or receive borrower name, profession/job title/occupation,
  race, ethnicity, sex, age, marital status, national origin, language,
  disability status, or other protected/compliance-only fields.
- LOA may use tokenized borrower ID, property address, loan/payment fields,
  employer name, income amount, tenure, FICO range, property type, and document
  status because those are needed for UC1/UC2 screening.
- Borrower names shown in the conversation-flow examples are fixture labels
  only. The implementation must not put borrower name into LOA-visible state.
- `new_rate`, term, and closing-cost assumptions must be deterministic inputs
  from request/configuration, never invented by the LLM.
- RAG must use the existing deterministic `retrival/scripts/guide_tool.py`
  through the existing retrieval wrappers. Do not introduce a new vector store.

## Keep From Current Codebase

- `src/turborefi/api.py` endpoint style
- `src/turborefi/services/session_service.py` as orchestrator
- `runtime/sessions/` JSON persistence
- `src/turborefi/agents/loan_officer.py`
- `src/turborefi/services/retrieval_service.py`
- `src/turborefi/tools/guideline_tools.py`
- `src/turborefi/extraction/` for supporting documents only
- frontend upload/chat/session shell

## Remove Or Defer

- `src/turborefi/agents/verifier.py`: not target scope
- `src/turborefi/services/verification_service.py`: not target scope
- Compliance Agent/TCS: schema placeholders only if needed, no implementation
- UC3/UC4/UC5/UC6 models/calculators/routes in this iteration
- mortgage statement OCR as primary startup path
- property API spread/range logic

## Target Minimal Backend Structure

```text
src/turborefi/
  schemas.py or schemas/
    enums.py
    received.py
    uploaded.py
    calculated.py
    documents.py
    borrower.py
    lars.py
    handoff.py
    conversation.py
    firewall.py
    packet.py
    session.py

  services/
    received_input.py
    information_firewall.py
    use_case_router.py
    state_machine.py
    conversation_flows.py
    screening_assumptions.py
    lars_engine.py
    session_service.py
    packet_builder.py
    audit_log.py
    retrieval_service.py
    retrieval_policy.py
    rag_validation.py

    calculations/
      income.py
      variable_income.py
      ltv.py
      mortgage.py
      debts.py
      savings.py
      pmi.py

  rules/
    document_requirements.py
    use_case_requirements.py
    conversation_requirements.py
    handoff_actions.py
    lars_factors.py
    lars_precedence.py
    guideline_map.py

  tools/
    calculators.py
    document_tools.py
    guideline_tools.py
    lars_tools.py

  agents/
    loan_officer.py
    common.py
```

## Received JSON Adapter

Add `src/turborefi/services/received_input.py`.

Map upstream JSON to internal received models:

- `core.balance` -> `current_balance`
- `core.rate` -> `current_rate`
- `core.monthlyPayment` -> `reported_monthly_payment`
- `core.paymentBreakdown.principal + interest` -> current P&I when present
- `core.paymentBreakdown.escrow` -> `escrow_monthly`
- `core.paymentBreakdown.pmi` -> `pmi_monthly`
- `core.loanNumber` -> `loan_number`
- `core.propertyAddress` -> `property_address`
- `core.servicer` -> `servicer_name`
- `core.loanType` -> `loan_type_detected`
- `core.rateType` -> `rate_type`
- `core.originationDate` -> `origination_date`
- `core.maturityDate` -> `maturity_date`
- `core.originalLoanAmount` -> `original_loan_amount`
- `core.propertyValue`, `core.propertyData.estimatedValue`, or
  `propertyLookup.estimatedValue` -> `api_value` and
  `estimated_property_value`
- `core.propertyData.purchasePrice` or `propertyLookup.purchasePrice` ->
  `purchase_price`
- `core.propertyData.propertyType` or `propertyLookup.propertyType` ->
  `property_type`
- `statement.statementDateRaw` -> `statement_date`
- `statement.borrowerName` -> raw borrower name, stored outside LOA-visible state
- request/config/settings `new_rate` -> `screening_assumptions.new_rate`

Rules:

- Do not send `statement.borrowerName` to LOA context.
- Treat statement/OCR fields as already normalized upstream into received JSON.
  The app should not re-extract mortgage statements in the primary path.
- If `monthlyPayment` conflicts with payment components, preserve a warning and
  compute PITIA from components.
- If no property value is present, ask for borrower estimate or use a configured
  single valuation provider.
- If `loanType == "va"`, mark unsupported/deferred for minimal UC1/UC2.
- If PMI is present, route likely UC2 and confirm with borrower.
- If PMI is not visible but the borrower asks about PMI removal or says PMI may
  be built into the rate, route as UC2 with `pmi_type = unknown` until clarified.

## Screening Assumptions

Add `src/turborefi/services/screening_assumptions.py`.

Purpose: hold deterministic assumptions used by calculators and conversation
summaries.

Fields:

- `new_rate`
- `term_months = 360`
- `closing_cost_pct = 0.015`
- `today`
- `expected_w2_years`
- `monthly_debts`, optional
- `hoa_monthly`, optional

Rules:

- `new_rate` must come from request/configuration. The LOA can say "assuming
  X%" only when this value exists.
- Do not hardcode 2024/2023 W-2 years in production code. The spec examples use
  2024/2023, but the implementation should derive or configure the two most
  recent complete W-2 years.
- If monthly debts are unavailable, calculate and label a housing-only screening
  DTI. Apply B15 if the available DTI calculation itself exceeds 43%; do not
  imply a full credit-report DTI without debt data.

## LOA-Safe Firewall

Add `src/turborefi/services/information_firewall.py`.

Functions:

- `tokenize_borrower(name, salt) -> BorrowerToken`
- `build_loa_visible_session(state) -> dict`
- `redact_for_loa_prompt(payload) -> dict`
- `assert_no_blocked_loa_fields(payload) -> None`

Blocked from LOA:

- borrower name
- profession, occupation, job title
- race
- ethnicity
- sex
- age
- marital status
- national origin
- language
- disability status
- any future compliance-only demographic fields

Allowed for UC1/UC2 LOA:

- tokenized borrower ID
- property address
- current balance/rate/payment fields
- property value estimate and LTV
- loan type and PMI status
- employer name
- income numbers
- employment tenure
- FICO range
- property type
- uploaded document status
- calculator outputs
- LARS events

Tests must prove blocked fields do not appear in LOA-visible session JSON.

## Minimal Use-Case Router

Add or refactor `src/turborefi/services/use_case_router.py`.

Routing:

- If `loan_type_detected == "va"`: unsupported/deferred in minimal build.
- If W2 path and PMI is present, borrower mentions PMI removal, or borrower says
  PMI may be lender-paid/built into the rate: UC2.
- Otherwise W2 conventional/FHA-like path: UC1.
- If borrower indicates self-employed/gig/rental/VA cash-out: deferred handoff.

Return:

- `use_case`
- `confidence`
- `reasons`
- `deferred_reason` when unsupported

## Minimal State Machine

Use Engineer Spec S0-S7, narrowed for UC1/UC2:

- `S0_INIT`
  - ingest received JSON
  - classify UC1/UC2
  - normalize one `api_value`
  - calculate initial LTV when balance and value are present
  - evaluate UC1/UC2 LTV factors that can be known before conversation
- `S1_IDENTITY`
  - request/collect government ID as a required document
  - no B13/B14 scoring in the UC1/UC2 minimal LARS set
- `S2_DOCS`
  - request UC1/UC2 docs
  - evaluate B5 and B7
  - validate paystub recency, paystub YTD, consecutive paystubs, W-2 years, and
    employer name consistency
- `S3_INCOME`
  - parse paystubs/W-2s
  - ask employment tenure and only-income-source
  - evaluate B4, B6, B8, B9, U1.1, and U1.2 using precedence rules
- `S4_CREDIT`
  - ask borrower-reported FICO range
  - evaluate B1, B2, B3
- `S5_PROPERTY`
  - use single property value
  - calculate LTV
  - evaluate B10 and B12
  - evaluate U2.1 for UC2 when single LTV is between 73% and 77%
  - mark B11 not evaluated due single source as audit status only
- `S6_CALC`
  - calculate PITIA, DTI, savings, break-even
  - evaluate B15
- `S7_DECISION`
  - if LARS >= 70: preliminary automated screening result
  - if LARS < 70: handoff package

Referral does not stop collection. Continue collecting until a useful handoff can
be generated.

## UC1 Requirements

UC1: W2 Employee Rate-Term Refinance.

Received before conversation:

- current rate
- current balance
- property address
- servicer
- loan number
- escrow if present
- loan type
- single estimated property value if available
- calculated LTV estimate if property value exists

Documents:

- 2 most recent paystubs covering consecutive pay periods
- 2 W-2s for the two most recent complete tax years
- government ID
- property tax bill
- homeowners insurance declaration

Questions in order:

1. Confirm received rate, balance, address, and statement date if available.
2. Mention the deterministic `new_rate` assumption and possible savings only if
   `new_rate` is configured.
3. Ask borrower-reported FICO range.
4. Ask employment tenure.
5. Ask whether this is the only income source.
6. Ask property type: single-family, townhome, or condo.
7. Request two most recent paystubs.
8. After paystub extraction, summarize deterministic GMI/variable-income output
   and request the two W-2s.
9. Request property tax bill and homeowners insurance declaration.
10. Present preliminary result or human handoff.

Uploaded/paystub fields:

- `paystub_gross_current`
- `paystub_ytd`
- `paystub_period_end`, must be within 30 days of `today`
- `pay_frequency`
- `employer_name`
- `paystub_base`
- `paystub_ot`
- `paystub_bonus`
- `paystub_commission`

Uploaded/W-2 fields:

- `w2_box1_yr1`
- `w2_box1_yr2`
- `w2_employer_yr1`
- `w2_employer_yr2`
- `w2_ein_yr1`
- `w2_ein_yr2`
- `w2_tax_year_yr1`
- `w2_tax_year_yr2`

Calculations:

- W2 GMI
- paystub annualized income
- W2/paystub diff
- declining W-2 income check; use the lower year if W-2 income is declining
- variable income percentage
- variable income history and decline/exclusion checks
- single-source LTV
- P&I amortization
- PITIA
- front-end and back-end DTI
- monthly savings
- closing-cost estimate
- break-even months

RAG targets through `guide_tool`:

- FNMA B3-3.1 and FHLMC Ch.5302 for W2 income
- FNMA B2-1.3 and FHLMC Refi Possible for LTV/refi limits
- FNMA B3-6 and FHLMC Ch.5401 for DTI
- FNMA B3-5.1 and FHLMC Ch.5201 for credit

## UC2 Requirements

UC2: W2 Employee PMI Removal Refinance.

UC2 includes all UC1 requirements plus PMI/equity screening.

Received before conversation:

- UC1 received data
- `pmi_monthly` from payment breakdown when visible
- purchase price if available from received JSON/property data
- single estimated property value
- single-source LTV estimate

Additional docs/questions:

- PMI billing statement only if PMI is not visible in received JSON
- original closing disclosure/HUD-1 if available
- confirm PMI amount/type
- ask original purchase price and down payment
- ask whether a second lien/HELOC exists
- ask second-lien/HELOC balance when one exists

UC2 calculations:

- UC1 W2/PITIA/DTI/savings calculations
- original LTV
- combined LTV when a second lien balance is known
- equity gained
- PMI savings
- total monthly savings = rate savings + PMI savings
- break-even months with PMI savings
- UC2 LTV threshold check at 75%
- UC2 U2.1 borderline check when `0.73 <= ltv <= 0.77`

UC2 question order when PMI is visible:

1. Opening confirms rate, balance, PMI amount, value/LTV if available, and the
   rate-plus-PMI savings opportunity.
2. Ask FICO range, employment tenure, only-income-source, and property type.
3. Ask PMI type: borrower-paid monthly vs lender-paid/built into rate.
4. Ask purchase price and down payment.
5. Ask whether a second mortgage or HELOC exists, and balance if yes.
6. Request paystubs, W-2s, tax bill, and insurance using the UC1 document flow.

UC2 question order when PMI is not visible or LPMI is suspected:

1. Opening confirms rate and balance, states no separate PMI line was visible,
   and asks whether the borrower knows if PMI exists.
2. Ask PMI type first.
3. Ask purchase price and down payment.
4. Ask whether a second mortgage or HELOC exists, and balance if yes.
5. Continue with FICO, employment tenure, only-income-source, property type, and
   the UC1 document flow.

UC2 RAG targets through `guide_tool`:

- FNMA B7-1 and FHLMC Ch.4701 for MI/PMI requirements
- FNMA B4-1.3 and FHLMC ACE waiver rules for valuation/appraisal waiver
- all UC1 targets for W2 income, LTV/refi, DTI, and credit

## Minimal Calculators

Implement deterministic calculators under `src/turborefi/services/calculations/`.

### `income.py`

- `gross_monthly_income(amount, pay_frequency)`
- `annual_salary_gmi(annual_salary)`
- `paystub_annualized(paystub_gross_current, pay_frequency)`
- `w2_paystub_diff_pct(paystub_annualized, w2_box1)`
- `w2_income_trend(w2_box1_yr1, w2_box1_yr2)`
- `usable_w2_income(w2_box1_yr1, w2_box1_yr2)`
- `employment_tenure_check(tenure_months)`
- `validate_paystub_recency(paystub_period_end, today, max_age_days=30)`
- `validate_paystub_ytd(paystub_ytd, paystub_gross_current)`
- `validate_w2_years(actual_years, expected_w2_years)`

Pay frequency formulas:

- weekly: `gross * 52 / 12`
- biweekly: `gross * 26 / 12`
- semimonthly: `gross * 2`
- monthly: `gross`
- annual salary: `annual_salary / 12`

Rules:

- W2/paystub mismatch is `abs(paystub_annualized - w2_box1_yr1) /
  w2_box1_yr1`.
- If `w2_box1_yr1 < w2_box1_yr2`, mark declining W-2 income and use the lower
  year for conservative screening.

### `variable_income.py`

- `variable_income_pct(ot, bonus, commission, base)`
- `variable_income_history_check(variable_income_present, tenure_months)`
- `variable_income_2yr_average(w2_yr1_variable, w2_yr2_variable)`
- `variable_income_decline_pct(prior_year_variable, current_year_variable)`
- `should_exclude_variable_income(decline_pct, current_year_variable)`

Rules:

- Variable income percentage is `(paystub_ot + paystub_bonus +
  paystub_commission) / paystub_base`.
- If variable income is greater than 25% of base, trigger U1.1.
- If variable income exists and tenure is under 24 months, trigger U1.2.
- If variable income declines more than 20% year over year or current-year
  variable income is zero, exclude variable income from qualifying income and
  record the exclusion reason for handoff/audit.

### `ltv.py`

- `ltv(current_balance, estimated_property_value)`
- `ltv_threshold_for_use_case("uc1" | "uc2")`
- `uc2_ltv_straddles_threshold(ltv)`
- `ltv_lars_factor(use_case, ltv)`
- `b11_status_for_single_source()`

Rules:

- UC1 threshold: 80%
- UC2 threshold: 75%
- UC2 U2.1 single-value borderline band: `0.73 <= ltv <= 0.77`
- For UC2, U2.1 and B10 are mutually exclusive:
  - `0.73 <= ltv <= 0.77` triggers U2.1
  - `ltv > 0.77` triggers B10
  - `ltv < 0.73` triggers neither
- B11 API divergence is not evaluated or scored because there is only one value

### `mortgage.py`

- `monthly_pi(principal, annual_rate_percent, term_months=360)`
- `tax_monthly(tax_bill_annual)`
- `insurance_monthly(insurance_annual)`
- `pitia_total(pi, tax, insurance, escrow=None, hoa=0, pmi=0)`
- `new_pmi_for_screening(use_case, ltv, pmi_monthly)`

Rules:

- UC1 new PMI is `$0` when new LTV is at or below 80%; otherwise keep a
  placeholder or require a PMI quote before finalizing.
- UC2 new PMI is `$0` only when PMI elimination is the scenario being screened.
- HOA can be `$0` when not provided, but condo/HOA status still triggers B12.

### `debts.py`

- `front_dti(pitia_total, gmi)`
- `back_dti(pitia_total, monthly_debts, gmi)`
- `screening_dti(pitia_total, gmi, monthly_debts=None)`
- `fnma_student_loan_payment(balance)`
- `fhlmc_student_loan_payment(balance)`

Rules:

- FNMA deferred student loan placeholder: 1% of balance.
- FHLMC deferred student loan placeholder: 0.5% of balance.
- If debt data is missing, calculate housing-only screening DTI and label it
  clearly.

### `savings.py`

- `old_pi(current_balance, current_rate, term_months=360)`
- `new_pi(current_balance, new_rate, term_months=360)`
- `rate_savings(old_pi, new_pi)`
- `closing_cost_estimate(current_balance, pct=0.015)`
- `break_even_months(closing_costs, monthly_savings)`

Rules:

- Old and new P&I both use the standard amortization formula against current
  balance.
- Closing costs are `current_balance * 0.015` for screening.

### `pmi.py`

- `pmi_savings(pmi_monthly, eliminated=True)`
- `original_ltv(purchase_price, down_payment)`
- `combined_ltv(current_balance, second_lien_balance, estimated_property_value)`
- `equity_gained(estimated_property_value, current_balance)`
- `total_savings_with_pmi(rate_savings, pmi_savings)`

Rules:

- Original LTV is `(purchase_price - down_payment) / purchase_price`.
- Equity gained for UC2 screening is `estimated_property_value -
  current_balance`.

## Minimal LARS

Implement only factors listed in `TurboRefi_UC1UC2_Spec.docx` Section 6.

Scored factors:

| Code | Condition | Deduction | Applies |
| --- | --- | ---: | --- |
| B1 | FICO below 620 | -15 | UC1/UC2 |
| B2 | FICO 620-679 | -5 | UC1/UC2 |
| B3 | FICO unknown | -15 | UC1/UC2 |
| B4 | "I'm not sure" on a factual question | -15 per occurrence | UC1/UC2 |
| B5 | Missing required document | -10 per document | UC1/UC2 |
| B6 | W2/paystub mismatch greater than 10% | -10 | UC1/UC2 |
| B7 | OCR confidence below 80% | -3 | UC1/UC2 |
| B8 | Employment under 2 years | -8 | UC1/UC2 |
| B9 | Employment gap | -10 | UC1/UC2 |
| B10 | LTV over threshold | -15 | UC1/UC2 |
| B12 | Condo/HOA | -10 | UC1/UC2 |
| B15 | DTI greater than 43% | -10 | UC1/UC2 |
| U1.1 | Variable income greater than 25% of base | -10 | UC1/UC2 |
| U1.2 | Variable income under 2-year history | -10 | UC1/UC2 |
| U2.1 | UC2 LTV straddles 75%: `0.73 <= ltv <= 0.77` | -15 | UC2 |
| U2.2 | PMI type unclear | -10 | UC2 |
| U2.3 | Second lien exists | -10 | UC2 |
| U2.4 | Purchase price unknown or uncertain | -10 | UC2 |

Not scored in the minimal UC1/UC2 build:

- B11 API divergence: audit status only, because there is one property value.
- B13 OFAC and B14 identity mismatch: present in broader docs, but not in the
  UC1/UC2 streamlined LARS table.
- U1.3 multiple employers: not listed in the UC1/UC2 streamlined LARS table.

Rules:

- start at 100
- deductions only
- floor at 0
- append immutable events
- recalculate after every new data point
- if score <70, set `referral_triggered = true` but keep collecting
- `decision = AUTOMATED` when final score is at least 70; `REFERRED` when below
  70.

Precedence/de-duplication rules:

- FICO:
  - If the borrower gives a usable range with uncertainty, apply B4 only.
  - If no usable FICO range is available, apply B3.
  - Do not apply B3 and B4 for the same FICO answer.
- UC2 LTV:
  - If `0.73 <= ltv <= 0.77`, apply U2.1 and do not also apply B10.
  - If `ltv > 0.77`, apply B10.
  - If `ltv < 0.73`, apply neither.
- UC2 uncertainty:
  - Unknown PMI type applies U2.2, not B4.
  - Unknown or uncertain purchase price applies U2.4, not B4.
- Employment tenure:
  - If variable income exists and tenure is under 24 months, apply U1.2.
  - Do not also apply B8 for the same tenure fact in that variable-income path.
  - Apply B8 when short employment tenure is an independent base-employment risk.
- B5 is per missing required document, but do not count a document as missing
  until the conversation has requested it or the case reaches decision.

Golden LARS expectations:

- UC1 clean spec case: 100, automated.
- UC1 problematic spec case without condo: 55, referred.
- UC1 problematic conversation case with condo: 45, referred.
- UC2 clean spec/conversation case: 100, automated.
- UC2 problematic spec/conversation case: 55, referred.

## Conversation Flow

Add deterministic conversation flow rules:

- `rules/conversation_requirements.py`
- `services/conversation_flows.py`

Opening message:

- confirm rate, balance, address
- include soft statement-recency ask only when statement date exists
- show property value estimate and LTV if available
- mention the configured `new_rate` assumption only when available
- mention preliminary-screening limitations

UC1 flow:

- follow `TurboRefi_ConversationFlows.docx` Case 1/2 order:
  FICO, tenure, only income source, property type, paystubs, W-2s, tax bill,
  insurance
- do not ask for rate, balance, or address from scratch

UC2 flow:

- use two variants:
  - visible PMI: FICO, tenure, income source, property type, PMI type,
    purchase/down payment, second lien, then UC1 document flow
  - PMI not visible/LPMI suspected: PMI existence/type, purchase/down payment,
    second lien, then FICO, tenure, income source, property type, and UC1
    document flow
- ask second-lien/HELOC balance when the borrower says yes

Referral flow:

- keep collecting only data that is useful for the handoff and not burdensome
- final handoff message tells borrower collected data is passed to LO
- do not make borrower repeat already-collected facts
- use "this is not a denial" style language from the conversation-flow examples
- once LARS is below 70 and the handoff is useful, do not force tax/insurance or
  other lower-value docs before human handoff

Golden conversation cases to encode as fixtures:

- Case 1 UC1 clean: LARS 100, automated, payment/savings summary shown.
- Case 2 UC1 problematic: B4, B12, U1.1, U1.2, B6 => LARS 45, referred.
- Case 3 UC2 clean: LARS 100, automated, savings includes rate and PMI.
- Case 4 UC2 problematic: U2.2, U2.4, U2.3, U2.1 => LARS 55, referred.

Agent output rules:

- The LOA must never show borrower name, even if fixture examples include names.
- The LOA must not do arithmetic in free text. It must use calculator outputs.
- The LOA must label FICO as borrower-reported.
- The LOA can invite the borrower to proceed to Gate 2/full application only
  after an automated preliminary result.
- Handoff output should name the exact unresolved items, such as PMI type,
  HELOC/CLTV treatment, valuation borderline, or income variability.

## Handoff Package

Add `schemas/handoff.py` and `rules/handoff_actions.py`.

Fields:

- borrower_id token
- use_case
- lars_score
- lars_events
- referral_reasons
- already_collected_do_not_reask
- collected_data
- missing_data
- human_action_items
- conversation_transcript
- gse_analysis if available

Action mappings:

- B5 missing W-2: help locate W-2s, order VOE if unavailable, verify through
  transcripts if needed
- B4 uncertainty: verify the uncertain fact directly
- B6 W2/paystub mismatch: reconcile paystub annualization against W-2s
- B10 LTV over threshold: review valuation and alternatives
- B12 condo/HOA: review HOA dues, condo eligibility, and project requirements
- U1.1 variable income high: document variable-income history and stability
- U1.2 variable income short history: determine whether variable income can be
  used or must be excluded
- U2.1 LTV straddles 75%: order/review valuation and evaluate PMI alternatives
- U2.2 PMI unclear: confirm borrower-paid vs lender-paid PMI
- U2.3 second lien: review CLTV, payoff/subordination/consolidation options
- U2.4 purchase price unknown: obtain closing disclosure/HUD-1 or purchase docs

## Deterministic RAG

Use existing `guide_tool` only.

Do not add a new retrieval framework.

Required functions already wrapped by `RetrievalService`/`guideline_tools`:

- `list_contents`
- `get_section`
- `search_titles`
- `get_section_with_references`

Add `services/rag_validation.py`:

- expected UC1/UC2 section families
- target-hit validation
- top-k retrieval logging

Validation accepts leaf descendants:

- `B3-3.1-01` satisfies target family `B3-3.1`
- `5302.2` satisfies `Ch.5302`

FNMA and FHLMC retrieval must stay separate by `gse`.

## API

Required endpoints:

- `POST /session/from-json`
- `POST /session/{session_id}/document-json`
- `POST /session/{session_id}/upload`
- `POST /session/{session_id}/message`
- `GET /session/{session_id}/status`
- `GET /session/{session_id}/result`
- `GET /refi/sessions`
- `GET /refi/sessions/{session_id}`

Not required for minimal target:

- `/verify`
- verifier endpoints
- Compliance Agent endpoints

Status/result should include:

- use case
- state machine state
- current phase
- screening assumptions, including `new_rate`, term, and closing-cost percent
- documents received/missing
- intake pending
- received mortgage/property data summary
- source-data warnings
- calculated output summary
- LARS score/events/referral decision
- handoff package when present
- audit/tool traces

## Frontend Minimal Changes

Update:

- `frontend/src/types/turborefi.ts`
- `frontend/src/api/turborefi.ts`
- `frontend/src/hooks/useTurboRefiSession.ts`
- `frontend/src/store.ts`

Add fields:

- `useCase`
- `stateMachineState`
- `larsScore`
- `referralDecision`
- `referralReasons`
- `handoffPackage`
- `alreadyCollectedDoNotReask`
- `calculatedOutputs`
- `screeningAssumptions`
- `sourceDataWarnings`
- `auditSummary`

Document types for minimal build:

- paystub
- w2
- tax_bill
- insurance
- identity
- pmi_statement
- closing_disclosure

## Implementation Phases

### Phase 0: Baseline

- run current tests
- add sample JSON fixtures
- add UC1/UC2 spec numeric fixtures
- add four conversation-flow golden fixtures
- add received-input adapter tests
- add LOA-safe redaction tests

### Phase 1: UC1/UC2 Schemas and JSON Start

- add received/uploaded/calculated/session models
- add screening-assumption model for `new_rate`, term, costs, and W-2 years
- add `/session/from-json`
- route UC1 vs UC2
- mark unsupported cases as deferred

### Phase 2: Calculators

- implement W2 income, variable income, LTV, PITIA, DTI, savings, PMI
- implement paystub recency/YTD validation and W-2 year/employer checks
- implement UC2 single-LTV U2.1 borderline logic
- test formula-sheet examples
- test UC1/UC2 expected values

### Phase 3: LARS and Handoff

- implement base + UC1 + UC2 LARS factors
- implement UC1/UC2 LARS precedence/de-duplication rules
- record B11 as not evaluated for single-source value, audit only
- generate handoff package
- add handoff action mappings

### Phase 4: Conversation Flow

- implement deterministic UC1/UC2 question order from
  `TurboRefi_ConversationFlows.docx`
- opening message confirms received data
- add statement-recency soft ask
- stop collection once a useful human handoff is available after referral

### Phase 5: Packet and RAG

- build Loan Recommendation Packet
- call deterministic `guide_tool` retrieval targets
- validate UC1/UC2 retrieval targets
- include citations and audit trace

### Phase 6: Frontend

- show session state, missing docs, LARS, result, and handoff data
- keep chat UI simple

## Test Plan

Unit tests:

- `tests/test_received_input.py`
- `tests/test_information_firewall.py`
- `tests/test_uc1_uc2_calculations.py`
- `tests/test_uc1_uc2_spec_cases.py`
- `tests/test_lars_uc1_uc2.py`
- `tests/test_lars_precedence_uc1_uc2.py`
- `tests/test_conversation_flows_uc1_uc2.py`
- `tests/test_conversation_golden_flows_uc1_uc2.py`
- `tests/test_handoff_actions_uc1_uc2.py`
- `tests/test_rag_validation_uc1_uc2.py`

Integration tests:

- `/session/from-json` creates session from sample JSON
- UC1 happy path builds packet
- UC2 PMI path builds packet
- UC2 LTV 75.2% triggers U2.1, not B10
- UC2 LTV over 77% triggers B10
- missing W-2 triggers B5 and handoff
- uncertainty triggers B4 and handoff
- uncertain PMI type triggers U2.2, not B4
- uncertain purchase price triggers U2.4, not B4
- variable income with tenure under 24 months triggers U1.2, not duplicate B8
- UC1 problematic conversation case with condo scores 45
- LOA-safe session excludes name/profession/protected fields
- no verifier/compliance endpoints are required

Required numeric fixture expectations:

- UC1 clean: GMI `$8,333.33`, LTV `66.7%`, new PITIA `$2,338.87`, monthly
  savings `$288.77`, LARS `100`.
- UC1 problematic spec case: U1.1, B6, U1.2, B4 => LARS `55`.
- UC2 clean: LTV `70.1%`, original LTV `90.0%`, equity `$127,000`, PMI
  savings `$175`, LARS `100`.
- UC2 problematic: U2.2, U2.1, U2.3, U2.4 => LARS `55`.

## Definition Of Done

- App starts from received JSON.
- UC1/UC2 route correctly.
- LOA context is privacy-safe.
- One property value is used; no API-spread requirement.
- UC2 U2.1 uses the single-LTV 73%-77% borderline band.
- Deterministic calculators produce expected values.
- LARS works for UC1/UC2.
- The four UC1/UC2 spec cases and four conversation-flow cases pass as golden
  tests.
- Handoff package prevents re-asking collected data.
- `guide_tool` retrieves and validates UC1/UC2 guide targets.
- Frontend can show status/result/handoff for UC1/UC2.
