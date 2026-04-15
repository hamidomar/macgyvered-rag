from __future__ import annotations


def monthly_pi(principal: float, annual_rate_percent: float, term_months: int = 360) -> float:
    if principal < 0:
        raise ValueError("principal cannot be negative")
    if term_months <= 0:
        raise ValueError("term_months must be positive")
    monthly_rate = annual_rate_percent / 100 / 12
    if monthly_rate == 0:
        return round(principal / term_months, 2)
    factor = (1 + monthly_rate) ** term_months
    payment = principal * (monthly_rate * factor) / (factor - 1)
    return round(payment, 2)


def tax_monthly(tax_bill_annual: float) -> float:
    return round(tax_bill_annual / 12, 2)


def insurance_monthly(insurance_annual: float) -> float:
    return round(insurance_annual / 12, 2)


def pitia_total(pi: float, tax: float, insurance: float, escrow: float | None = None, hoa: float = 0.0, pmi: float = 0.0) -> float:
    return round(pi + tax + insurance + hoa + pmi, 2)


def new_pmi_for_screening(use_case: str, ltv_ratio: float | None, pmi_monthly: float | None = None) -> float:
    if use_case == "uc2_pmi_removal":
        return 0.0
    if ltv_ratio is not None and ltv_ratio <= 0.80:
        return 0.0
    return round(pmi_monthly or 0.0, 2)

