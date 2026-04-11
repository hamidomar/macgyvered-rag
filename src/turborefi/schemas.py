from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


GSEType = Literal["fnma", "fhlmc", "unknown"]
UseCaseType = Literal["uc1_rate_term_refi", "uc2_pmi_removal", "uc3_se_rate_term"]
IncomeType = Literal["unknown", "w2", "self_employed", "gig_1099", "rental"]


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


class PaystubData(BaseModel):
    employer_name: str
    gross_this_period: float
    pay_frequency: Literal["weekly", "biweekly", "semimonthly", "monthly"]
    ytd_gross: float
    pay_period_end_date: date


class W2Data(BaseModel):
    employer_name: str
    wages_box1: float
    tax_year: int


class ScheduleCData(BaseModel):
    tax_year: int
    net_profit_loss: float
    depreciation: float = 0.0
    business_name: str


class BorrowerFacts(BaseModel):
    declared_income_type: IncomeType | None = None
    employer_name: str | None = None
    employment_years: float | None = None
    hire_date: date | None = None
    annual_income: float | None = None
    business_name: str | None = None
    years_in_business: int | None = None
    current_property_value: float | None = None
    property_value_source: str | None = None
    target_rate_percent: float | None = None


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


class BorrowerCase(BaseModel):
    case_id: str
    borrower_name: str
    use_case: UseCaseType
    income_type: IncomeType
    borrower_facts: BorrowerFacts = Field(default_factory=BorrowerFacts)
    documents: DocumentSet
    notes: list[str] = Field(default_factory=list)


class GuidelineCitation(BaseModel):
    section: str
    finding: str
    gse: Literal["fnma", "fhlmc"] | None = None


class ToolCallRecord(BaseModel):
    tool: str
    inputs: dict[str, Any]
    result: dict[str, Any]


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
    qualifying_monthly_income: float
    ltv_percent: float
    monthly_savings_estimate: float
    guideline_citations: list[GuidelineCitation] = Field(default_factory=list)
    calculations: dict[str, ToolCallRecord] = Field(default_factory=dict)
    documentation_status: DocumentationStatus = Field(default_factory=DocumentationStatus)
    reasoning_chain: list[str] = Field(default_factory=list)


class ComplianceComponent(BaseModel):
    component: str
    weight: float
    score: float
    status: Literal["PASS", "FLAG", "FAIL"]


class ComplianceScore(BaseModel):
    total: float
    components: list[ComplianceComponent] = Field(default_factory=list)


class FieldComparison(BaseModel):
    field: str
    loa_value: Any
    verifier_value: Any
    match: bool
    guideline_section: str | None = None
    notes: str = ""


class VerificationReport(BaseModel):
    verification_status: Literal["PASS", "FLAG", "FAIL"]
    field_comparisons: list[FieldComparison] = Field(default_factory=list)
    compliance_score: ComplianceScore | None = None
    audit_notes: list[str] = Field(default_factory=list)


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
    borrower_case_id: str | None = None
    session_name: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    borrower_name: str = "Borrower"
    use_case: UseCaseType = "uc1_rate_term_refi"
    income_type: IncomeType = "unknown"
    borrower_facts: BorrowerFacts = Field(default_factory=BorrowerFacts)
    documents: DocumentSet = Field(default_factory=DocumentSet)
    intake_pending: list[str] = Field(default_factory=list)
    received_documents: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    pending_documents: list[str] = Field(default_factory=list)
    current_phase: str = "extraction"
    retrieval_events: list[RetrievalEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    loa_output: LoanRecommendationPacket | None = None
    verifier_output: VerificationReport | None = None
