from __future__ import annotations


def front_dti(pitia_total: float, gmi: float) -> float:
    if gmi <= 0:
        raise ValueError("gmi must be greater than 0")
    return round(pitia_total / gmi, 4)


def back_dti(pitia_total: float, monthly_debts: float, gmi: float) -> float:
    if gmi <= 0:
        raise ValueError("gmi must be greater than 0")
    return round((pitia_total + monthly_debts) / gmi, 4)


def screening_dti(pitia_total: float, gmi: float, monthly_debts: float | None = None) -> float:
    if monthly_debts is None:
        return front_dti(pitia_total, gmi)
    return back_dti(pitia_total, monthly_debts, gmi)


def fnma_student_loan_payment(balance: float) -> float:
    return round(balance * 0.01, 2)


def fhlmc_student_loan_payment(balance: float) -> float:
    return round(balance * 0.005, 2)

