from __future__ import annotations


HANDOFF_ACTIONS = {
    "B1": "Review credit path because borrower-reported FICO is below 620.",
    "B2": "Confirm credit and pricing impact for borrower-reported FICO 620-679.",
    "B3": "Obtain credit authorization or reliable borrower-reported FICO range.",
    "B4": "Verify the uncertain borrower-provided fact directly.",
    "B5": "Collect missing required document before final underwriting.",
    "B6": "Reconcile paystub annualization against W-2 income.",
    "B7": "Manually review the low-confidence OCR document fields.",
    "B8": "Review employment stability because tenure is under two years.",
    "B9": "Document and evaluate the employment gap.",
    "B10": "Review valuation and alternatives because LTV is over threshold.",
    "B12": "Review HOA dues, condo eligibility, and project requirements.",
    "B15": "Review debt-to-income ratio and liabilities.",
    "U1.1": "Document overtime, bonus, or commission history and stability.",
    "U1.2": "Determine whether short-history variable income can be used or must be excluded.",
    "U2.1": "Order or review valuation and evaluate PMI alternatives for borderline LTV.",
    "U2.2": "Confirm borrower-paid versus lender-paid PMI.",
    "U2.3": "Review CLTV and payoff, subordination, or consolidation options for the second lien.",
    "U2.4": "Obtain closing disclosure, HUD-1, or purchase documentation.",
}


def action_for_factor(factor_code: str) -> str:
    return HANDOFF_ACTIONS.get(factor_code, f"Review referral factor {factor_code}.")

