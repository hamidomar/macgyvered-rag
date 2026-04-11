from __future__ import annotations


PAY_FREQUENCY_MULTIPLIERS = {
    "weekly": 52 / 12,
    "biweekly": 26 / 12,
    "semimonthly": 24 / 12,
    "monthly": 1.0,
    "annual": 1 / 12,
}


def calc_w2_income(gross_income: float, pay_frequency: str, gse: str = "fnma") -> dict:
    if pay_frequency not in PAY_FREQUENCY_MULTIPLIERS:
        raise ValueError(f"Unsupported pay frequency: {pay_frequency}")
    monthly_qualifying = round(gross_income * PAY_FREQUENCY_MULTIPLIERS[pay_frequency], 2)
    annual_income = round(monthly_qualifying * 12, 2)
    return {
        "gse": gse,
        "monthly_qualifying": monthly_qualifying,
        "annual_income": annual_income,
    }


def calc_ltv(loan_amount: float, property_value: float) -> dict:
    if property_value <= 0:
        raise ValueError("property_value must be greater than 0")
    ltv_ratio = round(loan_amount / property_value, 4)
    ltv_percent = round(ltv_ratio * 100, 1)
    return {
        "ltv_ratio": ltv_ratio,
        "ltv_percent": ltv_percent,
    }


def calc_pmi_savings(current_pmi_monthly: float, years_remaining: int) -> dict:
    if years_remaining < 0:
        raise ValueError("years_remaining cannot be negative")
    monthly_savings = round(current_pmi_monthly, 2)
    total_savings = round(current_pmi_monthly * years_remaining * 12, 2)
    return {
        "monthly_savings": monthly_savings,
        "total_savings": total_savings,
    }


def calc_se_income(
    yr1_net: float,
    yr2_net: float,
    depreciation: float = 0.0,
    depletion: float = 0.0,
    gse: str = "fnma",
) -> dict:
    qualifying_monthly = round((yr1_net + yr2_net + depreciation + depletion) / 24, 2)
    return {
        "gse": gse,
        "qualifying_monthly": qualifying_monthly,
    }


def build_calculator_tools():
    from agno.tools import tool

    @tool(show_result=True)
    def calc_w2_income_tool(gross_income: float, pay_frequency: str, gse: str = "fnma") -> dict:
        """Calculate qualifying W-2 income from a per-period gross pay amount."""
        return calc_w2_income(gross_income=gross_income, pay_frequency=pay_frequency, gse=gse)

    @tool(show_result=True)
    def calc_ltv_tool(loan_amount: float, property_value: float) -> dict:
        """Calculate the loan-to-value ratio and loan-to-value percent."""
        return calc_ltv(loan_amount=loan_amount, property_value=property_value)

    @tool(show_result=True)
    def calc_pmi_savings_tool(current_pmi_monthly: float, years_remaining: int) -> dict:
        """Calculate monthly and total PMI savings remaining on the loan."""
        return calc_pmi_savings(
            current_pmi_monthly=current_pmi_monthly,
            years_remaining=years_remaining,
        )

    @tool(show_result=True)
    def calc_se_income_tool(
        yr1_net: float,
        yr2_net: float,
        depreciation: float = 0.0,
        depletion: float = 0.0,
        gse: str = "fnma",
    ) -> dict:
        """Calculate self-employed qualifying monthly income using a two-year average."""
        return calc_se_income(
            yr1_net=yr1_net,
            yr2_net=yr2_net,
            depreciation=depreciation,
            depletion=depletion,
            gse=gse,
        )

    return [
        calc_w2_income_tool,
        calc_ltv_tool,
        calc_pmi_savings_tool,
        calc_se_income_tool,
    ]
