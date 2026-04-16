from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


GSEType = Literal["fnma", "fhlmc", "unknown"]
UseCaseType = Literal["uc1_rate_term_refi", "uc2_pmi_removal", "uc3_se_rate_term"]
IncomeType = Literal["unknown", "w2", "self_employed", "gig_1099", "rental"]
FicoRange = Literal["below_620", "620_679", "680_719", "720_759", "760_plus", "unknown"]
PropertyType = Literal["sfr", "townhome", "condo", "unknown"]
PmiType = Literal["borrower_paid", "lender_paid", "unknown"]
ReferralDecision = Literal["AUTOMATED", "REFERRED"]


class MortgageStatementData(BaseModel):
    borrower_name: str | None = None
    current_rate_percent: float
    loan_balance: float
    servicer_name: str
    loan_number: str
    gse_owner: GSEType = "unknown"
    monthly_pi: float
    monthly_pmi: float | None = None
    original_property_value: float | None = None
    property_address: str | None = None
    monthly_escrow: float | None = None
    loan_type_detected: str | None = None
    rate_type: str | None = None
    origination_date: date | None = None
    maturity_date: date | None = None
    original_loan_amount: float | None = None
    statement_date: date | None = None


class PaystubData(BaseModel):
    employer_name: str
    gross_this_period: float
    pay_frequency: Literal["weekly", "biweekly", "semimonthly", "monthly"]
    ytd_gross: float
    pay_period_end_date: date
    base_pay: float | None = None
    overtime_pay: float = 0.0
    bonus_pay: float = 0.0
    commission_pay: float = 0.0
    ocr_confidence: float | None = None


class W2Data(BaseModel):
    employer_name: str
    wages_box1: float
    tax_year: int
    employer_ein: str | None = None
    ocr_confidence: float | None = None


class ScheduleCData(BaseModel):
    tax_year: int
    net_profit_loss: float
    depreciation: float = 0.0
    business_name: str


class IdentityDocumentData(BaseModel):
    document_present: bool = True
    document_type: str | None = None
    borrower_name: str | None = None
    issuing_state: str | None = None
    id_last4: str | None = None
    expiration_date: date | None = None


class TaxBillData(BaseModel):
    document_present: bool = True
    tax_bill_annual: float | None = None
    tax_year: int | None = None
    property_address: str | None = None
    parcel_number: str | None = None


class InsuranceDeclarationData(BaseModel):
    document_present: bool = True
    insurance_annual: float | None = None
    carrier_name: str | None = None
    policy_number_last4: str | None = None
    effective_date: date | None = None


class PmiStatementData(BaseModel):
    document_present: bool = True
    pmi_monthly: float | None = None
    pmi_type: str | None = None
    servicer_name: str | None = None


class ClosingDisclosureData(BaseModel):
    document_present: bool = True
    closing_date: date | None = None
    loan_amount: float | None = None
    cash_to_close: float | None = None
    borrower_name: str | None = None


class BorrowerFacts(BaseModel):
    declared_income_type: IncomeType | None = None
    employer_name: str | None = None
    employment_years: float | None = None
    tenure_months: int | None = None
    hire_date: date | None = None
    annual_income: float | None = None
    business_name: str | None = None
    years_in_business: int | None = None
    current_property_value: float | None = None
    property_value_source: str | None = None
    target_rate_percent: float | None = None
    fico_range: FicoRange | None = None
    fico_uncertain: bool = False
    single_income_source: bool | None = None
    property_type: PropertyType | None = None
    pmi_type: PmiType | None = None
    purchase_price: float | None = None
    down_payment_amount: float | None = None
    has_second_lien: bool | None = None
    second_lien_balance: float | None = None
    employment_gap: bool = False
    factual_uncertainties: list[str] = Field(default_factory=list)


class ReceivedMortgageData(BaseModel):
    current_rate: float | None = None
    current_balance: float | None = None
    reported_monthly_payment: float | None = None
    current_pi: float | None = None
    escrow_monthly: float | None = None
    pmi_monthly: float | None = None
    loan_number: str | None = None
    property_address: str | None = None
    servicer_name: str | None = None
    loan_type_detected: str | None = None
    rate_type: str | None = None
    origination_date: date | None = None
    maturity_date: date | None = None
    original_loan_amount: float | None = None
    api_value: float | None = None
    estimated_property_value: float | None = None
    ltv: float | None = None
    purchase_price: float | None = None
    purchase_date: str | None = None
    property_type: str | None = None
    property_tax_annual: float | None = None
    statement_date: date | None = None
    lookup_source: str | None = None
    lookup_time_ms: int | None = None
    b11_status: str = "not_evaluated_single_source"


class ScreeningAssumptions(BaseModel):
    new_rate: float | None = None
    term_months: int = 360
    closing_cost_pct: float = 0.015
    today: date | None = None
    expected_w2_years: list[int] = Field(default_factory=list)
    monthly_debts: float | None = None
    hoa_monthly: float | None = None


class LarsEvent(BaseModel):
    factor_code: str
    factor_name: str
    condition_met: bool = True
    deduction: int
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    score_after: int
    hard_red: bool = False


class LarsResult(BaseModel):
    starting_score: int = 100
    final_score: int = 100
    events: list[LarsEvent] = Field(default_factory=list)
    referral_triggered: bool = False
    decision: ReferralDecision = "AUTOMATED"


