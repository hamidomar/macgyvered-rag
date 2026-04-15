from __future__ import annotations


def pmi_savings(pmi_monthly: float | None, eliminated: bool = True) -> float:
    if not eliminated:
        return 0.0
    return round(pmi_monthly or 0.0, 2)


def original_ltv(purchase_price: float, down_payment: float) -> float:
    if purchase_price <= 0:
        raise ValueError("purchase_price must be greater than 0")
    return round((purchase_price - down_payment) / purchase_price, 4)


def combined_ltv(current_balance: float, second_lien_balance: float | None, estimated_property_value: float) -> float:
    if estimated_property_value <= 0:
        raise ValueError("estimated_property_value must be greater than 0")
    return round((current_balance + (second_lien_balance or 0.0)) / estimated_property_value, 4)


def equity_gained(estimated_property_value: float, current_balance: float) -> float:
    return round(estimated_property_value - current_balance, 2)


def total_savings_with_pmi(rate_savings_amount: float, pmi_savings_amount: float) -> float:
    return round(rate_savings_amount + pmi_savings_amount, 2)

