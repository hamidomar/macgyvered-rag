# TurboRefi New Docs Migration Plan

## Executive Decision

The current application can be modified to implement the system described in
`new_docs/TurboRefi_Engineering_DataSpec Share.docx` and
`new_docs/TurboRefi_Formula_CheatSheet.docx`, but it needs a substantial
domain-layer refactor.

This is not a full rewrite. The existing app already has the right outer shape:

- FastAPI product API in `src/turborefi/api.py`
- session orchestration in `src/turborefi/services/session_service.py`
- persistent JSON session state under `runtime/sessions/`
- extraction service in `src/turborefi/extraction/` for supporting documents
- deterministic packet builder and verifier services
- Agno LOA/verifier agents
- guideline retrieval adapter over `retrival/`
- frontend session, upload, chat, and result plumbing

The parts that must change are the mortgage-domain core:

- data schemas only support UC1-UC3 and omit most required fields
- the first input is currently modeled as an extracted mortgage statement, but
  the new integration will provide normalized received JSON up front
- calculator coverage is too narrow and several formulas do not match the new docs
- LARS scoring and referral event logging do not exist
- property value API range handling does not exist
- state machine S0-S7 does not exist
- UC4, UC5, and UC6 are not implemented
- UC2 uses the old PMI/LTV logic, not the new 75% screening threshold
- verification currently rebuilds the same deterministic packet instead of producing an independent LARS/compliance audit

Recommended approach: keep the app shell and replace the domain layer in phases.
Do not make mortgage-statement OCR part of the critical path. The primary entry
point should accept the provided received JSON directly.

## Source Documents Used

Specification files:

- `new_docs/TurboRefi_Engineering_DataSpec Share.docx`
- `new_docs/TurboRefi_Formula_CheatSheet.docx`

Sample received-data payloads:

- `example_json_inputs/VA Good Rate.json`
- `example_json_inputs/High Balance ARM.json`
- `example_json_inputs/Low Equity.json`
- `example_json_inputs/High Rate FHA.json`
- `example_json_inputs/Near Payoff.json`

The engineering spec references additional documents that are not present in this
repository, including Engineer's Technical Spec v1, Expert Review Guide v2,
Compliance Agent Architecture, UW Training Guidelines, a Use Case document, and
a Field-UseCase Mapping spreadsheet. This plan uses the available two docs plus
the sample JSON inputs as the source of truth and leaves explicit extension
points for the missing specs.

## Important Doc Issues To Confirm

The two new docs are mostly consistent, but a few details need confirmation
before final test locks:

- Engineering Spec Test Case 1 input says API values are `$435K, $428K, $441K`,
  but expected LTV text uses `$445K` and `$425K`. The calculator should follow
  the formula and inputs, while the test fixture should be corrected after
  business confirmation.
- Engineering Spec Test Case 1 labels PITIA as `$2,188.90`, then adds
  `$1,738.90 + $450 + $150 + $0 = $2,338.90`. The arithmetic result is
  `$2,338.90`.
- Engineering Spec self-employed trend text uses `yr1` and `yr2` inconsistently.
  Implementation should define `most_recent_year` and `prior_year` explicitly.
  If most recent adjusted income is below prior year, treat income as declining
  and use the lower/most recent year per the cheat sheet.

## Sample JSON Input Contract

The `example_json_inputs/` files show that TurboRefi will start with a received
JSON payload, not a mortgage statement file. This changes the ingestion plan.

Observed top-level shape:

```text
{
  "core": {...},
  "profile": {...},
  "statement": {...},
  "raw": {...},
  "formDecisions": {...},
  "propertyLookup": {...}
}
```

Important fields observed in `core`:

- `balance`
- `rate`
- `monthlyPayment`
- `paymentBreakdown.principal`
- `paymentBreakdown.interest`
- `paymentBreakdown.escrow`
- `paymentBreakdown.pmi`
- `loanNumber`
- `propertyAddress`
- `servicer`
- `loanType`
- `rateType`
- `originationDate`
- `maturityDate`
- `loanTermYears`
- `originalLoanAmount`
- `armResetDate`
- `propertyValue`
- `propertyData.estimatedValue`
- `propertyData.purchasePrice`
- `propertyData.purchaseDate`
- `propertyData.propertyType`
- `propertyData.county`

Important fields observed in `propertyLookup`:

- `found`
- `estimatedValue`
- `purchasePrice`
- `purchaseDate`
- `propertyType`
- `propertyTaxAnnual`
- address components
- `source`
- `lookupTimeMs`

Implementation consequences:

- Add a received-input adapter that maps this exact payload into internal
  `MortgageStatementReceived` and `PropertyValuationReceived` models.
- Treat `raw` and `formDecisions.reasoning` as audit/support data, not as the
  canonical calculator source.
- Use `core.balance` as current unpaid principal balance.
- Use `core.rate` as current rate.
- Use `core.paymentBreakdown.escrow` as current escrow when present.
- Use `core.paymentBreakdown.pmi` and `profile.pmiStatus` to pre-route possible
  UC2 PMI removal cases.
- Use `core.loanType` to pre-route VA IRRRL when `va`; for `fha`, route using
  the normal refinance use-case rules unless a separate FHA use case is later
  supplied.
- Preserve `rateType`, `armResetDate`, origination date, maturity date, and
  original loan amount. These are present in samples even though the docs do not
  define full ARM or near-payoff rules.
- Do not blindly trust `monthlyPayment` as total PITIA. In several samples,
  `monthlyPayment` appears to be P&I while escrow/PMI are separately listed.
  Current PITIA should be computed from components when components are present.
- The new docs mention 2-3 property-value APIs, but the samples usually provide
  one `propertyLookup.estimatedValue` or no value. The implementation should
  support one or many estimates. B11 API-spread evaluation should only run when
  enough independent estimates are available; otherwise log the spread check as
  unavailable/pending rather than failing the borrower.

Primary ingestion endpoint should be JSON-first:

- `POST /session/from-json` for these received payloads
- optional legacy upload/OCR endpoints can remain, but should not be required
  for the new workflow

## Current Codebase Structure

