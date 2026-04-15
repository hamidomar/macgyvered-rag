from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP


PAY_FREQUENCY_MULTIPLIERS = {
    "weekly": 52 / 12,
    "biweekly": 26 / 12,
    "semimonthly": 2,
    "monthly": 1,
    "annual": 1 / 12,
}


def _round_money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _monthly_decimal(amount: float, pay_frequency: str) -> Decimal:
    amount_decimal = Decimal(str(amount))
    if pay_frequency == "weekly":
        return amount_decimal * Decimal("52") / Decimal("12")
    if pay_frequency == "biweekly":
        return amount_decimal * Decimal("26") / Decimal("12")
    if pay_frequency == "semimonthly":
        return amount_decimal * Decimal("2")
    if pay_frequency == "monthly":
        return amount_decimal
    if pay_frequency == "annual":
        return amount_decimal / Decimal("12")
    raise ValueError(f"Unsupported pay frequency: {pay_frequency}")


def gross_monthly_income(amount: float, pay_frequency: str) -> float:
    if pay_frequency not in PAY_FREQUENCY_MULTIPLIERS:
        raise ValueError(f"Unsupported pay frequency: {pay_frequency}")
    return float(_monthly_decimal(amount, pay_frequency).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def annual_salary_gmi(annual_salary: float) -> float:
    return gross_monthly_income(annual_salary, "annual")


def paystub_annualized(paystub_gross_current: float, pay_frequency: str) -> float:
    if pay_frequency not in PAY_FREQUENCY_MULTIPLIERS:
        raise ValueError(f"Unsupported pay frequency: {pay_frequency}")
    if pay_frequency == "annual":
        return _round_money(paystub_gross_current)
    annual = _monthly_decimal(paystub_gross_current, pay_frequency) * Decimal("12")
    return float(annual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def w2_paystub_diff_pct(paystub_annualized_income: float, w2_box1: float) -> float:
    if w2_box1 <= 0:
        raise ValueError("w2_box1 must be greater than 0")
    return round(abs(paystub_annualized_income - w2_box1) / w2_box1, 4)


def w2_income_trend(w2_box1_yr1: float, w2_box1_yr2: float) -> str:
    if w2_box1_yr1 < w2_box1_yr2:
        return "declining"
    if w2_box1_yr1 > w2_box1_yr2:
        return "increasing"
    return "stable"


def usable_w2_income(w2_box1_yr1: float, w2_box1_yr2: float) -> float:
    return round(min(w2_box1_yr1, w2_box1_yr2), 2)


def employment_tenure_check(tenure_months: int | None) -> bool:
    return tenure_months is not None and tenure_months >= 24


def validate_paystub_recency(paystub_period_end: date, today: date, max_age_days: int = 30) -> bool:
    return 0 <= (today - paystub_period_end).days <= max_age_days


def validate_paystub_ytd(paystub_ytd: float, paystub_gross_current: float) -> bool:
    return paystub_ytd >= paystub_gross_current > 0


def validate_w2_years(actual_years: list[int], expected_w2_years: list[int]) -> bool:
    if not expected_w2_years:
        return len(set(actual_years)) >= 2
    return set(expected_w2_years).issubset(set(actual_years))
