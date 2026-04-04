import json
from src.tools.calculators import calc_ltv, calc_w2_income, calc_pmi_savings, calc_se_income

def test_calc_ltv():
    res = calc_ltv.invoke({"loan_amount": 80000, "property_value": 100000, "gse": "fnma"})
    assert isinstance(res, str)
    data = json.loads(res)
    assert "ltv_ratio" in data
    assert "ltv_percent" in data
    assert data["ltv_percent"] == 80.0

def test_calc_w2_income():
    res = calc_w2_income.invoke({"gross_monthly": 5000, "pay_frequency": "monthly", "gse": "fnma"})
    data = json.loads(res)
    assert "annual_income" in data
    assert "monthly_qualifying" in data

def test_calc_pmi_savings():
    res = calc_pmi_savings.invoke({"current_pmi_monthly": 100, "years_remaining": 10, "gse": "fnma"})
    data = json.loads(res)
    assert "total_savings" in data
    assert "monthly_savings" in data

def test_calc_se_income():
    res = calc_se_income.invoke({"yr1_net": 50000, "yr2_net": 60000, "depreciation": 5000, "depletion": 0, "gse": "fnma"})
    data = json.loads(res)
    assert "qualifying_monthly" in data