```text
src/turborefi/
  api.py
    FastAPI app factory. Exposes ingest, session, status, result, verify, and
    session-list endpoints. Currently knows only mortgage_statement, paystub,
    w2, and schedule_c upload types.

  schemas.py
    Central Pydantic models. Currently has MortgageStatementData, PaystubData,
    W2Data, ScheduleCData, BorrowerFacts, DocumentSet, SessionState,
    LoanRecommendationPacket, VerificationReport, and related trace models.
    UseCaseType currently supports only uc1_rate_term_refi, uc2_pmi_removal,
    and uc3_se_rate_term.

  workflow.py
    Fixture runner for local regression and AgentOS runner workflows.

  prompts.py
    LOA, verifier, and runner agent instructions.

  config.py
    Settings and runtime paths.

  extraction/
    service.py
      OpenAI/PDF extraction service and document-type inference. Useful for
      uploaded supporting documents, but the new primary mortgage/received-data
      path should bypass mortgage statement extraction and accept JSON directly.
    prompts.py
      JSON extraction prompts for mortgage statement, paystub, W-2, Schedule C.
    normalizers.py
      Basic string/list/dict payload cleanup.

  services/
    session_service.py
      Main product orchestrator. Creates sessions from mortgage data, accepts
      supporting docs, resolves intake messages, builds packets, verifies, saves
      session state, and syncs Agno session state.
    session_state.py
      Infers income type/use case and refreshes current phase and missing docs.
    intake_service.py
      Extracts simple borrower facts from free-text messages and builds follow-up prompts.
    intake_resolver.py
      Agent/deterministic wrapper around intake updates.
    packet_builder.py
      Deterministic recommendation packet construction. Currently calculates
      income, LTV, PMI savings, basic eligibility, citations, and reasoning.
    verification_service.py
      Rebuilds the deterministic packet and compares fields.
    compliance.py
      Basic compliance score from verifier field matches.
    retrieval_service.py
      Adapter around `retrival/scripts/guide_tool.py`.
    retrieval_policy.py
      Retrieval focuses and branch hints for UC1-UC3 style guideline lookup.
    guideline_research.py
      Deterministic guide traversal and citation collection.
    guide_traversal.py
      Hierarchy traversal/evidence validation.
    audit_log.py
      Writes JSON traces.

  rules/
    document_requirements.py
      Required document counts by income type.
    guideline_map.py
      Expected guideline sections and current max LTV thresholds.

  tools/
    calculators.py
      Current calculator functions and Agno tool wrappers. Too narrow for the
      new specs.
    document_tools.py
      Required-document helper tools.
    guideline_tools.py
      Agno wrappers for guideline retrieval.
    case_tools.py
      Fixture case loading and runner tools.

  agents/
    loan_officer.py
      Builds Agno LOA agent.
    verifier.py
      Builds Agno verifier agent.
    common.py
      Agno model/storage compatibility layer.

frontend/src/
  api/turborefi.ts
    Frontend API client.
  types/turborefi.ts
    Frontend TurboRefi response and document types.
  hooks/useTurboRefiSession.ts
    Upload/message/session orchestration.
  store.ts
    Zustand app state.
  components/chat/*
    Chat, upload, messages, and tool call drawer UI.

tests/
  test_calculators.py
  test_packet_builder.py
  test_session_service.py
  test_verification_service.py
  test_extraction_service.py
  test_api.py
  test_retrieval_service.py
  test_uc1_workflow.py
```

## New System Requirements Summary

### Data Taxonomy

Every field must be categorized as exactly one of:

- `RECEIVED`: pre-loaded before conversation from mortgage statement and
  property value APIs. In this repo's new integration, this arrives as the
  `example_json_inputs/` JSON shape rather than as a mortgage statement file.
- `UPLOADED`: extracted from borrower-uploaded documents or captured from
  borrower answers.
- `CALCULATED`: deterministic outputs from tools only. The LLM must never
  perform these calculations.

Implementation impact: schemas need source/category metadata, calculator outputs
need traceable inputs, and packet/handoff outputs need to preserve provenance.

### Use Cases

The target app must support six use cases:

- UC1: W2 Rate-Term Refinance
- UC2: W2 PMI Removal Refi
- UC3: Self-Employed Refi
- UC4: Gig Worker Refi
- UC5: VA IRRRL
- UC6: W2 + Rental Income Refi

Current app supports only UC1, UC2, and UC3 at a simplified level.

### Calculators

Every formula in the docs must be implemented as deterministic Python functions
with tests:

- GMI from annual, weekly, biweekly, semimonthly, monthly, and hourly income
- paystub annualization
- W2/paystub consistency
- variable income percent, two-year average, decline exclusion
- Schedule C adjusted income and self-employed GMI
- gig worker 1099/Schedule C match, expense ratio, platform volatility
- LTV low/high range and API spread
- standard amortization
- old/new P&I
- PITIA
- front-end and back-end DTI
- student loan debt treatment by program
- PMI savings and break-even
- UC2 original LTV/equity checks
- UC5 VA IRRRL net tangible benefit, funding fee, seasoning
- UC6 FNMA and FHLMC rental income methods, including sign handling
- LARS factor evaluation

### LARS Referral System

The app must start at score 100, deduct factor weights, log events, keep
collecting data after RED, and produce auto/human referral decisions.

The docs define baseline factors B1-B15 and use-case factors U1.1-U6.7.

Current app has no LARS model, no factor event schema, and no handoff package.

### State Machine

The engineering spec references S0-S7 deterministic conversation states from a
missing Engineer's Technical Spec v1. Because that document is unavailable, this
implementation should introduce an internal state machine aligned to the data
spec:

- S0 received data loaded
- S1 pre-conversation property/API checks complete
- S2 use case identified
- S3 intake questions pending
- S4 required document collection pending
- S5 deterministic calculation ready
- S6 recommendation/handoff ready
- S7 verified/audited

The names can change after the missing spec is supplied, but the state machine
should be explicit and testable.

## Keep, Refactor, Replace

### Keep

- FastAPI app factory and endpoint pattern in `src/turborefi/api.py`
- session JSON persistence pattern under `runtime/sessions/`
- Agno agent construction and storage compatibility in `src/turborefi/agents/`
- guideline retrieval adapter over `retrival/`
- tool-call trace shape for frontend display
- frontend session/chat skeleton
- fixture runner concept

### Refactor

- `src/turborefi/schemas.py` should be split into focused schema modules or
  expanded carefully with compatibility shims.
- `src/turborefi/tools/calculators.py` should become a thin Agno wrapper over a
  dedicated `services/calculations/` package.
- `src/turborefi/services/packet_builder.py` should become an assembler that
  consumes calculator and LARS results, not a place where formulas live.
- `src/turborefi/services/session_state.py` should stop inferring only UC1-UC3
  and should use a real use-case router.
- `src/turborefi/rules/document_requirements.py` should become use-case-aware,
  not only income-type-aware.
- `src/turborefi/services/verification_service.py` should independently
  recalculate required outputs and compare LARS events, formulas, and citations.
- frontend types must support the expanded document list and LARS/referral data.

### Replace

- old LTV thresholds in `src/turborefi/rules/guideline_map.py`
  - current: UC1/UC3 max 97, UC2 max 80
  - new screening thresholds: UC2 75, UC1/UC3/UC4/UC6 80, UC5 no LTV check
- current self-employed income calculation that averages net plus combined
  depreciation without trend/loss logic
- current monthly savings proxy based on rate delta ratio
- current verifier that simply rebuilds the same packet and compares a few fields

## Target Backend Structure

