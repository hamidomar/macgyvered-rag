import json
from langchain_core.tools import tool

@tool
def calc_ltv(loan_amount: float, property_value: float) -> str:
    """Calculate Loan-to-Value ratio.

    Args:
        loan_amount: Current loan balance
        property_value: Current estimated property value
    """
    # REAL IMPLEMENTATION — this is trivial division
    ltv_ratio = loan_amount / property_value
    ltv_percent = round(ltv_ratio * 100, 1)
    return json.dumps({"ltv_ratio": round(ltv_ratio, 4), "ltv_percent": ltv_percent})

@tool
def calc_w2_income(gross_monthly: float, pay_frequency: str, gse: str) -> str:
    """Calculate qualifying monthly income from W2/salaried employment.

    Args:
        gross_monthly: Gross income for the most recent pay period
        pay_frequency: "weekly" | "biweekly" | "semimonthly" | "monthly"
        gse: "fnma" or "fhlmc"
    """
    # STUB — pay frequency conversion may have GSE-specific nuances
    # TODO: validate against FNMA B3-3.1-01 and FHLMC 5302.2 for edge cases
    multipliers = {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12}
    annual = gross_monthly * multipliers.get(pay_frequency, 12)
    monthly_qualifying = round(annual / 12, 2)
    return json.dumps({"annual_income": round(annual, 2), "monthly_qualifying": monthly_qualifying})

@tool
def calc_pmi_savings(current_pmi_monthly: float, years_remaining: float) -> str:
    """Calculate total and monthly savings from PMI removal.

    Args:
        current_pmi_monthly: Current monthly PMI payment
        years_remaining: Estimated remaining years on the loan
    """
    # STUB — real PMI elimination depends on LTV thresholds, lender policies
    # TODO: implement full PMI removal eligibility logic per B2-1.3-01
    total_savings = round(current_pmi_monthly * years_remaining * 12, 2)
    return json.dumps({"total_savings": total_savings, "monthly_savings": current_pmi_monthly})

@tool
def calc_se_income(yr1_net: float, yr2_net: float, depreciation: float, depletion: float, gse: str) -> str:
    """Calculate qualifying monthly income for self-employed borrowers.

    Args:
        yr1_net: Year 1 net profit/loss from Schedule C
        yr2_net: Year 2 net profit/loss from Schedule C
        depreciation: Total depreciation addback (both years combined)
        depletion: Total depletion addback (both years combined, often 0)
        gse: "fnma" or "fhlmc"
    """
    # STUB — real SE income calc has declining income rules, minimum years in business, etc.
    # TODO: implement full logic per B3-3.3-03 (FNMA) and FHLMC 5304.1
    qualifying_monthly = round((yr1_net + yr2_net + depreciation + depletion) / 24, 2)
    return json.dumps({"qualifying_monthly": qualifying_monthly})
