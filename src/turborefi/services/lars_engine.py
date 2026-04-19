from __future__ import annotations

from typing import Any

from turborefi.rules.handoff_actions import action_for_factor
from turborefi.schemas import HandoffPackage, LarsEvent, LarsResult, SessionState
from turborefi.services.calculations.ltv import ltv_lars_factor


FACTOR_NAMES = {
    "B1": "FICO below 620",
    "B2": "FICO 620-679",
    "B3": "FICO unknown",
    "B4": "Uncertain factual answer",
    "B5": "Missing required document",
    "B6": "W2/paystub mismatch greater than 10%",
    "B7": "OCR confidence below 80%",
    "B8": "Employment under 2 years",
    "B9": "Employment gap",
    "B10": "LTV over threshold",
    "B12": "Condo/HOA",
    "B15": "DTI greater than 43%",
    "U1.1": "Variable income greater than 25% of base",
    "U1.2": "Variable income under 2-year history",
    "U2.1": "UC2 LTV straddles 75%",
    "U2.2": "PMI type unclear",
    "U2.3": "Second lien exists",
    "U2.4": "Purchase price unknown",
}

DEDUCTIONS = {
    "B1": 15,
    "B2": 5,
    "B3": 15,
    "B4": 15,
    "B5": 10,
    "B6": 10,
    "B7": 3,
    "B8": 8,
    "B9": 10,
    "B10": 15,
    "B12": 10,
    "B15": 10,
    "U1.1": 10,
    "U1.2": 10,
    "U2.1": 15,
    "U2.2": 10,
    "U2.3": 10,
    "U2.4": 10,
}


def _append_event(events: list[LarsEvent], score: int, code: str, data: dict[str, Any] | None = None) -> int:
    deduction = DEDUCTIONS[code]
    next_score = max(score - deduction, 0)
    events.append(
        LarsEvent(
            factor_code=code,
            factor_name=FACTOR_NAMES[code],
            deduction=deduction,
            data=data or {},
            score_after=next_score,
        )
    )
    return next_score


def _decision_for_score(score: int) -> str:
    if score == 100:
        return "AUTOMATED"
    if score >= 90:
        return "REFERRAL_A"
    if score >= 70:
        return "REFERRAL_B"
    return "REFERRAL_C"


def evaluate_lars(state: SessionState, *, score_missing_documents: bool = False) -> LarsResult:
    facts = state.borrower_facts
    outputs = state.calculated_outputs
    events: list[LarsEvent] = []
    score = 100

    if facts.fico_range == "below_620":
        score = _append_event(events, score, "B1", {"fico_range": facts.fico_range})
    elif facts.fico_range == "620_679":
        score = _append_event(events, score, "B2", {"fico_range": facts.fico_range})
    elif facts.fico_range == "unknown":
        score = _append_event(events, score, "B3", {"fico_range": facts.fico_range})
    elif facts.fico_uncertain and facts.fico_range:
        score = _append_event(events, score, "B4", {"field": "fico_range", "value": facts.fico_range})

    for field in facts.factual_uncertainties:
        if field in {"fico_range", "pmi_type", "purchase_price"}:
            continue
        score = _append_event(events, score, "B4", {"field": field})

    if score_missing_documents:
        for document in state.missing_documents:
            score = _append_event(events, score, "B5", {"document": document})

    diff_pct = outputs.get("w2_paystub_diff_pct")
    if diff_pct is not None and diff_pct > 0.10:
        score = _append_event(events, score, "B6", {"diff_pct": diff_pct})

    for confidence in outputs.get("ocr_confidences", []):
        if confidence is not None and confidence < 0.80:
            score = _append_event(events, score, "B7", {"ocr_confidence": confidence})

    variable_pct = outputs.get("variable_income_pct") or 0.0
    variable_income_present = variable_pct > 0
    u12_applied = False
    if variable_pct > 0.25:
        score = _append_event(events, score, "U1.1", {"variable_income_pct": variable_pct})

    if variable_income_present and facts.tenure_months is not None and facts.tenure_months < 24:
        score = _append_event(events, score, "U1.2", {"tenure_months": facts.tenure_months})
        u12_applied = True

    if facts.tenure_months is not None and facts.tenure_months < 24 and not u12_applied:
        score = _append_event(events, score, "B8", {"tenure_months": facts.tenure_months})

    if facts.employment_gap:
        score = _append_event(events, score, "B9")

    ltv_ratio = outputs.get("ltv")
    if ltv_ratio is None and state.received_mortgage is not None:
        ltv_ratio = state.received_mortgage.ltv
    if ltv_ratio is not None:
        ltv_factor = ltv_lars_factor(state.use_case, float(ltv_ratio))
        if ltv_factor:
            score = _append_event(events, score, ltv_factor, {"ltv": ltv_ratio})

    property_type = facts.property_type or (
        state.received_mortgage.property_type if state.received_mortgage is not None else None
    )
    if property_type == "condo":
        score = _append_event(events, score, "B12", {"property_type": property_type})

    dti = outputs.get("back_dti") or outputs.get("screening_dti")
    if dti is not None and dti > 0.43:
        score = _append_event(events, score, "B15", {"dti": dti})

    if state.use_case == "uc2_pmi_removal":
        pmi_type = facts.pmi_type
        if pmi_type == "unknown":
            score = _append_event(events, score, "U2.2", {"pmi_type": pmi_type or "unknown"})
        if facts.has_second_lien is True:
            score = _append_event(
                events,
                score,
                "U2.3",
                {"second_lien_balance": facts.second_lien_balance},
            )
        purchase_price = facts.purchase_price or (
            state.received_mortgage.purchase_price if state.received_mortgage is not None else None
        )
        if "purchase_price" in facts.factual_uncertainties or outputs.get("score_missing_purchase_price"):
            score = _append_event(events, score, "U2.4", {"purchase_price": purchase_price})

    decision = _decision_for_score(score)

    return LarsResult(
        starting_score=100,
        final_score=score,
        events=events,
        referral_triggered=decision != "AUTOMATED",
        decision=decision,
    )


def build_handoff_package(state: SessionState) -> HandoffPackage | None:
    if state.lars_result is None or not state.lars_result.referral_triggered:
        return None
    already_collected = []
    if state.received_mortgage is not None:
        for field in ("current_rate", "current_balance", "property_address", "pmi_monthly"):
            if getattr(state.received_mortgage, field) is not None:
                already_collected.append(field)
    for field in ("fico_range", "tenure_months", "property_type", "pmi_type"):
        if getattr(state.borrower_facts, field) is not None:
            already_collected.append(field)
    already_collected.extend(state.received_documents)

    factor_codes = [event.factor_code for event in state.lars_result.events]
    action_items = [action_for_factor(code) for code in factor_codes]

    return HandoffPackage(
        borrower_id=state.borrower_id_token or state.session_id,
        use_case=state.use_case,
        lars_score=state.lars_result.final_score,
        lars_events=state.lars_result.events,
        referral_reasons=[event.factor_name for event in state.lars_result.events],
        already_collected_do_not_reask=sorted(set(already_collected)),
        collected_data={
            "received_mortgage": (
                state.received_mortgage.model_dump(mode="json")
                if state.received_mortgage is not None
                else None
            ),
            "borrower_facts": state.borrower_facts.model_dump(mode="json"),
            "calculated_outputs": state.calculated_outputs,
        },
        missing_data=state.missing_documents,
        human_action_items=action_items,
        conversation_transcript=[message.model_dump(mode="json") for message in state.conversation],
    )