This structure keeps the app recognizable while isolating the new domain rules.

```text
src/turborefi/
  schemas/
    __init__.py
    enums.py
    received.py
    uploaded.py
    calculated.py
    documents.py
    borrower.py
    session.py
    packet.py
    lars.py
    handoff.py
    verification.py

  services/
    session_service.py
    state_machine.py
    use_case_router.py
    received_input.py
    property_valuation.py
    intake_service.py
    packet_builder.py
    verification_service.py
    compliance.py
    audit_log.py
    retrieval_service.py
    retrieval_policy.py
    guideline_research.py
    guide_traversal.py

    calculations/
      __init__.py
      income.py
      variable_income.py
      self_employed.py
      gig.py
      ltv.py
      mortgage.py
      debts.py
      rental.py
      va.py
      savings.py

  rules/
    document_requirements.py
    lars_factors.py
    use_case_requirements.py
    guideline_map.py

  extraction/
    service.py
    prompts.py
    normalizers.py

  tools/
    calculators.py
    document_tools.py
    guideline_tools.py
    lars_tools.py
    valuation_tools.py
    case_tools.py

  agents/
    loan_officer.py
    verifier.py
    common.py
```

The split from `schemas.py` to `schemas/` is recommended but can be staged. If
we want a smaller first PR, keep `schemas.py` and add the new classes there, then
split after tests are stable.

## Detailed File Plan

### `src/turborefi/schemas/enums.py`

Purpose: centralize shared enum-like literals.

Definitions:

- `DataCategory = Literal["received", "uploaded", "calculated"]`
- `GSEType = Literal["fnma", "fhlmc", "fha", "va", "unknown"]`
- `UseCaseType = Literal[
  "uc1_w2_rate_term",
  "uc2_w2_pmi_removal",
  "uc3_self_employed",
  "uc4_gig_worker",
  "uc5_va_irrrl",
  "uc6_w2_rental",
]`
- `IncomeType = Literal["unknown", "w2", "self_employed", "gig_1099", "rental", "va_irrrl"]`
- `PayFrequency = Literal["weekly", "biweekly", "semimonthly", "monthly", "annual", "hourly"]`
- `FicoRange = Literal["below_620", "620_679", "680_719", "720_759", "760_plus", "unknown"]`
- `PropertyType = Literal["sfr", "townhome", "condo"]`
- `PmiType = Literal["borrower_paid", "lender_paid", "unknown"]`
- `ReferralDecision = Literal["AUTO", "REFER"]`

Compatibility note: preserve aliases from current use cases during migration or
provide a migration function for existing saved sessions.

### `src/turborefi/schemas/received.py`

Purpose: model all pre-loaded data from mortgage statement and property APIs.

Models:

- `ReceivedInputPayload`
  - typed representation of the upstream JSON with `core`, `profile`,
    `statement`, `raw`, `formDecisions`, and `propertyLookup`
  - this is the external contract for `example_json_inputs/`
  - keep permissive enough to tolerate missing/null fields
- `MortgageStatementReceived`
  - `borrower_name`
  - `current_rate`
  - `current_balance`
  - `property_address`
  - `servicer_name`
  - `loan_number`
  - `escrow_monthly`
  - `pmi_monthly`
  - `loan_type_detected`
  - `rate_type`
  - `origination_date`
  - `maturity_date`
  - `loan_term_years`
  - `original_loan_amount`
  - `arm_reset_date`
  - `pi_monthly` for old loan if statement has it
  - `current_payment_reported`
  - `payment_breakdown`
  - `ocr_confidence`
- `PropertyValuationReceived`
  - `api_value_1`
  - `api_value_2`
  - `api_value_3`
  - `estimated_value`
  - `purchase_price`
  - `purchase_date`
  - `property_type`
  - `property_tax_annual`
  - `source_1`
  - `source_2`
  - `source_3`
  - `lookup_source`
  - `lookup_time_ms`
  - `value_range_low`
  - `value_range_high`
  - `api_spread_pct`
  - `ltv_high`
  - `ltv_low`
  - `spread_check_status`
  - `address_components`

Notes:

- Property API fields are "received" in the docs, but `value_range_*`,
  `api_spread_pct`, and `ltv_*` are calculated from API values. Store them in
  `CalculatedOutputs` as the canonical calculated values and optionally mirror
  them in the received summary for UI convenience.
- The sample JSON often provides only one `propertyLookup.estimatedValue`.
  `api_spread_pct` and B11 require multiple independent values; when only one
  value is present, record the valuation as usable for LTV but mark spread as
  unavailable.
- UC5 must not call property valuation APIs.

### `src/turborefi/schemas/uploaded.py`

Purpose: model uploaded document extractions and borrower answers.

Models:

- `PaystubUploaded`
  - current gross, YTD gross, period end, pay frequency, employer, base, OT,
    bonus, commission, OCR confidence
- `W2Uploaded`
  - tax year, Box 1 wages, employer, EIN, OCR confidence
- `ScheduleCUploaded`
  - tax year, gross income, net profit, depreciation, depletion, amortization,
    business use of home, expenses, entity type, OCR confidence
- `ScheduleEUploaded`
  - tax year, gross rents, expenses, depreciation, net rental income, OCR confidence
- `Form1099Uploaded`
  - platform/payer name, gross earnings, form type, tax year, OCR confidence
- `LeaseUploaded`
  - monthly rent, term months, tenant name, start/end dates, tenant relationship, OCR confidence
- `TaxBillUploaded`
  - annual tax amount, property address, OCR confidence
- `InsuranceUploaded`
  - annual premium, property address, OCR confidence
- `RentalMortgageStatementUploaded`
  - rental PITIA and address fields
- `VAUploaded`
  - COE status, payment count, first payment date, disability rating, loan purpose
- `BorrowerAnswersUploaded`
  - FICO range, tenure months, single income source, property type, rental count,
    occupied flag, tenant relationship, rental PITIA, business count, platform
    count, platform months, uncertainty flags

### `src/turborefi/schemas/calculated.py`

Purpose: structured outputs from deterministic calculators.

Models:

- `IncomeCalculation`
- `VariableIncomeCalculation`
- `SelfEmployedCalculation`
- `GigCalculation`
- `LtvCalculation`
- `MortgagePaymentCalculation`
- `PitiaCalculation`
- `DtiCalculation`
- `SavingsCalculation`
- `RentalIncomeCalculation`
- `VaIrrrlCalculation`
- `CalculatedOutputs`

Each model should include:

- calculator name
- input values
- output values
- formula identifier
- guideline references when known
- warnings or edge-case flags

### `src/turborefi/schemas/documents.py`

Purpose: replace the current `DocumentSet` with a complete document container.

Fields:

