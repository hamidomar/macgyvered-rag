from __future__ import annotations

from dataclasses import dataclass, field

from turborefi.schemas import BorrowerFacts, ReceivedMortgageData, UseCaseType


@dataclass(frozen=True)
class UseCaseRoutingResult:
    use_case: UseCaseType
    confidence: float
    reasons: list[str] = field(default_factory=list)
    deferred_reason: str | None = None


def route_uc1_uc2(received: ReceivedMortgageData, facts: BorrowerFacts | None = None) -> UseCaseRoutingResult:
    facts = facts or BorrowerFacts()
    loan_type = (received.loan_type_detected or "").lower()
    if loan_type == "va":
        return UseCaseRoutingResult(
            use_case="uc1_rate_term_refi",
            confidence=1.0,
            reasons=["loan_type_detected=va"],
            deferred_reason="VA loans are deferred in the UC1/UC2 minimal build.",
        )

    reasons: list[str] = []
    if received.pmi_monthly and received.pmi_monthly > 0:
        reasons.append("pmi_monthly_present")
    if facts.pmi_type == "lender_paid":
        reasons.append("borrower_reported_lender_paid_pmi")

    if reasons:
        return UseCaseRoutingResult(
            use_case="uc2_pmi_removal",
            confidence=0.95,
            reasons=reasons,
        )

    return UseCaseRoutingResult(
        use_case="uc1_rate_term_refi",
        confidence=0.8,
        reasons=["default_w2_rate_term_path"],
    )

