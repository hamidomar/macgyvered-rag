from __future__ import annotations

from turborefi.services.calculations.mortgage import monthly_pi


def old_pi(current_balance: float, current_rate: float, term_months: int = 360) -> float:
    return monthly_pi(current_balance, current_rate, term_months)


def new_pi(current_balance: float, new_rate: float, term_months: int = 360) -> float:
    return monthly_pi(current_balance, new_rate, term_months)


def rate_savings(old_pi_amount: float, new_pi_amount: float) -> float:
    return round(old_pi_amount - new_pi_amount, 2)


def closing_cost_estimate(current_balance: float, pct: float = 0.015) -> float:
    return round(current_balance * pct, 2)


def break_even_months(closing_costs: float, monthly_savings: float) -> float | None:
    if monthly_savings <= 0:
        return None
    return round(closing_costs / monthly_savings, 1)