- `mortgage_statement`
- `paystubs`
- `w2s`
- `schedule_c`
- `schedule_e`
- `forms_1099`
- `lease_agreements`
- `tax_bills`
- `insurance_declarations`
- `rental_mortgage_statements`
- `va_documents`
- `identity_documents`
- `additional_documents`

Methods:

- `category_count(category)`
- `received_categories()`
- `latest_paystub()`
- `w2_by_year()`
- `schedule_c_by_year()`
- `schedule_e_by_year()`

### `src/turborefi/schemas/lars.py`

Purpose: model LARS factors, events, and final score.

Models:

- `LarsFactorDefinition`
  - code
  - label
  - deduction
  - applies_to
  - trigger_summary
  - severity
- `LarsEvent`
  - code
  - label
  - deduction
  - triggered
  - inputs
  - explanation
  - data_category
  - source_fields
  - created_at
- `LarsScore`
  - starting_score = 100
  - events
  - final_score
  - decision: `AUTO` if final_score >= 70 else `REFER`
  - referral_reasons

### `src/turborefi/schemas/handoff.py`

Purpose: human loan-officer referral package when LARS < 70 or hard-fail factors
trigger.

Model:

- `HumanHandoffPackage`
  - borrower_id
  - session_id
  - use_case
  - final_lars_score
  - lars_events
  - referral_reasons
  - collected_data
  - missing_data
  - human_action_items
  - generated_at

### `src/turborefi/schemas/packet.py`

Purpose: update `LoanRecommendationPacket` to the new output contract.

Fields:

- borrower/session identifiers
- use case
- received data summary
- uploaded data summary
- calculated outputs
- LARS score and events
- referral decision
- handoff package when applicable
- FNMA and FHLMC pathway results where applicable
- VA pathway result for UC5
- recommended pathway
- monthly savings and break-even
- documentation status
- guideline citations
- audit/tool-call records
- borrower-facing summary

Important: for UC6, include both FNMA and FHLMC rental calculations even when
one is better than the other.

### `src/turborefi/schemas/session.py`

Purpose: update `SessionState`.

Fields:

- `state_machine_state`: S0-S7
- `received`
- `uploaded`
- `calculated`
- `documents`
- `borrower_answers`
- `lars_score`
- `handoff_package`
- `current_phase` for backward-compatible frontend display
- `loa_output`
- `verifier_output`
- `retrieval_events`
- `tool_calls`
- `conversation`

Migration:

- existing saved session JSON may use old class names. Implement a
  `model_validator(mode="before")` or explicit migration helper that maps:
  - `current_rate_percent` to `current_rate`
  - `loan_balance` to `current_balance`
  - `monthly_pmi` to `pmi_monthly`
  - `original_property_value` to property valuation fallback

### `src/turborefi/services/calculations/income.py`

Purpose: W2/salaried GMI and consistency checks.

Functions:

- `gross_monthly_income(amount, pay_frequency, guaranteed_hours=None)`
- `paystub_annualized(paystub_gross_current, pay_frequency)`
- `w2_paystub_diff_pct(paystub_annualized, w2_box1_most_recent)`
- `select_w2_income(w2_most_recent, w2_prior)` with declining-income logic
- `employment_tenure_check(tenure_months)`

Tests:

- cheat-sheet pay frequency examples
- W2/paystub diff 10% threshold
- declining income uses lower year
- zero/negative input validation

### `src/turborefi/services/calculations/variable_income.py`

Purpose: OT/bonus/commission rules.

Functions:

- `variable_income_pct(ot, bonus, commission, base)`
- `variable_income_two_year_average(yr1_variable, yr2_variable)`
- `variable_income_decline(yr1_variable, yr2_variable)`
- `should_exclude_variable_income(decline_pct, current_year_variable)`

Tests:

- >25% triggers U1.1
- tenure <24 months triggers U1.2 when variable income exists
- >20% decline or current year zero excludes variable income

### `src/turborefi/services/calculations/self_employed.py`

Purpose: Schedule C adjusted income and UC3 GMI.

Functions:

- `adjust_schedule_c_income(net, depreciation, depletion, amortization, home_office)`
- `self_employed_income_trend(most_recent_adjusted, prior_adjusted)`
- `self_employed_gmi(most_recent_adjusted, prior_adjusted)`
- `has_schedule_c_loss(most_recent_net, prior_net)`
- `pl_deviation_pct(pl_ytd_net, tax_average_net)`
- `largest_deduction_pct(deduction_amount, gross_income)`

Tests:

- Engineering Spec Test Case 3
- declining income triggers U3.1 and uses lower/current year
- net loss triggers U3.2
- P&L deviation >25% triggers U3.7
- large one-time deduction >20% triggers U3.5

### `src/turborefi/services/calculations/gig.py`

Purpose: UC4 1099/Schedule C checks and gig GMI.

Functions:

- `gross_1099_matches_schedc(gross_1099, schedc_gross, tolerance=0)`
- `expense_ratio(schedc_expenses, gross_1099)`
- `seasonal_volatility(monthly_earnings)`
- `platform_history_status(months_active)`
- `gig_gmi(...)` delegating to self-employed formulas after validation

Tests:

- mismatch triggers U4.6
- expense ratio >50% triggers U4.2
- volatility >50% triggers U4.5
- <12 months triggers U4.3
- 12-23 months marks FNMA-only pathway

### `src/turborefi/services/calculations/ltv.py`

Purpose: property API ranges and LTV thresholds.

Functions:

- `api_value_range(api_values)`
- `api_spread_pct(api_values)`
- `ltv_range(current_balance, value_range_low, value_range_high)`
- `ltv_threshold_for_use_case(use_case)`
- `ltv_straddles_threshold(ltv_low, ltv_high, threshold)`

Rules:

- UC2 threshold: 75% for LARS B10/U2.1 screening
- UC1/UC3/UC4/UC6 threshold: 80%
- UC5: no LTV calculation and no API query
- API spread >15% triggers B11

Tests:

- Engineering Spec Test Cases 1, 2, and 3 after resolving doc inconsistencies
- B10 threshold by use case
- B11 spread threshold
- U2.1 straddles 75%

### `src/turborefi/services/calculations/mortgage.py`

Purpose: amortization and PITIA.

Functions:

- `monthly_pi(principal, annual_rate_percent, term_months=360)`
- `tax_monthly(tax_bill_annual)`
- `insurance_monthly(insurance_annual)`
- `pmi_for_new_loan(ltv, fico_range, existing_pmi=None)`
- `pitia_total(pi, tax, insurance, hoa=0, pmi=0)`

Tests:

- `$290,000 @ 6.0% / 30yr = about $1,738.87`
- zero-rate edge case returns principal / term
- PITIA sums exactly

### `src/turborefi/services/calculations/debts.py`

Purpose: DTI and monthly debt treatment.

Functions:

- `student_loan_payment(program, balance, reported_payment=None, deferred=False)`
- `monthly_debts_total(debts, program)`
- `front_dti(pitia_total, gmi)`
- `back_dti(pitia_total, monthly_debts, gmi)`
- `apply_rental_to_dti(gmi, monthly_debts, net_rental)`

Rules:

- FNMA deferred student loan: 1% of balance or fully amortized payment, whichever is greater
- FHLMC deferred student loan: 0.5% of balance
- FHA: 1%, IBR not accepted
- VA: may exclude if deferred 12+ months past close; otherwise 5% / 12
- back DTI >43% triggers B15

### `src/turborefi/services/calculations/rental.py`

Purpose: UC6 dual GSE rental income calculations.

Functions:

- `fnma_net_rental_income(lease_monthly_rent, rental_pitia)`
- `fhlmc_net_rental_income(schede_net, schede_depreciation)`
- `lease_schede_diff_pct(lease_monthly_rent, schede_gross)`
- `rental_income_or_liability(net_rental)`
- `combined_gmi_with_rental(w2_gmi, net_rental)`

Rules:

- FNMA: `(lease_monthly_rent * 0.75) - rental_pitia`
- FHLMC: `(schede_net + schede_depreciation) / 12`
- positive result adds to GMI
- negative result adds absolute value to monthly debts
- negative rental triggers U6.2
- lease/Schedule E mismatch >10% triggers U6.6

Tests:

- Engineering Spec Test Case 5 exactly
- sign flip behavior
- FNMA and FHLMC can have different signs and both must be displayed

### `src/turborefi/services/calculations/va.py`

Purpose: UC5 VA IRRRL calculations.

Functions:

- `rate_reduction_bps(current_rate, new_rate)`
- `va_funding_fee(current_balance, disability_rating)`
- `va_irrrl_monthly_savings(current_balance, current_rate, new_rate)`
- `seasoning_pass(payment_count, days_since_first_payment)`
- `net_tangible_benefit_pass(reduction_bps)`

Rules:

- reduction <50 bps triggers U5.2 hard fail
- funding fee = current_balance * 0.005 unless disability rating >0
- seasoning requires at least 6 payments and at least 210 days
- no income docs, credit, or LTV for UC5; requesting those is U5.5 system bug

### `src/turborefi/services/calculations/savings.py`

Purpose: savings and break-even.

Functions:

- `rate_savings(old_pi, new_pi)`
- `pmi_savings(pmi_monthly, eliminated)`
- `total_monthly_savings(rate_savings, pmi_savings=0)`
- `closing_cost_estimate(current_balance, pct=0.015)`
- `break_even_months(closing_costs, monthly_savings)`

Rules:

- UC2 savings includes PMI elimination
- other UCs use rate savings unless another use-case-specific saving is defined
- handle zero/negative savings by returning `None` or an explicit not-applicable status

### `src/turborefi/rules/lars_factors.py`

Purpose: machine-readable factor catalog and trigger functions.

Content:

- `LARS_FACTORS` dictionary for B1-B15 and U1.1-U6.7
- `evaluate_base_factors(context)`
- `evaluate_uc1_factors(context)`
- `evaluate_uc2_factors(context)`
- `evaluate_uc3_factors(context)`
- `evaluate_uc4_factors(context)`
- `evaluate_uc5_factors(context)`
- `evaluate_uc6_factors(context)`
- `evaluate_lars(context)` returning `LarsScore`

Implementation notes:

- Keep factor definitions declarative.
- Trigger functions should be simple and directly tied to calculator outputs.
- Every LARS event should include input values for auditability.
- Missing-doc B5 is per missing required doc.
- B4 should be triggered by explicit uncertainty in borrower answers, not by
  parser failure alone.
- B7 should use OCR confidence when the extraction service provides it.

### `src/turborefi/rules/use_case_requirements.py`

Purpose: use-case-specific checklists from Section 4.

Content:

- required received fields
- required uploaded docs
- required borrower answers
- required calculated outputs
- applicable LARS factor codes
- use-case-specific thresholds

This should replace scattered logic in `document_requirements.py`,
`session_state.py`, and `packet_builder.py`.

### `src/turborefi/rules/document_requirements.py`

Purpose: update from income-type requirements to use-case-aware requirements.

Requirements from the new docs:

- UC1: mortgage statement, property APIs, 2 paystubs, 2 W-2s, tax bill,
  insurance declaration, ID
- UC2: UC1 docs plus PMI statement/PMI type, purchase price, down payment,
  second-lien answer
- UC3: mortgage statement, property APIs, 2 years tax returns/Schedule C, P&L,
  tax bill, insurance, ID
- UC4: mortgage statement, property APIs, 1099, tax returns/Schedule C, platform
  dashboard, tax bill, insurance, ID
- UC5: mortgage statement showing/confirming VA, COE/electronic pull, ID, verbal
  VA answers; no income docs, no credit, no property value APIs
- UC6: UC1 docs plus Schedule E, lease, rental mortgage statement, rental tax and
  insurance, rental verbal answers

Output:

- `received`
- `missing`
- `pending_pre_closing`
- `not_required`
- `system_forbidden` for UC5 no-income/no-credit/no-LTV checks

### `src/turborefi/services/received_input.py`

Purpose: map the upstream received JSON payload into internal TurboRefi models.

This replaces mortgage-statement OCR as the primary session-start path.

Functions:

- `parse_received_payload(payload: dict) -> ReceivedInputPayload`
- `normalize_received_payload(payload: ReceivedInputPayload) -> ReceivedData`
- `build_mortgage_statement_received(payload) -> MortgageStatementReceived`
- `build_property_valuation_received(payload) -> PropertyValuationReceived`
- `derive_current_pi(payload) -> float | None`
- `derive_current_pitia_components(payload) -> PitiaComponentInputs`
- `collect_received_warnings(payload) -> list[str]`

Mapping rules from samples:

- `core.balance` -> `current_balance`
- `core.rate` -> `current_rate`
- `core.loanNumber` -> `loan_number`
- `core.propertyAddress` -> `property_address`
- `core.servicer` -> `servicer_name`
- `core.loanType` -> `loan_type_detected`
- `core.rateType` -> `rate_type`
- `core.originationDate` -> `origination_date`
- `core.maturityDate` -> `maturity_date`
- `core.loanTermYears` -> `loan_term_years`
- `core.originalLoanAmount` -> `original_loan_amount`
- `core.armResetDate` and `raw.profile/extra.arm_reset_date` -> `arm_reset_date`
- `statement.borrowerName` -> `borrower_name`
- `core.paymentBreakdown.escrow` -> `escrow_monthly`
- `core.paymentBreakdown.pmi` -> `pmi_monthly`
- `core.paymentBreakdown.principal + interest` -> current P&I when both exist
- `core.monthlyPayment` -> reported payment; use as P&I only if component
  checks support it
- `core.propertyValue`, `core.propertyData.estimatedValue`, and
  `propertyLookup.estimatedValue` -> valuation estimates
