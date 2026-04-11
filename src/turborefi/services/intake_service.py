from __future__ import annotations

import re
from dataclasses import dataclass

from turborefi.schemas import SessionState


INTAKE_FIELD_LABELS = {
    "income_type": "income type",
    "current_property_value": "current property value",
    "years_in_business": "years in business",
}

DOCUMENT_REQUEST_LABELS = {
    "paystubs": "two most recent paystubs",
    "w2s": "most recent W-2",
    "schedule_c": "two most recent Schedule C documents",
}

SELF_EMPLOYED_KEYWORDS = (
    "self employed",
    "self-employed",
    "freelance",
    "freelancer",
    "sole proprietor",
    "sole prop",
    "business owner",
    "my business",
    "schedule c",
)

W2_KEYWORDS = (
    "w2",
    "w-2",
    "salary",
    "salaried",
    "teacher",
    "employee",
    "employer",
    "paystub",
    "pay stub",
)


@dataclass
class IntakeUpdate:
    state: SessionState
    changed_fields: set[str]


def _normalize_text(message: str) -> str:
    return " ".join(message.strip().split())


def _lower_text(message: str) -> str:
    return _normalize_text(message).lower()


def _parse_amount(raw_value: str) -> float | None:
    cleaned = raw_value.lower().replace(",", "").replace("$", "").strip()
    multiplier = 1.0
    if cleaned.endswith("k"):
        multiplier = 1_000.0
        cleaned = cleaned[:-1].strip()
    elif cleaned.endswith("m"):
        multiplier = 1_000_000.0
        cleaned = cleaned[:-1].strip()

    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def _extract_first_amount(message: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        value = _parse_amount(match.group(1))
        if value is not None:
            return value
    return None


def _extract_property_value(message: str) -> float | None:
    patterns = [
        r"(?:worth|valued at|value is|value of|estimate(?:d)?(?: value)?(?: is)?|appraisal(?: is| came in at)?|zestimate(?: is| at)?|current value(?: is)?)\s+(?:about\s+|around\s+|approximately\s+|approx\.?\s+)?\$?\s*([\d,.]+(?:\s*[km])?)",
        r"\$?\s*([\d,.]+(?:\s*[km])?)\s+(?:for|as)\s+(?:my\s+)?(?:home|house|property)\s+value",
    ]
    value = _extract_first_amount(message, patterns)
    if value is not None:
        return value

    normalized = _normalize_text(message)
    if re.fullmatch(r"\$?\s*[\d,.]+(?:\s*[km])?", normalized, flags=re.IGNORECASE):
        return _parse_amount(normalized)

    return None


def _extract_annual_income(message: str) -> float | None:
    patterns = [
        r"(?:make|making|earn|earning|salary(?: is)?|base(?: salary)?(?: is)?|income(?: is)?)\s+(?:about\s+|around\s+|approximately\s+|approx\.?\s+)?\$?\s*([\d,.]+(?:\s*[km])?)",
        r"\$?\s*([\d,.]+(?:\s*[km])?)\s*(?:/|per\s+)?(?:year|yr|annually|annual)\b",
    ]
    return _extract_first_amount(message, patterns)


def _extract_years(message: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except ValueError:
            continue
    return None


def _extract_years_in_business(message: str) -> float | None:
    patterns = [
        r"(?:in business|operating|self-employed|self employed|freelancing|freelance)\s+for\s+(\d+(?:\.\d+)?)\s+years?",
        r"(\d+(?:\.\d+)?)\s+years?\s+(?:in business|operating|self-employed|self employed|freelancing|freelance)",
    ]
    return _extract_years(message, patterns)


def _extract_employment_years(message: str) -> float | None:
    patterns = [
        r"(?:been there|with (?:my )?employer for|same employer for|same school district for|at [A-Za-z0-9&.\- ]+ for)\s+(\d+(?:\.\d+)?)\s+years?",
        r"(\d+(?:\.\d+)?)\s+years?\s+(?:at|with)\s+[A-Za-z0-9&.\- ]+",
    ]
    return _extract_years(message, patterns)


def _extract_named_org(message: str, prefix_patterns: list[str]) -> str | None:
    for pattern in prefix_patterns:
        match = re.search(pattern, message)
        if not match:
            continue
        value = match.group(1).strip(" ,.")
        if value:
            return value
    return None


def _extract_employer_name(message: str) -> str | None:
    patterns = [
        r"\b(?:at|with)\s+([A-Z][A-Za-z0-9&.\-']*(?:\s+[A-Z][A-Za-z0-9&.\-']*){0,4})",
        r"\bemployer(?: is|:)\s+([A-Z][A-Za-z0-9&.\-']*(?:\s+[A-Z][A-Za-z0-9&.\-']*){0,4})",
    ]
    return _extract_named_org(message, patterns)


def _extract_business_name(message: str) -> str | None:
    patterns = [
        r"\b(?:business(?: is|:)?|company(?: is|:)?|called)\s+([A-Z][A-Za-z0-9&.\-']*(?:\s+[A-Z][A-Za-z0-9&.\-']*){0,5})",
    ]
    return _extract_named_org(message, patterns)


def detect_income_type(message: str) -> str | None:
    normalized = _lower_text(message)
    if any(keyword in normalized for keyword in SELF_EMPLOYED_KEYWORDS):
        return "self_employed"
    if any(keyword in normalized for keyword in W2_KEYWORDS):
        return "w2"
    if re.search(r"\bi work at\b|\bi've been there\b|\bsame employer\b", normalized):
        return "w2"
    return None


def needs_property_value_intake(state: SessionState) -> bool:
    statement = state.documents.mortgage_statement
    if statement is None:
        return False

    if state.use_case == "uc2_pmi_removal":
        return not state.borrower_facts.current_property_value

    if state.borrower_facts.current_property_value:
        return False

    statement_value = statement.original_property_value or 0
    return statement_value <= 0


def get_intake_pending(state: SessionState) -> list[str]:
    pending: list[str] = []
    if state.documents.mortgage_statement is None:
        return pending

    if state.income_type == "unknown":
        pending.append("income_type")
    if needs_property_value_intake(state):
        pending.append("current_property_value")
    if state.income_type == "self_employed" and not state.borrower_facts.years_in_business:
        pending.append("years_in_business")
    return pending


def intake_labels(pending_fields: list[str]) -> list[str]:
    return [INTAKE_FIELD_LABELS.get(field, field.replace("_", " ")) for field in pending_fields]


def missing_document_labels(missing_documents: list[str]) -> list[str]:
    return [DOCUMENT_REQUEST_LABELS.get(field, field.replace("_", " ")) for field in missing_documents]


def apply_borrower_message(state: SessionState, message: str) -> IntakeUpdate:
    next_state = state.model_copy(deep=True)
    changed_fields: set[str] = set()

    detected_income_type = detect_income_type(message)
    if detected_income_type and next_state.borrower_facts.declared_income_type != detected_income_type:
        next_state.borrower_facts.declared_income_type = detected_income_type
        changed_fields.add("income_type")

    property_value = _extract_property_value(message)
    if property_value and next_state.borrower_facts.current_property_value != property_value:
        next_state.borrower_facts.current_property_value = property_value
        next_state.borrower_facts.property_value_source = "borrower_stated"
        changed_fields.add("current_property_value")

    annual_income = _extract_annual_income(message)
    if annual_income and next_state.borrower_facts.annual_income != annual_income:
        next_state.borrower_facts.annual_income = annual_income
        changed_fields.add("annual_income")

    if next_state.borrower_facts.declared_income_type == "self_employed":
        business_name = _extract_business_name(message)
        if business_name and next_state.borrower_facts.business_name != business_name:
            next_state.borrower_facts.business_name = business_name
            changed_fields.add("business_name")

        years_in_business = _extract_years_in_business(message)
        if years_in_business and next_state.borrower_facts.years_in_business != years_in_business:
            next_state.borrower_facts.years_in_business = int(years_in_business)
            changed_fields.add("years_in_business")
    else:
        employer_name = _extract_employer_name(message)
        if employer_name and next_state.borrower_facts.employer_name != employer_name:
            next_state.borrower_facts.employer_name = employer_name
            changed_fields.add("employer_name")

        employment_years = _extract_employment_years(message)
        if employment_years and next_state.borrower_facts.employment_years != employment_years:
            next_state.borrower_facts.employment_years = employment_years
            changed_fields.add("employment_years")

    return IntakeUpdate(state=next_state, changed_fields=changed_fields)


def build_initial_intake_prompt(state: SessionState) -> str:
    statement = state.documents.mortgage_statement
    assert statement is not None

    rate = f"{statement.current_rate_percent:.2f}%"
    balance = f"${statement.loan_balance:,.0f}"
    statement_value = (
        f"${statement.original_property_value:,.0f}"
        if statement.original_property_value and statement.original_property_value > 0
        else None
    )
    if state.use_case == "uc2_pmi_removal":
        monthly_pmi = statement.monthly_pmi or 0.0
        value_prompt = (
            f"I also see a property value on the statement of {statement_value}. "
            "Tell me if you want me to use that as the working estimate or give me your current value instead. "
            if statement_value
            else "I also need your best estimate of the property's current value. "
        )
        return (
            f"I reviewed your mortgage statement. I see a current rate of {rate}, a balance of {balance}, "
            f"and about ${monthly_pmi:,.0f}/month in PMI. Before I request supporting documents, "
            "I need two quick items: confirm whether your income should be reviewed as W-2 or self-employed, "
            f"and provide the property-value detail. {value_prompt}"
            "If you're W-2, you can also include "
            "your employer and rough annual income. If you're self-employed, include your business name and years in business."
        )

    if statement_value:
        return (
            f"I reviewed your mortgage statement. I see a current rate of {rate}, a balance of {balance}, "
            f"and a property value on the statement of {statement_value}. Before I request supporting documents, "
            "confirm whether your income should be reviewed as W-2 or self-employed. "
            "If the property value on the statement is outdated, include your current estimate too. "
            "If you're W-2, you can also include your employer and rough annual income. "
            "If you're self-employed, include your business name and years in business."
        )

    return (
        f"I reviewed your mortgage statement. I see a current rate of {rate} and a balance of {balance}. "
        "Before I request supporting documents, confirm whether your income should be reviewed as W-2 or self-employed, "
        "and tell me your best estimate of the current property value. "
        "If you're W-2, you can also include your employer and rough annual income. "
        "If you're self-employed, include your business name and years in business."
    )


def build_guided_follow_up(
    state: SessionState,
    changed_fields: set[str] | None = None,
    clarification_questions: list[str] | None = None,
) -> str:
    changed_fields = changed_fields or set()
    clarification_questions = clarification_questions or []

    acknowledgements: list[str] = []
    if "income_type" in changed_fields:
        acknowledgements.append(
            "I marked the file as self-employed income."
            if state.income_type == "self_employed"
            else "I marked the file as W-2 income."
        )
    if "current_property_value" in changed_fields and state.borrower_facts.current_property_value:
        acknowledgements.append(
            f"I recorded a borrower-stated property value of ${state.borrower_facts.current_property_value:,.0f}."
        )
    if "years_in_business" in changed_fields and state.borrower_facts.years_in_business:
        acknowledgements.append(
            f"I noted {state.borrower_facts.years_in_business} years in business."
        )
    if "annual_income" in changed_fields and state.borrower_facts.annual_income:
        acknowledgements.append(
            f"I recorded annual income at ${state.borrower_facts.annual_income:,.0f}."
        )
    if "employer_name" in changed_fields and state.borrower_facts.employer_name:
        acknowledgements.append(
            f"I recorded the employer as {state.borrower_facts.employer_name}."
        )
    if "business_name" in changed_fields and state.borrower_facts.business_name:
        acknowledgements.append(
            f"I recorded the business as {state.borrower_facts.business_name}."
        )

    if clarification_questions:
        prefix = " ".join(acknowledgements).strip()
        if prefix:
            prefix += " "
        return f"{prefix}{' '.join(clarification_questions)}"

    if state.current_phase == "awaiting_intake":
        pending = set(state.intake_pending)
        requests: list[str] = []
        if "income_type" in pending:
            requests.append("tell me whether I should review this as W-2 or self-employed income")
        if "current_property_value" in pending:
            requests.append("share your best estimate of the property's current value")
        if "years_in_business" in pending:
            requests.append("tell me how many years the business has been operating")

        request_text = ", and ".join(requests)
        prefix = " ".join(acknowledgements).strip()
        if prefix:
            prefix += " "
        return (
            f"{prefix}Before I move to document collection, I still need you to {request_text}."
        )

    if state.current_phase == "awaiting_docs":
        missing_labels = missing_document_labels(state.missing_documents)
        docs_text = ", and ".join(missing_labels)
        prefix = " ".join(acknowledgements).strip()
        if prefix:
            prefix += " "

        if state.income_type == "self_employed":
            return (
                f"{prefix}I'm moving forward under the self-employed refinance path. "
                f"Please upload {docs_text}. Once those are in, I'll calculate the two-year average income and build the recommendation packet."
            )

        property_value_note = ""
        if state.borrower_facts.current_property_value:
            property_value_note = (
                f" I will use the borrower-stated value of ${state.borrower_facts.current_property_value:,.0f} "
                "as the working estimate until appraisal."
            )
        elif state.documents.mortgage_statement and state.documents.mortgage_statement.original_property_value:
            property_value_note = (
                f" I will use the statement value of ${state.documents.mortgage_statement.original_property_value:,.0f} "
                "as the working estimate until appraisal."
            )

        return (
            f"{prefix}I'm moving forward under the W-2 refinance path. "
            f"Please upload {docs_text} so I can verify income and finish the assessment.{property_value_note}"
        )

    return "I have what I need to continue the assessment."