class HandoffPackage(BaseModel):
    borrower_id: str
    use_case: UseCaseType
    lars_score: int
    lars_events: list[LarsEvent] = Field(default_factory=list)
    referral_reasons: list[str] = Field(default_factory=list)
    already_collected_do_not_reask: list[str] = Field(default_factory=list)
    collected_data: dict[str, Any] = Field(default_factory=dict)
    missing_data: list[str] = Field(default_factory=list)
    human_action_items: list[str] = Field(default_factory=list)
    conversation_transcript: list[dict[str, Any]] = Field(default_factory=list)
    gse_analysis: dict[str, Any] | None = None


class DocumentSet(BaseModel):
    mortgage_statement: MortgageStatementData | None = None
    paystubs: list[PaystubData] = Field(default_factory=list)
    w2s: list[W2Data] = Field(default_factory=list)
    schedule_c: list[ScheduleCData] = Field(default_factory=list)
    additional_documents: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)

    def category_count(self, category: str) -> int:
        if category == "mortgage_statement":
            return 1 if self.mortgage_statement is not None else 0
        if category == "paystubs":
            return len(self.paystubs)
        if category == "w2s":
            return len(self.w2s)
        if category == "schedule_c":
            return len(self.schedule_c)
        return len(self.additional_documents.get(category, []))

    def received_categories(self) -> list[str]:
        categories: list[str] = []
        if self.mortgage_statement is not None:
            categories.append("mortgage_statement")
        if self.paystubs:
            categories.append("paystubs")
        if self.w2s:
            categories.append("w2s")
        if self.schedule_c:
            categories.append("schedule_c")
        for key, values in self.additional_documents.items():
            if values:
                categories.append(key)
        return categories

class GuidelineCitation(BaseModel):
    section: str
    finding: str
    gse: Literal["fnma", "fhlmc"] | None = None
    focus_key: str | None = None
    focus_label: str | None = None
    title: str | None = None
    why_selected: str | None = None


class ToolCallRecord(BaseModel):
    tool: str
    inputs: dict[str, Any]
    result: dict[str, Any]


class GSEFocusFinding(BaseModel):
    gse: Literal["fnma", "fhlmc"]
    focus_key: str
    focus_label: str
    section_ids: list[str] = Field(default_factory=list)
    assessment: Literal["pass", "fail", "unclear", "not_applicable"]
    rule_summary: str
    decision_description: str
    borrower_facts_used: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    source: Literal["agentic", "deterministic"] = "deterministic"


class GSEAnalysisSummary(BaseModel):
    gse: Literal["fnma", "fhlmc"]
    supported: bool
    overall_reason: str
    focus_results: list[GSEFocusFinding] = Field(default_factory=list)


class DocumentationStatus(BaseModel):
    received: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    not_required: list[str] = Field(default_factory=list)


class LoanRecommendationPacket(BaseModel):
    borrower_name: str
    use_case: UseCaseType
    fnma_eligible: bool
    fhlmc_eligible: bool
    recommended_gse: Literal["fnma", "fhlmc"]
    recommended_gse_reason: str = ""
    qualifying_monthly_income: float
    ltv_percent: float
    monthly_savings_estimate: float
    guideline_citations: list[GuidelineCitation] = Field(default_factory=list)
    calculations: dict[str, ToolCallRecord] = Field(default_factory=dict)
    documentation_status: DocumentationStatus = Field(default_factory=DocumentationStatus)
    reasoning_chain: list[str] = Field(default_factory=list)
    borrower_id_token: str | None = None
    calculated_outputs: dict[str, Any] = Field(default_factory=dict)
    lars_result: LarsResult | None = None
    handoff_package: HandoffPackage | None = None
    screening_assumptions: ScreeningAssumptions | None = None
    source_data_warnings: list[str] = Field(default_factory=list)
    gse_analysis: dict[str, GSEAnalysisSummary] = Field(default_factory=dict)

class RetrievalEvent(BaseModel):
    gse: Literal["fnma", "fhlmc"]
    tool: str
    query: str
    result_summary: str


class ConversationToolTrace(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class ConversationMessage(BaseModel):
    role: Literal["user", "agent"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_trace: list[ConversationToolTrace] = Field(default_factory=list)


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    session_name: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    borrower_name: str = "Borrower"
    use_case: UseCaseType = "uc1_rate_term_refi"
    income_type: IncomeType = "unknown"
    borrower_id_token: str | None = None
    source_mode: Literal["legacy_upload", "received_json_uc1_uc2"] = "legacy_upload"
    state_machine_state: str = "S0_INIT"
    received_mortgage: ReceivedMortgageData | None = None
    screening_assumptions: ScreeningAssumptions = Field(default_factory=ScreeningAssumptions)
    borrower_facts: BorrowerFacts = Field(default_factory=BorrowerFacts)
    documents: DocumentSet = Field(default_factory=DocumentSet)
    source_data_warnings: list[str] = Field(default_factory=list)
    calculated_outputs: dict[str, Any] = Field(default_factory=dict)
    lars_result: LarsResult | None = None
    handoff_package: HandoffPackage | None = None
    referral_decision: ReferralDecision | None = None
    unsupported_reason: str | None = None
    intake_pending: list[str] = Field(default_factory=list)
    received_documents: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    pending_documents: list[str] = Field(default_factory=list)
    full_application_intent: Literal["proceed", "decline"] | None = None
    current_phase: str = "extraction"
    retrieval_events: list[RetrievalEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    loa_output: LoanRecommendationPacket | None = None
