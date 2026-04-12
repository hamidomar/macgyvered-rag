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

- `new_docs/TurboRefi_Engineering_DataSpec Share.docx`
- `new_docs/TurboRefi_Formula_CheatSheet.docx`
- `new_docs/TurboRefi_Engineer_Spec.docx`
- `new_docs/TurboRefi_Expert_Review_v2.docx`

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
  `not_evaluated_single_source`.
- Do not implement UC2 LTV-straddles-75 range logic. U2.1 is
  `not_applicable_single_source` until ranges return.
- Keep Compliance Agent/TCS aside for now.
- Do not build or keep a target Verifier Agent.
- LOA must not keep or receive borrower name, profession/job title/occupation,
  race, ethnicity, sex, age, marital status, national origin, language,
  disability status, or other protected/compliance-only fields.
- LOA may use tokenized borrower ID, property address, loan/payment fields,
  employer name, income amount, tenure, FICO range, property type, and document
  status because those are needed for UC1/UC2 screening.
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
  `propertyLookup.estimatedValue` -> `estimated_property_value`
- `core.propertyData.purchasePrice` or `propertyLookup.purchasePrice` ->
  `purchase_price`
- `core.propertyData.propertyType` or `propertyLookup.propertyType` ->
  `property_type`
- `statement.statementDateRaw` -> `statement_date`
- `statement.borrowerName` -> raw borrower name, stored outside LOA-visible state

Rules:

- Do not send `statement.borrowerName` to LOA context.
- If `monthlyPayment` conflicts with payment components, preserve a warning and
  compute PITIA from components.
- If no property value is present, ask for borrower estimate or use a configured
  single valuation provider.
- If `loanType == "va"`, mark unsupported/deferred for minimal UC1/UC2.
- If PMI is present, route likely UC2 and confirm with borrower.

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
- If W2 path and PMI is present or borrower mentions PMI removal: UC2.
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
  - mark OFAC B13 as pending/not implemented if no OFAC service exists
- `S1_IDENTITY`
  - request/collect ID if available
  - evaluate B14 only when ID data exists
- `S2_DOCS`
  - request UC1/UC2 docs
  - evaluate B5 and B7
- `S3_INCOME`
  - parse paystubs/W-2s
  - ask employment tenure and only-income-source
  - evaluate B4, B6, B8, B9, U1.1, U1.2, U1.3
- `S4_CREDIT`
  - ask borrower-reported FICO range
  - evaluate B1, B2, B3
- `S5_PROPERTY`
  - use single property value
  - calculate LTV
  - evaluate B10 and B12
  - mark B11 not evaluated due single source
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

- 2 most recent paystubs
- 2 W-2s
- government ID
- property tax bill
- homeowners insurance declaration

Questions in order:

1. Confirm received rate, balance, address, and statement date.
2. Request paystubs and W-2s.
3. Ask employment tenure.
4. Ask if this is the only source of income.
5. Ask FICO range.
6. Ask property type.
7. Request tax bill and insurance declaration.

Calculations:

- W2 GMI
- paystub annualized income
- W2/paystub diff
- variable income percentage
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

UC2 calculations:

- UC1 W2/PITIA/DTI/savings calculations
- original LTV
- equity gained
- PMI savings
- total monthly savings = rate savings + PMI savings
- break-even months with PMI savings
- UC2 LTV threshold check at 75%

UC2 RAG targets through `guide_tool`:

- FNMA B7-1 and FHLMC Ch.4701 for MI/PMI requirements
- FNMA B4-1.3 and FHLMC ACE waiver rules for valuation/appraisal waiver
- all UC1 targets for W2 income, LTV/refi, DTI, and credit

## Minimal Calculators

Implement deterministic calculators under `src/turborefi/services/calculations/`.

### `income.py`

- `gross_monthly_income(amount, pay_frequency)`
- `paystub_annualized(paystub_gross_current, pay_frequency)`
- `w2_paystub_diff_pct(paystub_annualized, w2_box1)`
- `employment_tenure_check(tenure_months)`

### `variable_income.py`

- `variable_income_pct(ot, bonus, commission, base)`
- `variable_income_history_check(variable_income_present, tenure_months)`

### `ltv.py`

- `ltv(current_balance, estimated_property_value)`
- `ltv_threshold_for_use_case("uc1" | "uc2")`
- `b11_status_for_single_source()`

Rules:

- UC1 threshold: 80%
- UC2 threshold: 75%
- B11 not evaluated
- U2.1 not applicable because there is no LTV range

### `mortgage.py`