- `core.propertyData.purchasePrice` or `propertyLookup.purchasePrice` ->
  purchase price
- `core.propertyData.propertyType` or `propertyLookup.propertyType` ->
  property type
- `propertyLookup.propertyTaxAnnual` -> annual property tax if available

Validation/warning rules:

- If `monthlyPayment` does not match component sums, preserve both the reported
  value and computed component total and add a warning.
- If escrow or PMI is separately listed, compute PITIA from components rather
  than treating `monthlyPayment` as total housing payment.
- If no property value exists, continue intake and request borrower value or
  allow a configured valuation provider to fill it, except for UC5.
- If loan type is `fha`, keep it as received data but route according to the
  current use-case router unless FHA-specific requirements are later supplied.

### `src/turborefi/services/property_valuation.py`

Purpose: encapsulate property API lookup and deterministic range calculations.

Interface:

```python
class PropertyValuationProvider(Protocol):
    def lookup(self, property_address: str) -> list[PropertyValueEstimate]: ...
```

Implementations:

- `PayloadPropertyValuationProvider` that reads embedded `propertyLookup` and
  `core.propertyData` values from the received JSON
- `StaticPropertyValuationProvider` for tests and fixtures
- `DisabledPropertyValuationProvider` for local/offline mode
- future real providers for Zillow, Redfin, ATTOM/HouseCanary

Rules:

- first use values already present in the received JSON
- only call external APIs if configured and the received payload lacks usable
  valuation data
- do not run for UC5 VA IRRRL
- compute and persist range/spread/LTV immediately
- evaluate B10 before conversation starts when a usable value exists
- evaluate B11 only when multiple independent API values exist; otherwise mark
  the spread check unavailable/pending

### `src/turborefi/services/use_case_router.py`

Purpose: deterministic use-case detection.

Inputs:

- loan type detected from mortgage statement
- pmi line item
- borrower income type answer
- borrower rental answers
- uploaded document types
- explicit borrower scenario answers

Routing:

- VA loan or borrower confirms VA IRRRL -> UC5
- W2 + PMI candidate -> UC2
- self-employed Schedule C -> UC3
- gig/platform/1099 -> UC4
- W2 + rental income/property -> UC6
- default W2 rate-term -> UC1

Output:

- `UseCaseRoutingResult`
  - use_case
  - confidence
  - reasons
  - questions_needed

### `src/turborefi/services/state_machine.py`

Purpose: explicit deterministic workflow transitions.

States:

- `S0_RECEIVED_LOADED`
- `S1_PRECHECK_COMPLETE`
- `S2_USE_CASE_IDENTIFIED`
- `S3_INTAKE_PENDING`
- `S4_DOC_COLLECTION_PENDING`
- `S5_CALCULATION_READY`
- `S6_RECOMMENDATION_READY`
- `S7_VERIFIED`

Functions:

- `next_state(session_state)`
- `missing_inputs_for_state(session_state)`
- `can_calculate(session_state)`
- `should_continue_collecting_after_referral(session_state)`

Frontend mapping:

- S0/S1 -> `extraction`
- S2/S3 -> `awaiting_intake`
- S4 -> `awaiting_docs`
- S5 -> `assessment`
- S6 -> `complete`
- S7 -> `verified`

### `src/turborefi/services/packet_builder.py`

Purpose after refactor: assemble outputs, not implement formulas.

Flow:

1. Validate required inputs for current use case.
2. Run all applicable calculators.
3. Evaluate LARS factors.
4. Retrieve required guideline citations.
5. Build pathway results:
   - FNMA/FHLMC for UC1, UC2, UC3, UC4, UC6
   - VA for UC5
   - both FNMA and FHLMC rental treatment for UC6
6. Build documentation status.
7. Build handoff package if LARS <70 or hard-fail conditions apply.
8. Return `PacketBuildResult`.

Do not:

- perform inline math in string summaries
- hide negative rental sign flips
- collapse FNMA/FHLMC rental results into one number
- silently skip unavailable required fields

### `src/turborefi/services/verification_service.py`

Purpose after refactor: independent deterministic audit.

Flow:

1. Take raw received/uploaded data and LOA packet.
2. Re-run every applicable calculator.
3. Re-run LARS factor evaluation.
4. Re-run document checklist.
5. Re-run guideline focus retrieval.
6. Compare:
   - calculated fields
   - LARS events and final score
   - referral decision
   - recommended pathway
   - document status
   - citations
7. Produce `VerificationReport` with mismatches and compliance score.

### `src/turborefi/services/compliance.py`

Purpose after refactor: score more than field equality.

Components:

- Calculation Accuracy
- Guideline Adherence
- Documentation Completeness
- LARS/Referral Accuracy
- Audit Trail Integrity

Later when missing Compliance Agent Architecture doc is available, extend this
with TCS scoring, fairness monitors, streaming regression, and CUSUM charts.

### `src/turborefi/extraction/prompts.py`

Update prompts to extract all required supporting-document fields.

Mortgage statement extraction is not needed for the new primary flow because the
received mortgage/valuation data arrives as JSON. Keep the mortgage statement
prompt only as optional legacy fallback.

- optional legacy mortgage statement:
  - current rate, current balance, property address, servicer, loan number,
    escrow, PMI, loan type, old PI if visible
- paystub:
  - gross current, YTD, period end, frequency, employer, base, OT, bonus,
    commission
- W-2:
  - Box 1, employer, EIN, tax year
- Schedule C:
  - gross, net, depreciation, depletion, amortization, business use of home,
    expenses, entity type
- Schedule E:
  - gross rents, expenses, depreciation, net
- 1099:
  - gross, platform/payer, form type, tax year
- lease:
  - rent, term, tenant, start/end, relationship indicator if visible
- tax bill:
  - annual tax
- insurance declaration:
  - annual premium
- VA/COE:
  - COE status, disability indicator if present

Add OCR confidence fields where possible. If the model cannot provide real OCR
confidence, use extraction confidence heuristics and keep B7 conservative.

### `src/turborefi/extraction/service.py`

Changes:

- expand `SECONDARY_DOCUMENT_TYPES`
- expand `SCHEMA_BY_DOC_TYPE`
- support JSON input mode directly through `received_input.py`, since the
  mortgage/received details arrive in JSON format
- add `extract_json_payload(doc_type, payload)` as a first-class path
- infer new document types by filename and PDF text markers
- return normalized uploaded schema models
- keep mortgage statement OCR as optional legacy support, not as a required
  production path

### `src/turborefi/api.py`

Changes:

- make `POST /session/from-json` the primary session creation path for the
  upstream received payload shape in `example_json_inputs/`
- accept the exact top-level JSON fields `core`, `profile`, `statement`, `raw`,
  `formDecisions`, and `propertyLookup`
