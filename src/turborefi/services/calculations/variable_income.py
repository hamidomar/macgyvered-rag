from __future__ import annotations


def variable_income_pct(ot: float = 0.0, bonus: float = 0.0, commission: float = 0.0, base: float | None = None) -> float:
    if base is None or base <= 0:
        return 0.0
    return round((ot + bonus + commission) / base, 4)


def variable_income_history_check(variable_income_present: bool, tenure_months: int | None) -> bool:
    if not variable_income_present:
        return True
    return tenure_months is not None and tenure_months >= 24


def variable_income_2yr_average(w2_yr1_variable: float, w2_yr2_variable: float) -> float:
    return round((w2_yr1_variable + w2_yr2_variable) / 24, 2)


def variable_income_decline_pct(prior_year_variable: float, current_year_variable: float) -> float:
    if prior_year_variable <= 0:
        return 0.0
    return round((prior_year_variable - current_year_variable) / prior_year_variable, 4)


def should_exclude_variable_income(decline_pct: float, current_year_variable: float) -> bool:
    return decline_pct > 0.20 or current_year_variable == 0

