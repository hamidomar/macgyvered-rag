from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from turborefi.agents.common import build_openai_chat
from turborefi.config import Settings
from turborefi.schemas import SessionState
from turborefi.services.intake_service import (
    _extract_annual_income,
    _extract_business_name,
    _extract_employer_name,
    _extract_employment_years,
    _extract_property_value,
    _extract_years_in_business,
    _normalize_text,
)


logger = logging.getLogger(__name__)


INTAKE_AGENT_INSTRUCTIONS = [
    "You resolve borrower-provided intake facts for TurboRefi.",
    "Use the update_borrower_fact tool for each intake field the borrower explicitly provides or corrects.",
    "Supported fields are: income_type, annual_income, employer_name, employment_years, business_name, years_in_business, current_property_value, target_rate_percent.",
    "If the borrower replies with only a number while current_property_value is pending, treat it as the current property value.",
    "If the borrower confirms the value already shown on the mortgage statement, call current_property_value with 'statement value'.",
    "Do not invent values or fill unsupported fields.",
    "Do not answer with underwriting guidance. Your job is only to resolve intake facts through the tool.",
]


FIELD_ALIASES = {
    "income_type": "income_type",
    "income": "income_type",
    "employment_type": "income_type",
    "annual_income": "annual_income",
    "income_amount": "annual_income",
    "salary": "annual_income",
    "employer": "employer_name",
    "employer_name": "employer_name",
    "company": "employer_name",
    "employment_years": "employment_years",
    "years_with_employer": "employment_years",
    "business_name": "business_name",
    "years_in_business": "years_in_business",
    "current_property_value": "current_property_value",
    "property_value": "current_property_value",
    "home_value": "current_property_value",
    "house_value": "current_property_value",
    "target_rate_percent": "target_rate_percent",
    "target_rate": "target_rate_percent",
}


@dataclass
class IntakeResolution:
    state: SessionState
    changed_fields: set[str] = field(default_factory=set)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)


class IntakeResolver(Protocol):
    def resolve(self, state: SessionState, message: str) -> IntakeResolution: ...


def _canonical_field_name(field_name: str) -> str | None:
    normalized = field_name.strip().lower().replace("-", "_").replace(" ", "_")
    return FIELD_ALIASES.get(normalized)


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


def _parse_years(raw_value: str) -> float | None:
    normalized = _normalize_text(raw_value)
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _normalize_income_type(raw_value: str) -> str | None:
    normalized = raw_value.strip().lower()
    if any(token in normalized for token in ("w2", "w-2", "salaried", "salary", "employee")):
        return "w2"
    if any(
        token in normalized
        for token in (
            "self employed",
            "self-employed",
            "self_employed",
            "freelance",
            "schedule c",
            "business owner",
        )
    ):
        return "self_employed"
    if "1099" in normalized or "gig" in normalized:
        return "gig_1099"
    if "rental" in normalized:
        return "rental"
    return None


def _normalize_name(raw_value: str) -> str | None:
    cleaned = _normalize_text(raw_value).strip(" ,.")
    if len(cleaned) < 2:
        return None
    return cleaned