- accept expanded document types:
  - mortgage_statement
  - paystub
  - w2
  - schedule_c
  - schedule_e
  - form_1099
  - lease
  - tax_bill
  - insurance
  - rental_mortgage_statement
  - va_coe
  - identity
- add JSON endpoints for pre-loaded received data:
  - `POST /session/from-json`
  - `POST /session/{session_id}/document-json`
- include in status/detail responses:
  - state machine state
  - use case
  - LARS score
  - referral decision
  - referral reasons
  - handoff package
  - calculated outputs summary
- keep existing endpoints for frontend compatibility.
- treat `/session` and `/ingest` mortgage-statement upload as legacy/optional
  entry points unless product later requires file uploads again

### `src/turborefi/services/session_service.py`

Changes:

- add `create_session_from_received_json(payload, session_name=None)`
- call `received_input.py` to normalize the upstream JSON into internal
  received-data models
- inject `PropertyValuationProvider`
- call use-case router and state machine after every input
- run pre-conversation LTV/API spread checks after received JSON normalization
  and embedded/configured property valuation
- continue collecting docs even after LARS RED
- support UC5 forbidden-doc logic
- route JSON payloads through the same session update path as uploads
- only build final packet when required data is complete enough for that UC
- expose LARS/tool traces to frontend messages

### `src/turborefi/services/intake_service.py`

Changes:

- parse FICO ranges
- parse tenure months/years
- parse single income source
- parse property type
- parse rental count, occupied, tenant relationship, ownership months
- parse PMI type, purchase price, down payment, second lien
- parse VA purpose, payment count, disability rating
- parse platform count/months and uncertainty phrases
- record B4 uncertainty events as data, not just text

Recommendation: keep regex parsing for deterministic tests, and let
`AgentIntakeResolver` fill structured fields when regex is not enough.

### `src/turborefi/rules/guideline_map.py`

Changes:

- update expected sections/focuses for UC1-UC6
- update LTV thresholds:
  - UC2: 75
  - UC1/UC3/UC4/UC6: 80
  - UC5: None
- add focus keys for:
  - W2 income
  - variable income
  - self-employed Schedule C
  - gig/1099
  - rental Schedule E/lease
  - VA IRRRL/NTB
  - DTI/debts
  - LTV/property value

### `src/turborefi/services/retrieval_policy.py`

Changes:

- define retrieval focuses per use case and calculation category
- UC5 should retrieve VA references only if available; current retrieval backend
  may only contain FNMA/FHLMC, so build this with graceful unavailable-source
  results
- UC6 should retrieve both FNMA B3-3.5 and FHLMC Chapter 5305 support
- UC4 should retrieve FNMA SEL-2025-01 if available; otherwise log missing
  source and cite fallback B3-3.2 only where appropriate

### `src/turborefi/tools/calculators.py`

Purpose after refactor: Agno tool wrappers only.

Expose tools:

- `calc_gmi_tool`
- `calc_w2_consistency_tool`
- `calc_variable_income_tool`
- `calc_self_employed_income_tool`
- `calc_gig_income_tool`
- `calc_ltv_range_tool`
- `calc_monthly_pi_tool`
- `calc_pitia_tool`
- `calc_dti_tool`
- `calc_rental_income_tool`
- `calc_va_irrrl_tool`
- `calc_savings_tool`

Each wrapper should call `services/calculations/*`.

### `src/turborefi/tools/lars_tools.py`

Purpose: allow agents to inspect LARS results without doing scoring themselves.

Tools:

- `evaluate_lars_tool`
- `list_lars_factors_tool`
- `build_handoff_package_tool`

### `src/turborefi/tools/document_tools.py`

Changes:

- accept `use_case`, not just `income_type`
- return required, missing, received, pending, and forbidden docs
- expose `get_use_case_checklist(use_case)`

### `src/turborefi/prompts.py`

Update LOA instructions:

- explicitly state RECEIVED/UPLOADED/CALCULATED taxonomy
- CALCULATED values must only come from tool outputs
- LARS score must only come from LARS tool/service
- after LARS RED, continue collecting required docs unless the state machine says stop
- UC5 must not request income, credit, or LTV/property valuation
- UC6 must present FNMA and FHLMC rental calculations separately
- all borrower-facing claims involving FICO must say borrower-reported range

Update verifier instructions:

- independently rerun calculators and LARS
- compare UC6 dual-path rental outputs
- flag forbidden UC5 data requests

### `frontend/src/types/turborefi.ts`

Changes:

- expand `TurboRefiDocumentType`
- add typed structures for:
  - LARS score
  - LARS event
  - handoff package
  - calculated outputs summary
  - use case
  - referral decision
  - verification report

### `frontend/src/api/turborefi.ts`

Changes:

- add JSON session/document endpoints
- allow all new document types
- fetch verification/handoff data if displayed separately

### `frontend/src/hooks/useTurboRefiSession.ts`

Changes:

- update document labels
- store LARS score/referral/handoff data
- support JSON input path if the app starts from structured mortgage statement JSON
- show new tool traces from calculator/LARS services

### `frontend/src/store.ts`

Changes:

- add to `turboRefiSession`:
  - `useCase`
  - `stateMachineState`
  - `larsScore`
  - `referralDecision`
  - `referralReasons`
  - `handoffPackage`
  - `calculatedOutputs`
  - `verificationReport`

## Implementation Phases

### Phase 0: Compatibility and Test Harness

Goal: create a safe baseline before major schema changes.

Tasks:

- run current tests and record baseline
- add `example_json_inputs/` as received-input fixtures
- add tests for the received JSON adapter before changing the session flow
- add doc-derived fixtures for the five engineering spec test cases
- add aliases/migration helpers for old use case names
- add `tests/fixtures/new_docs/` JSON fixtures based on the spec
- add known-doc-issue comments for Test Case 1 API/PITIA inconsistencies

Deliverables:

- current tests still pass
- every sample JSON file maps into internal received models
- new tests can be added as expected failures or skipped until calculators land

### Phase 1: Calculator Package

Goal: implement deterministic math independent of sessions, agents, and API.

Tasks:

- create `src/turborefi/services/calculations/`
- move/replace calculator logic
- keep old `tools/calculators.py` wrapper functions temporarily
- implement exhaustive unit tests for formulas

Deliverables:

- all formula cheat-sheet examples pass
- engineering spec test cases pass for calculation-only outputs

### Phase 2: New Schemas and Document Requirements

Goal: make the app capable of representing all required data.

Tasks:

- expand use cases and document models
- add `ReceivedInputPayload` and received JSON adapter models
- update extraction prompts and normalizers
- update `DocumentSet`
- update document requirements by use case
- add JSON input support

Deliverables:

- app can load the exact `example_json_inputs/` payloads
- app can store all UC1-UC6 uploaded fields
- document checklist tests pass

### Phase 3: LARS Engine

Goal: implement referral scoring as a deterministic service.