- `monthly_pi(principal, annual_rate_percent, term_months=360)`
- `tax_monthly(tax_bill_annual)`
- `insurance_monthly(insurance_annual)`
- `pitia_total(pi, tax, insurance, escrow=None, hoa=0, pmi=0)`

### `debts.py`

- `front_dti(pitia_total, gmi)`
- `back_dti(pitia_total, monthly_debts, gmi)`
- student loan placeholder if debt data exists later

### `savings.py`

- `rate_savings(old_pi, new_pi)`
- `closing_cost_estimate(current_balance, pct=0.015)`
- `break_even_months(closing_costs, monthly_savings)`

### `pmi.py`

- `pmi_savings(pmi_monthly, eliminated=True)`
- `original_ltv(purchase_price, down_payment)`
- `equity_gained(purchase_price, current_balance)`
- `total_savings_with_pmi(rate_savings, pmi_savings)`

## Minimal LARS

Implement only factors relevant to UC1/UC2 now.

Base factors:

- B1 FICO below 620
- B2 FICO 620-679
- B3 FICO unknown
- B4 factual uncertainty
- B5 missing required doc
- B6 W2/paystub mismatch >10%
- B7 OCR confidence <80%
- B8 employment <2 years
- B9 employment gap
- B10 LTV > threshold
- B11 not evaluated single-source valuation
- B12 condo/HOA
- B13 OFAC not screened, if processing_started and no OFAC integration
- B14 identity mismatch, if ID data exists
- B15 DTI >43%

UC1:

- U1.1 variable income >25%
- U1.2 variable income <2-year history
- U1.3 multiple employers

UC2:

- all UC1 factors
- U2.1 not applicable single-source valuation
- U2.2 PMI type unclear
- U2.3 second lien exists
- U2.4 purchase price unknown

Rules:

- start at 100
- deductions only
- floor at 0
- append immutable events
- recalculate after every new data point
- if score <70, set `referral_triggered = true` but keep collecting

## Conversation Flow

Add deterministic conversation flow rules:

- `rules/conversation_requirements.py`
- `services/conversation_flows.py`

Opening message:

- confirm rate, balance, address
- include soft statement-recency ask
- show property value estimate and LTV if available
- mention preliminary-screening limitations

UC1 flow:

- follow UC1 question order from Expert Review Guide
- do not ask for rate, balance, or address from scratch

UC2 flow:

- confirm PMI when visible
- ask PMI type only when needed
- ask purchase price/down payment
- ask second lien/HELOC
- continue UC1 flow

Referral flow:

- keep collecting missing useful data
- final handoff message tells borrower collected data is passed to LO
- do not make borrower repeat already-collected facts

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
- U2.2 PMI unclear: confirm borrower-paid vs lender-paid PMI
- U2.3 second lien: review CLTV/subordinate financing
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
- documents received/missing
- intake pending
- received mortgage/property data summary
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
- add received-input adapter tests
- add LOA-safe redaction tests

### Phase 1: UC1/UC2 Schemas and JSON Start

- add received/uploaded/calculated/session models
- add `/session/from-json`
- route UC1 vs UC2
- mark unsupported cases as deferred

### Phase 2: Calculators

- implement W2 income, variable income, LTV, PITIA, DTI, savings, PMI
- test formula-sheet examples
- test UC1/UC2 expected values

### Phase 3: LARS and Handoff

- implement base + UC1 + UC2 LARS factors
- record B11 and U2.1 as not applicable/not evaluated for single-source value
- generate handoff package
- add handoff action mappings

### Phase 4: Conversation Flow

- implement deterministic UC1/UC2 question order
- opening message confirms received data
- add statement-recency soft ask
- continue collecting after referral

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
- `tests/test_lars_uc1_uc2.py`
- `tests/test_conversation_flows_uc1_uc2.py`
- `tests/test_handoff_actions_uc1_uc2.py`
- `tests/test_rag_validation_uc1_uc2.py`

Integration tests:

- `/session/from-json` creates session from sample JSON
- UC1 happy path builds packet
- UC2 PMI path builds packet
- UC2 over-75 LTV triggers B10
- missing W-2 triggers B5 and handoff
- uncertainty triggers B4 and handoff
- LOA-safe session excludes name/profession/protected fields
- no verifier/compliance endpoints are required

## Definition Of Done

- App starts from received JSON.
- UC1/UC2 route correctly.
- LOA context is privacy-safe.
- One property value is used; no API-spread requirement.
- Deterministic calculators produce expected values.
- LARS works for UC1/UC2.
- Handoff package prevents re-asking collected data.
- `guide_tool` retrieves and validates UC1/UC2 guide targets.
- Frontend can show status/result/handoff for UC1/UC2.
