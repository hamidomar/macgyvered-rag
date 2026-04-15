from __future__ import annotations

from datetime import date

from turborefi.schemas import ScreeningAssumptions


def build_screening_assumptions(
    *,
    new_rate: float | None = None,
    term_months: int = 360,
    closing_cost_pct: float = 0.015,
    today: date | None = None,
    expected_w2_years: list[int] | None = None,
    monthly_debts: float | None = None,
    hoa_monthly: float | None = None,
) -> ScreeningAssumptions:
    return ScreeningAssumptions(
        new_rate=new_rate,
        term_months=term_months,
        closing_cost_pct=closing_cost_pct,
        today=today,
        expected_w2_years=expected_w2_years or [],
        monthly_debts=monthly_debts,
        hoa_monthly=hoa_monthly,
    )