Tasks:

- create `rules/lars_factors.py`
- create `schemas/lars.py`
- create evaluator functions for base and use-case factors
- add handoff package model and builder
- wire LARS into packet builder

Deliverables:

- LARS starts at 100 and deducts correct factors
- LARS <70 produces `REFER`
- handoff package is generated
- Test Case 4 scores according to the corrected expected result

Note: Engineering Spec Test Case 4 says "Should REFER, LARS 65" but its listed
deductions total 55. The implementation should follow the factor arithmetic and
flag the doc mismatch.

### Phase 4: State Machine and Use-Case Router

Goal: replace implicit UC1-UC3 inference with deterministic routing and state.

Tasks:

- create `state_machine.py`
- create `use_case_router.py`
- update `session_state.py`
- update `session_service.py` to transition through S0-S7
- make UC5 skip property valuation and income requests
- continue document collection after referral

Deliverables:

- session phase behavior is deterministic
- route tests cover all six use cases
- UC5 forbidden-doc guard is tested

### Phase 5: Packet Builder and Verification Refactor

Goal: produce the new recommendation packet and independent verification.

Tasks:

- update `LoanRecommendationPacket`
- update `build_deterministic_loan_packet`
- build all use-case-specific calculated output groups
- add dual FNMA/FHLMC UC6 pathway output
- update verifier comparisons
- update compliance score components

Deliverables:

- recommendation packet includes received/uploaded/calculated/LARS/handoff data
- verifier catches calculation/LARS mismatches
- compliance score reflects calculation, guideline, docs, LARS, and audit trail

### Phase 6: Extraction and API Expansion

Goal: handle all required input modes.

Tasks:

- expand document type inference
- add JSON payload endpoints
- add new upload doc types
- update API serializers for new fields
- preserve existing `/ingest`, `/session`, `/status`, `/result`, `/verify`
- make `/session/from-json` the preferred creation endpoint

Deliverables:

- existing frontend remains functional
- structured JSON start path works with all five sample files
- new document types can be uploaded or passed as JSON

### Phase 7: Frontend Display

Goal: expose the new backend outputs without blocking backend correctness.

Tasks:

- update TS types and document labels
- show use case and state
- show LARS score/referral decision
- show missing docs and handoff reasons
- show calculated outputs in result drawer/detail view
- keep chat flow unchanged where possible

Deliverables:

- users can see why a file was auto-approved or referred
- tool drawer shows calculators and LARS events

### Phase 8: Guideline Retrieval Expansion

Goal: align retrieval focuses with all six use cases.

Tasks:

- expand retrieval policies
- add fake retrieval coverage for tests
- map required sections for UC4/UC5/UC6 as available
- gracefully report missing VA/SEL sources
- avoid making eligibility dependent on unavailable guide indices unless the use
  case requires guide support

Deliverables:

- citations are present for available FNMA/FHLMC sections
- missing guideline source is explicit, not silently ignored

## Testing Plan

### Unit Tests

Add tests:

- `tests/test_received_input.py`
- `tests/test_income_calculations.py`
- `tests/test_variable_income_calculations.py`
- `tests/test_self_employed_calculations.py`
- `tests/test_gig_calculations.py`
- `tests/test_ltv_calculations.py`
- `tests/test_mortgage_calculations.py`
- `tests/test_debt_dti_calculations.py`
- `tests/test_rental_calculations.py`
- `tests/test_va_calculations.py`
- `tests/test_savings_calculations.py`
- `tests/test_lars_factors.py`
- `tests/test_use_case_router.py`
- `tests/test_state_machine.py`

### Integration Tests

Update/add:

- `tests/test_packet_builder.py`
  - UC1 clean
  - UC2 PMI removal
  - UC3 self-employed stable
  - UC4 gig worker
  - UC5 VA IRRRL
  - UC6 W2 + rental dual GSE
- `tests/test_session_service.py`
  - JSON mortgage statement start path
  - continue collecting after LARS RED
  - UC5 forbidden docs not requested
  - handoff package generated
- `tests/test_api.py`
  - `/session/from-json` creates a session from each `example_json_inputs/` file
  - expanded upload types
  - JSON endpoints
  - status includes LARS/referral fields
- `tests/test_verification_service.py`
  - verifier catches modified calculator output
  - verifier catches modified LARS score
- `tests/test_extraction_service.py`
  - document type inference for Schedule E, 1099, lease, tax bill, insurance, VA

### Golden Fixtures

Create:

```text
data/mock_cases/new_docs/
  uc1_clean_w2.json
  uc2_pmi_removal.json
  uc3_self_employed_stable.json
  uc1_referral_issues.json
  uc6_negative_rental.json
```

Later add:

```text
data/mock_cases/new_docs/
  uc4_gig_worker.json
  uc5_va_irrrl.json
```

## Risk Assessment

### Low Risk

- adding standalone calculator modules
- adding LARS factor definitions and pure evaluator tests
- adding JSON input endpoints
- adding the received JSON adapter for the observed sample shape
- extending frontend TypeScript types

### Medium Risk

- expanding Pydantic schemas while preserving existing saved sessions
- handling inconsistent upstream payment fields without hiding source-data warnings
- updating session state transitions without breaking the current frontend
- keeping Agno session-state sync compatible with expanded state payloads
- retrieval availability for all required guideline sections

### High Risk

- real property valuation API integration
- OCR confidence and field confidence if the extractor cannot provide reliable confidence
- UC5 VA guideline retrieval if local VA guide source is absent
- exact compliance architecture because referenced compliance docs are missing
- exact S0-S7 behavior because referenced Engineer's Technical Spec v1 is missing

## Recommended Delivery Order

1. Build calculators and tests first.
2. Add schemas/document requirements and JSON input support.
3. Add LARS scoring and handoff package.
4. Add state machine/use-case router.
5. Refactor packet builder and verifier.
6. Expand extraction/API/frontend.
7. Expand retrieval focuses.

This order keeps most work deterministic and testable before touching the
conversation/UI layer.

## Answer To The Main Question

The app should be modified, not rewritten. The current architecture is a good
host for the new system, but the domain implementation is too narrow and should
be reworked around the new taxonomy, six use cases, formula package, LARS engine,
and explicit state machine.

After reviewing `example_json_inputs/`, the first implementation should be
JSON-first. Mortgage statement extraction should not be built as a required
step. Instead, add a received-input adapter that accepts the upstream
`core/profile/statement/raw/formDecisions/propertyLookup` payload and starts the
workflow from that normalized received data.

Expected effort is a moderate-to-large refactor:

- keep roughly 50-60% of the app shell
- replace or heavily modify 70-80% of the mortgage-domain logic
- add broad test coverage before changing the session flow

The most important engineering rule is to move all calculations and referral
decisions into deterministic, unit-tested services before letting the LOA or
Verifier agents summarize anything.