def _property_value_statement_text(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    return "statement value" in normalized or normalized in {"use that", "use it", "use the statement"}


def validate_and_apply_borrower_fact(
    state: SessionState,
    *,
    field_name: str,
    value: str,
) -> tuple[dict[str, Any], str | None]:
    canonical_field = _canonical_field_name(field_name)
    if canonical_field is None:
        return (
            {
                "field_name": field_name,
                "status": "rejected",
                "stored": False,
                "message": f"Unsupported intake field '{field_name}'.",
            },
            None,
        )

    result: dict[str, Any] = {
        "field_name": canonical_field,
        "status": "rejected",
        "stored": False,
        "message": "",
    }

    normalized_value: Any = None
    clarification_question: str | None = None

    if canonical_field == "income_type":
        normalized_value = _normalize_income_type(value)
        if normalized_value is None:
            result["message"] = "Income type must be W-2, self-employed, 1099/gig, or rental."
            return result, None
        current_value = state.borrower_facts.declared_income_type
        state.borrower_facts.declared_income_type = normalized_value

    elif canonical_field == "annual_income":
        normalized_value = _parse_amount(value)
        if normalized_value is None or normalized_value <= 0:
            result["message"] = "Annual income must be a positive dollar amount."
            return result, None
        if normalized_value < 10_000 or normalized_value > 5_000_000:
            clarification_question = (
                f"I heard annual income as ${normalized_value:,.0f}. Can you confirm that amount?"
            )
            result["status"] = "needs_confirmation"
            result["message"] = clarification_question
            result["normalized_value"] = normalized_value
            return result, None
        current_value = state.borrower_facts.annual_income
        state.borrower_facts.annual_income = normalized_value

    elif canonical_field == "current_property_value":
        statement = state.documents.mortgage_statement
        if _property_value_statement_text(value):
            if statement is None or not statement.original_property_value:
                result["message"] = "There is no statement property value available to confirm."
                return result, None
            normalized_value = float(statement.original_property_value)
            source = "statement_confirmed"
        else:
            normalized_value = _parse_amount(value)
            if normalized_value is None or normalized_value <= 0:
                result["message"] = "Current property value must be a positive dollar amount."
                return result, None
            source = "borrower_chat"

        loan_balance = statement.loan_balance if statement is not None else None
        if loan_balance and normalized_value < loan_balance * 0.5:
            clarification_question = (
                f"I heard current property value as ${normalized_value:,.0f}, which is much lower than the current loan balance "
                f"of ${loan_balance:,.0f}. Did you mean a different amount?"
            )
            result["status"] = "needs_confirmation"
            result["message"] = clarification_question
            result["normalized_value"] = normalized_value
            return result, None
        if normalized_value > 20_000_000:
            clarification_question = (
                f"I heard current property value as ${normalized_value:,.0f}. Can you confirm that amount?"
            )
            result["status"] = "needs_confirmation"
            result["message"] = clarification_question
            result["normalized_value"] = normalized_value
            return result, None
        current_value = state.borrower_facts.current_property_value
        state.borrower_facts.current_property_value = normalized_value
        state.borrower_facts.property_value_source = source

    elif canonical_field == "employment_years":
        normalized_value = _parse_years(value)
        if normalized_value is None or normalized_value < 0:
            result["message"] = "Employment years must be zero or greater."
            return result, None
        if normalized_value > 60:
            clarification_question = (
                f"I heard time with the employer as {normalized_value:g} years. Can you confirm that?"
            )
            result["status"] = "needs_confirmation"
            result["message"] = clarification_question
            result["normalized_value"] = normalized_value
            return result, None
        current_value = state.borrower_facts.employment_years
        state.borrower_facts.employment_years = normalized_value

    elif canonical_field == "years_in_business":
        normalized_value = _parse_years(value)
        if normalized_value is None or normalized_value < 0:
            result["message"] = "Years in business must be zero or greater."
            return result, None
        if normalized_value > 60:
            clarification_question = (
                f"I heard years in business as {normalized_value:g}. Can you confirm that?"
            )
            result["status"] = "needs_confirmation"
            result["message"] = clarification_question
            result["normalized_value"] = normalized_value
            return result, None
        current_value = state.borrower_facts.years_in_business
        state.borrower_facts.years_in_business = int(normalized_value)

    elif canonical_field == "target_rate_percent":
        normalized_value = _parse_amount(value)
        if normalized_value is None or normalized_value <= 0:
            result["message"] = "Target rate must be a positive number."
            return result, None
        if normalized_value > 25:
            clarification_question = f"I heard target rate as {normalized_value:.2f}%. Can you confirm that?"
            result["status"] = "needs_confirmation"
            result["message"] = clarification_question
            result["normalized_value"] = normalized_value
            return result, None
        current_value = state.borrower_facts.target_rate_percent
        state.borrower_facts.target_rate_percent = normalized_value

    elif canonical_field == "employer_name":
        normalized_value = _normalize_name(value)
        if normalized_value is None:
            result["message"] = "Employer name must be a valid company name."
            return result, None
        current_value = state.borrower_facts.employer_name
        state.borrower_facts.employer_name = normalized_value

    elif canonical_field == "business_name":
        normalized_value = _normalize_name(value)
        if normalized_value is None:
            result["message"] = "Business name must be a valid company name."
            return result, None
        current_value = state.borrower_facts.business_name
        state.borrower_facts.business_name = normalized_value

    else:
        result["message"] = f"Field '{canonical_field}' is not supported yet."
        return result, None

    changed = current_value != normalized_value
    result.update(
        {
            "status": "accepted",
            "stored": changed,
            "normalized_value": normalized_value,
            "message": f"Stored {canonical_field}.",
        }
    )
    return result, canonical_field if changed else None


def _deterministic_candidates(state: SessionState, message: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    normalized = _normalize_text(message)

    property_value = _extract_property_value(message)
    if property_value is None and "current_property_value" in state.intake_pending:
        if re.fullmatch(r"\$?\s*[\d,.]+(?:\s*[km])?", normalized, flags=re.IGNORECASE):
            property_value = _parse_amount(normalized)
    if property_value is not None:
        candidates.append(("current_property_value", str(property_value)))

    annual_income = _extract_annual_income(message)
    if annual_income is not None:
        candidates.append(("annual_income", str(annual_income)))

    employer_name = _extract_employer_name(message)
    if employer_name is not None:
        candidates.append(("employer_name", employer_name))

    business_name = _extract_business_name(message)
    if business_name is not None:
        candidates.append(("business_name", business_name))

    employment_years = _extract_employment_years(message)
    if employment_years is not None:
        candidates.append(("employment_years", str(employment_years)))

    years_in_business = _extract_years_in_business(message)
    if years_in_business is not None:
        candidates.append(("years_in_business", str(years_in_business)))

    income_normalized = _normalize_income_type(message)
    if income_normalized is not None:
        candidates.append(("income_type", income_normalized))

    return candidates


class DeterministicIntakeResolver:
    def resolve(self, state: SessionState, message: str) -> IntakeResolution:
        working_state = state.model_copy(deep=True)
        resolution = IntakeResolution(state=working_state)

        for field_name, raw_value in _deterministic_candidates(state, message):
            result, changed_field = validate_and_apply_borrower_fact(
                working_state,
                field_name=field_name,
                value=raw_value,
            )
            resolution.tool_trace.append(
                {
                    "tool": "update_borrower_fact",
                    "arguments": {"field_name": field_name, "value": raw_value},
                    "result": result,
                }
            )
            if result["status"] == "needs_confirmation" and result["message"]:
                resolution.clarification_questions.append(result["message"])
            if changed_field is not None:
                resolution.changed_fields.add(changed_field)

        return resolution


class AgentIntakeResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve(self, state: SessionState, message: str) -> IntakeResolution:
        working_state = state.model_copy(deep=True)
        resolution = IntakeResolution(state=working_state)

        try:
            from agno.agent import Agent
            from agno.tools import tool
        except Exception:
            logger.exception("Agno is unavailable for intake resolution")
            return resolution

        @tool(show_result=True)
        def update_borrower_fact(field_name: str, value: str) -> dict[str, Any]:
            result, changed_field = validate_and_apply_borrower_fact(
                working_state,
                field_name=field_name,
                value=value,
            )
            resolution.tool_trace.append(
                {
                    "tool": "update_borrower_fact",
                    "arguments": {"field_name": field_name, "value": value},
                    "result": result,
                }
            )
            if result["status"] == "needs_confirmation" and result["message"]:
                resolution.clarification_questions.append(result["message"])
            if changed_field is not None:
                resolution.changed_fields.add(changed_field)
            return result

        agent_kwargs: dict[str, Any] = {
            "name": "TurboRefi Intake Resolver",
            "description": "Resolve borrower intake facts before underwriting.",
            "model": build_openai_chat(self.settings.openai_model_loa),
            "instructions": INTAKE_AGENT_INSTRUCTIONS,
            "tools": [update_borrower_fact],
            "markdown": True,
        }
        agent_params = inspect.signature(Agent).parameters
        if "session_state" in agent_params:
            agent_kwargs["session_state"] = working_state.model_dump(mode="json")
        if "add_session_state_to_context" in agent_params:
            agent_kwargs["add_session_state_to_context"] = True
        if "show_tool_calls" in agent_params:
            agent_kwargs["show_tool_calls"] = True

        agent = Agent(**agent_kwargs)
        prompt = (
            f"Borrower message:\n{message}\n\n"
            f"Pending intake fields: {', '.join(state.intake_pending) or 'none'}\n"
            f"Borrower facts: {working_state.borrower_facts.model_dump(mode='json')}\n"
            f"Mortgage statement: "
            f"{working_state.documents.mortgage_statement.model_dump(mode='json') if working_state.documents.mortgage_statement else None}"
        )
        try:
            agent.run(prompt)
        except Exception:
            logger.exception("Agent intake resolution failed")

        return resolution
