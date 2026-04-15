from __future__ import annotations


def ltv(current_balance: float, estimated_property_value: float) -> float:
    if estimated_property_value <= 0:
        raise ValueError("estimated_property_value must be greater than 0")
    return round(current_balance / estimated_property_value, 4)


def ltv_percent(current_balance: float, estimated_property_value: float) -> float:
    return round(ltv(current_balance, estimated_property_value) * 100, 1)


def ltv_threshold_for_use_case(use_case: str) -> float:
    return 0.75 if use_case == "uc2_pmi_removal" else 0.80


def uc2_ltv_straddles_threshold(ltv_ratio: float) -> bool:
    return 0.73 <= ltv_ratio <= 0.77


def ltv_lars_factor(use_case: str, ltv_ratio: float) -> str | None:
    if use_case == "uc2_pmi_removal":
        if uc2_ltv_straddles_threshold(ltv_ratio):
            return "U2.1"
        if ltv_ratio > 0.77:
            return "B10"
        return None
    return "B10" if ltv_ratio > 0.80 else None


def b11_status_for_single_source() -> str:
    return "not_evaluated_single_source"

