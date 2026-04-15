from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from turborefi.schemas import MortgageStatementData, ReceivedMortgageData, ScreeningAssumptions
from turborefi.services.calculations.ltv import b11_status_for_single_source, ltv


@dataclass(frozen=True)
class ReceivedInputResult:
    mortgage_statement: MortgageStatementData
    received_mortgage: ReceivedMortgageData
    screening_assumptions: ScreeningAssumptions
    borrower_id_token: str
    warnings: list[str]
    unsupported_reason: str | None = None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _number(value)
        if parsed is not None:
            return parsed
    return None


def _parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _property_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    if "condo" in lowered:
        return "condo"
    if "town" in lowered:
        return "townhome"
    if "single" in lowered or "sfr" in lowered:
        return "sfr"
    return None


def _tokenize_borrower(*parts: str | None) -> str:
    seed = "|".join(part.strip() for part in parts if part and part.strip()) or "borrower"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"borrower_{digest}"


def _payment_component_sum(payment_breakdown: dict[str, Any]) -> float | None:
    principal = _number(payment_breakdown.get("principal"))
    interest = _number(payment_breakdown.get("interest"))
    if principal is None and interest is None:
        return None
    return round((principal or 0.0) + (interest or 0.0), 2)


def parse_received_json(payload: dict[str, Any], *, new_rate: float | None = None) -> ReceivedInputResult:
    core = payload.get("core") or {}
    statement = payload.get("statement") or {}
    property_lookup = payload.get("propertyLookup") or {}
    property_data = core.get("propertyData") or {}
    payment_breakdown = core.get("paymentBreakdown") or {}

    warnings: list[str] = []

    current_balance = _first_number(core.get("balance"))
    current_rate = _first_number(core.get("rate"))
    reported_monthly_payment = _first_number(core.get("monthlyPayment"))
    current_pi = _payment_component_sum(payment_breakdown)
    escrow_monthly = _first_number(payment_breakdown.get("escrow"))
    pmi_monthly = _first_number(payment_breakdown.get("pmi"))
    api_value = _first_number(
        property_lookup.get("estimatedValue"),
        core.get("propertyValue"),
        property_data.get("estimatedValue"),
    )

    if reported_monthly_payment is not None and current_pi is not None:
        if abs(reported_monthly_payment - current_pi) > 1:
            warnings.append(
                "reported_monthly_payment_differs_from_principal_interest_components"
            )

    ltv_ratio = None
    if current_balance is not None and api_value is not None and api_value > 0:
        ltv_ratio = ltv(current_balance, api_value)

    property_address = core.get("propertyAddress") or statement.get("borrowerAddress")
    loan_type_detected = (core.get("loanType") or "").lower() or None
    unsupported_reason = "VA loans are deferred in the UC1/UC2 minimal build." if loan_type_detected == "va" else None

    received = ReceivedMortgageData(
        current_rate=current_rate,
        current_balance=current_balance,
        reported_monthly_payment=reported_monthly_payment,
        current_pi=current_pi,
        escrow_monthly=escrow_monthly,
        pmi_monthly=pmi_monthly,
        loan_number=core.get("loanNumber"),
        property_address=property_address,
        servicer_name=core.get("servicer"),
        loan_type_detected=loan_type_detected,
        rate_type=core.get("rateType"),
        origination_date=_parse_date(core.get("originationDate")),
        maturity_date=_parse_date(core.get("maturityDate")),
        original_loan_amount=_first_number(core.get("originalLoanAmount")),
        api_value=api_value,
        estimated_property_value=api_value,
        ltv=ltv_ratio,
        purchase_price=_first_number(property_lookup.get("purchasePrice"), property_data.get("purchasePrice")),
        purchase_date=property_lookup.get("purchaseDate") or property_data.get("purchaseDate"),
        property_type=_property_type(property_lookup.get("propertyType") or property_data.get("propertyType")),
        property_tax_annual=_first_number(property_lookup.get("propertyTaxAnnual")),
        statement_date=_parse_date(statement.get("statementDateRaw")),
        lookup_source=property_lookup.get("source"),
        lookup_time_ms=_int(property_lookup.get("lookupTimeMs")),
        b11_status=b11_status_for_single_source(),
    )

    mortgage_statement = MortgageStatementData(
        borrower_name=None,
        current_rate_percent=current_rate or 0.0,
        loan_balance=current_balance or 0.0,
        servicer_name=core.get("servicer") or "",
        loan_number=core.get("loanNumber") or "",
        monthly_pi=current_pi or reported_monthly_payment or 0.0,
        monthly_pmi=pmi_monthly,
        original_property_value=api_value,
        property_address=property_address,
        monthly_escrow=escrow_monthly,
        loan_type_detected=loan_type_detected,
        rate_type=core.get("rateType"),
        origination_date=received.origination_date,
        maturity_date=received.maturity_date,
        original_loan_amount=received.original_loan_amount,
        statement_date=received.statement_date,
    )

    assumptions = ScreeningAssumptions(new_rate=new_rate)
    token = _tokenize_borrower(statement.get("borrowerName"), core.get("loanNumber"), property_address)

    return ReceivedInputResult(
        mortgage_statement=mortgage_statement,
        received_mortgage=received,
        screening_assumptions=assumptions,
        borrower_id_token=token,
        warnings=warnings,
        unsupported_reason=unsupported_reason,
    )

