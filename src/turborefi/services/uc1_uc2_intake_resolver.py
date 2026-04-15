from __future__ import annotations

import inspect
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from turborefi.config import Settings
from turborefi.schemas import SessionState


logger = logging.getLogger(__name__)


UC1_UC2_AGENT_INSTRUCTIONS = [
    "You resolve borrower-provided facts for the TurboRefi UC1/UC2 intake flow.",
    "Use the resolve_uc1_uc2_fact tool for each fact the borrower explicitly provides or corrects.",
    "Supported fields are: fico_range, fico_uncertain, tenure_months, single_income_source, property_type, pmi_type, purchase_price, down_payment_amount, has_second_lien, second_lien_balance, employment_gap, factual_uncertainty.",
    "Use the expected field and existing borrower facts as context for short answers like yes, no, not sure, same, or just the first mortgage.",
    "Do not store borrower names, job titles, professions, race, gender, age, marital status, or any protected-class information.",
    "Do not infer unsupported underwriting decisions. Your job is only to resolve the structured facts through the tool.",
]


FIELD_ALIASES = {
    "fico": "fico_range",
    "credit_score": "fico_range",
    "credit_score_range": "fico_range",
    "fico_range": "fico_range",
    "fico_uncertain": "fico_uncertain",
    "tenure": "tenure_months",
    "employment_tenure": "tenure_months",
    "tenure_months": "tenure_months",
    "single_income": "single_income_source",
    "only_income": "single_income_source",
    "single_income_source": "single_income_source",
    "property": "property_type",
    "property_type": "property_type",
    "pmi": "pmi_type",
    "pmi_type": "pmi_type",
    "purchase": "purchase_price",
    "purchase_price": "purchase_price",
    "down_payment": "down_payment_amount",
    "down_payment_amount": "down_payment_amount",
    "second_lien": "has_second_lien",
    "second_mortgage": "has_second_lien",
    "has_second_lien": "has_second_lien",
    "heloc": "has_second_lien",
    "second_lien_balance": "second_lien_balance",
    "heloc_balance": "second_lien_balance",
    "employment_gap": "employment_gap",
    "factual_uncertainty": "factual_uncertainty",
    "factual_uncertainties": "factual_uncertainty",
    "uncertain_field": "factual_uncertainty",
}


FICO_RANGES = {"below_620", "620_679", "680_719", "720_759", "760_plus", "unknown"}
PROPERTY_TYPES = {"sfr", "townhome", "condo", "unknown"}
PMI_TYPES = {"borrower_paid", "lender_paid", "unknown"}
UNCERTAINTY_FIELDS = {
    "fico_range",
    "pmi_type",
    "purchase_price",
    "property_type",
    "tenure_months",
    "has_second_lien",
}
MIN_ACCEPT_CONFIDENCE = 0.55


@dataclass
class UC1UC2IntakeResolution:
    state: SessionState
    changed_fields: set[str] = field(default_factory=set)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)


class UC1UC2IntakeResolver(Protocol):
    def resolve(self, state: SessionState, message: str) -> UC1UC2IntakeResolution: ...


@dataclass(frozen=True)
class FactCandidate:
    field_name: str
    value: Any
    confidence: float = 1.0
    source: str = "deterministic_semantic_fallback"
    evidence: str | None = None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _canonical_field_name(field_name: str) -> str | None:
    normalized = field_name.strip().lower().replace("-", "_").replace(" ", "_")
    return FIELD_ALIASES.get(normalized)


def _parse_amount(raw_value: Any) -> float | None:
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    cleaned = str(raw_value).lower().replace("$", "").replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None
    multiplier = 1.0
    if cleaned.endswith("k"):
        multiplier = 1_000.0
        cleaned = cleaned[:-1]
    elif cleaned.endswith("m"):
        multiplier = 1_000_000.0
        cleaned = cleaned[:-1]
    try:
        return round(float(cleaned) * multiplier, 2)
    except ValueError:
        return None


def _amount_from_match(match: re.Match[str], index: int = 1) -> float | None:
    value = match.group(index)
    suffix = match.group(index + 1) if match.lastindex and match.lastindex >= index + 1 else ""
    return _parse_amount(f"{value}{suffix or ''}")


def _normalize_bool(raw_value: Any) -> bool | None:
    if isinstance(raw_value, bool):
        return raw_value
    normalized = _normalize_text(str(raw_value)).strip(".!?")
    truthy = {
        "yes",
        "yeah",
        "yep",
        "true",
        "correct",
        "that is correct",
        "i do",
        "i have",
        "we do",
        "we have",
    }
    falsy = {
        "no",
        "nope",
        "nah",
        "false",
        "none",
        "not any",
        "i do not",
        "i don't",
        "we do not",
        "we don't",
    }
    if normalized in truthy:
        return True
    if normalized in falsy:
        return False
    return None


def _normalize_fico(raw_value: Any) -> str | None:
    normalized = _normalize_text(str(raw_value))
    compact = normalized.replace("-", "_").replace(" ", "_")
    if compact in FICO_RANGES:
        return compact
    if any(token in normalized for token in ("unknown", "not sure", "do not know", "don't know", "no idea")):
        return "unknown"
    if "below 620" in normalized or "under 620" in normalized or "less than 620" in normalized:
        return "below_620"
    if "760" in normalized and any(token in normalized for token in ("plus", "above", "over", "or higher")):
        return "760_plus"
    if "high 700" in normalized or "upper 700" in normalized or "800" in normalized:
        return "760_plus"
    if "mid 700" in normalized or "720s" in normalized or "730s" in normalized or "740s" in normalized or "750s" in normalized:
        return "720_759"
    if "low 700" in normalized or "680s" in normalized or "690s" in normalized:
        return "680_719"
    if "620s" in normalized or "630s" in normalized or "640s" in normalized or "650s" in normalized or "660s" in normalized or "670s" in normalized:
        return "620_679"

    scores = [int(match.group(0)) for match in re.finditer(r"\b[3-8]\d\d\b", normalized)]
    scores = [score for score in scores if 300 <= score <= 850]
    if not scores:
        return None
    score = scores[0]
    if score < 620:
        return "below_620"
    if score < 680:
        return "620_679"
    if score < 720:
        return "680_719"
    if score < 760:
        return "720_759"
    return "760_plus"


def _normalize_property_type(raw_value: Any) -> str | None:
    normalized = _normalize_text(str(raw_value)).replace("-", " ")
    compact = normalized.replace(" ", "_")
    if compact in PROPERTY_TYPES:
        return compact
    if "condo" in normalized or "condominium" in normalized:
        return "condo"
    if any(token in normalized for token in ("townhome", "town house", "townhouse", "row home", "rowhouse")):
        return "townhome"
    if any(
        token in normalized
        for token in (
            "single family",
            "single family residence",
            "sfr",
            "sfh",
            "detached",
            "standalone",
            "stand alone",
            "free standing",
            "freestanding",
        )
    ):
        return "sfr"
    if normalized in {"house", "home", "a house", "a home"}:
        return "sfr"
    if "not sure" in normalized or "unknown" in normalized:
        return "unknown"
    return None


def _normalize_pmi_type(raw_value: Any) -> str | None:
    normalized = _normalize_text(str(raw_value)).replace("-", " ")
    compact = normalized.replace(" ", "_")
    if compact in PMI_TYPES:
        return compact
    if any(token in normalized for token in ("not sure", "unknown", "unclear", "do not know", "don't know", "no idea")):
        return "unknown"
    if any(
        token in normalized
        for token in (
            "borrower paid",
            "monthly",
            "separate",
            "line item",
            "i pay pmi",
            "pay it each month",
            "pay it monthly",
        )
    ):
        return "borrower_paid"
    if any(
        token in normalized
        for token in (
            "lender paid",
            "built into",
            "inside the rate",
            "in the rate",
            "higher rate",
            "lpmi",
        )
    ):
        return "lender_paid"
    return None


def _parse_tenure_months(raw_value: Any) -> int | None:
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(round(raw_value))
    normalized = _normalize_text(str(raw_value))
    years_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", normalized)
    months_match = re.search(r"(\d+)\s*months?", normalized)
    months = 0
    if years_match:
        months += int(round(float(years_match.group(1)) * 12))
    if months_match:
        months += int(months_match.group(1))
    if months:
        return months

    since_match = re.search(r"\b(?:since|started|hired)\s+(?:in\s+)?(?:[a-z]+\s+)?(20\d{2}|19\d{2})\b", normalized)
    if since_match:
        start_year = int(since_match.group(1))
        today = date.today()
        if 1900 <= start_year <= today.year:
            return max((today.year - start_year) * 12, 0)
    return None


def _result(
    field_name: str,
    *,
    status: str,
    stored: bool,
    message: str,
    normalized_value: Any = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "field_name": field_name,
        "status": status,
        "stored": stored,
        "message": message,
    }
    if normalized_value is not None:
        result["normalized_value"] = normalized_value
    if confidence is not None:
        result["confidence"] = confidence
    return result


def validate_and_apply_uc1_uc2_fact(
    state: SessionState,
    *,
    field_name: str,
    value: Any,
    confidence: float = 1.0,
) -> tuple[dict[str, Any], str | None]:
    canonical_field = _canonical_field_name(field_name)
    if canonical_field is None:
        return (
            _result(
                field_name,
                status="rejected",
                stored=False,
                message=f"Unsupported UC1/UC2 intake field '{field_name}'.",
                confidence=confidence,
            ),
            None,
        )
    if confidence < MIN_ACCEPT_CONFIDENCE:
        return (
            _result(
                canonical_field,
                status="needs_clarification",
                stored=False,
                message=f"Low-confidence value for {canonical_field}; ask a clarifying question.",
                normalized_value=value,
                confidence=confidence,
            ),
            None,
        )

    facts = state.borrower_facts
    normalized_value: Any

    if canonical_field == "fico_range":
        normalized_value = _normalize_fico(value)
        if normalized_value is None:
            return (
                _result(canonical_field, status="rejected", stored=False, message="FICO range was not recognized."),
                None,
            )
        current_value = facts.fico_range
        facts.fico_range = normalized_value

    elif canonical_field == "fico_uncertain":
        normalized_value = _normalize_bool(value)
        if normalized_value is None:
            return (
                _result(canonical_field, status="rejected", stored=False, message="FICO uncertainty must be true or false."),
                None,
            )
        current_value = facts.fico_uncertain
        facts.fico_uncertain = normalized_value

    elif canonical_field == "tenure_months":
        normalized_value = _parse_tenure_months(value)
        if normalized_value is None or normalized_value < 0:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Employment tenure was not recognized."),
                None,
            )
        if normalized_value > 720:
            return (
                _result(
                    canonical_field,
                    status="needs_clarification",
                    stored=False,
                    message=f"I heard employment tenure as {normalized_value} months. Can you confirm that?",
                    normalized_value=normalized_value,
                ),
                None,
            )
        current_value = facts.tenure_months
        facts.tenure_months = normalized_value
        facts.employment_years = round(normalized_value / 12, 2)

    elif canonical_field == "single_income_source":
        normalized_value = _normalize_bool(value)
        if normalized_value is None:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Single income source must be true or false."),
                None,
            )
        current_value = facts.single_income_source
        facts.single_income_source = normalized_value

    elif canonical_field == "property_type":
        normalized_value = _normalize_property_type(value)
        if normalized_value is None:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Property type was not recognized."),
                None,
            )
        current_value = facts.property_type
        facts.property_type = normalized_value

    elif canonical_field == "pmi_type":
        normalized_value = _normalize_pmi_type(value)
        if normalized_value is None:
            return (
                _result(canonical_field, status="rejected", stored=False, message="PMI type was not recognized."),
                None,
            )
        current_value = facts.pmi_type
        facts.pmi_type = normalized_value

    elif canonical_field == "purchase_price":
        normalized_value = _parse_amount(value)
        if normalized_value is None or normalized_value <= 0:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Purchase price must be a positive dollar amount."),
                None,
            )
        if normalized_value > 20_000_000:
            return (
                _result(
                    canonical_field,
                    status="needs_clarification",
                    stored=False,
                    message=f"I heard purchase price as ${normalized_value:,.0f}. Can you confirm that?",
                    normalized_value=normalized_value,
                ),
                None,
            )
        current_value = facts.purchase_price
        facts.purchase_price = normalized_value

    elif canonical_field == "down_payment_amount":
        normalized_value = _parse_amount(value)
        if normalized_value is None or normalized_value < 0:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Down payment must be a dollar amount."),
                None,
            )
        if facts.purchase_price and normalized_value > facts.purchase_price:
            return (
                _result(
                    canonical_field,
                    status="needs_clarification",
                    stored=False,
                    message=(
                        f"I heard down payment as ${normalized_value:,.0f}, which is above the purchase price. "
                        "Can you confirm that?"
                    ),
                    normalized_value=normalized_value,
                ),
                None,
            )
        current_value = facts.down_payment_amount
        facts.down_payment_amount = normalized_value

    elif canonical_field == "has_second_lien":
        normalized_value = _normalize_bool(value)
        if normalized_value is None:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Second-lien answer must be true or false."),
                None,
            )
        current_value = facts.has_second_lien
        facts.has_second_lien = normalized_value
        if normalized_value is False:
            facts.second_lien_balance = None

    elif canonical_field == "second_lien_balance":
        normalized_value = _parse_amount(value)
        if normalized_value is None or normalized_value < 0:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Second-lien balance must be a dollar amount."),
                None,
            )
        current_value = facts.second_lien_balance
        facts.second_lien_balance = normalized_value
        if normalized_value > 0 and facts.has_second_lien is not True:
            facts.has_second_lien = True

    elif canonical_field == "employment_gap":
        normalized_value = _normalize_bool(value)
        if normalized_value is None:
            return (
                _result(canonical_field, status="rejected", stored=False, message="Employment gap must be true or false."),
                None,
            )
        current_value = facts.employment_gap
        facts.employment_gap = normalized_value

    elif canonical_field == "factual_uncertainty":
        normalized_value = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized_value not in UNCERTAINTY_FIELDS:
            return (
                _result(canonical_field, status="rejected", stored=False, message=f"Unsupported uncertainty field '{value}'."),
                None,
            )
        changed = normalized_value not in facts.factual_uncertainties
        if changed:
            facts.factual_uncertainties.append(normalized_value)
        if normalized_value == "fico_range":
            # FICO uncertainty has its own dedicated LARS factor path.
            fico_uncertain_changed = facts.fico_uncertain is not True
            facts.fico_uncertain = True
            changed = changed or fico_uncertain_changed
        return (
            _result(
                canonical_field,
                status="accepted",
                stored=changed,
                message=f"Stored uncertainty for {normalized_value}.",
                normalized_value=normalized_value,
                confidence=confidence,
            ),
            (
                "fico_uncertain"
                if normalized_value == "fico_range" and facts.fico_uncertain
                else "factual_uncertainties"
            )
            if changed
            else None,
        )

    else:
        return (
            _result(canonical_field, status="rejected", stored=False, message=f"Field '{canonical_field}' is not supported."),
            None,
        )

    changed = current_value != normalized_value
    return (
        _result(
            canonical_field,
            status="accepted",
            stored=changed,
            message=f"Stored {canonical_field}.",
            normalized_value=normalized_value,
            confidence=confidence,
        ),
        canonical_field if changed else None,
    )


def expected_uc1_uc2_field(state: SessionState) -> str | None:
    facts = state.borrower_facts
    if state.unsupported_reason or state.handoff_package is not None:
        return None
    if state.use_case == "uc2_pmi_removal" and facts.pmi_type is None and not (
        state.received_mortgage and state.received_mortgage.pmi_monthly
    ):
        return "pmi_type"
    if facts.fico_range is None:
        return "fico_range"
    if facts.tenure_months is None:
        return "tenure_months"
    if facts.single_income_source is None:
        return "single_income_source"
    if facts.property_type is None:
        return "property_type"
    if state.use_case == "uc2_pmi_removal" and facts.pmi_type is None:
        return "pmi_type"
    if (
        state.use_case == "uc2_pmi_removal"
        and facts.purchase_price is None
        and "purchase_price" not in facts.factual_uncertainties
    ):
        return "purchase_price"
    if state.use_case == "uc2_pmi_removal" and facts.has_second_lien is None:
        return "has_second_lien"
    return None


def _short_answer_candidate(state: SessionState, message: str) -> list[FactCandidate]:
    value = _normalize_bool(message)
    if value is None:
        return []
    expected = expected_uc1_uc2_field(state)
    if expected == "single_income_source":
        return [FactCandidate("single_income_source", value, evidence=message)]
    if expected == "has_second_lien":
        return [FactCandidate("has_second_lien", value, evidence=message)]
    if expected == "pmi_type" and value is False:
        return [FactCandidate("pmi_type", "unknown", evidence=message)]
    if expected == "purchase_price" and value is False:
        return [FactCandidate("factual_uncertainty", "purchase_price", evidence=message)]
    return []


def _fico_candidates(message: str) -> list[FactCandidate]:
    normalized = _normalize_text(message)
    fico_range = _normalize_fico(message)
    candidates: list[FactCandidate] = []
    if fico_range is not None:
        candidates.append(FactCandidate("fico_range", fico_range, evidence=message))
    if any(
        token in normalized
        for token in (
            "maybe",
            "not sure",
            "not totally sure",
            "not entirely sure",
            "probably",
            "roughly",
            "estimate",
            "haven't checked",
            "havent checked",
            "checked in a while",
        )
    ) and fico_range not in {None, "unknown"}:
        candidates.append(FactCandidate("fico_uncertain", True, evidence=message))
    return candidates


def _tenure_candidates(message: str) -> list[FactCandidate]:
    normalized = _normalize_text(message)
    if not any(token in normalized for token in ("employer", "job", "company", "work", "since", "started", "hired", "years", "months")):
        return []
    months = _parse_tenure_months(message)
    if months is None:
        return []
    return [FactCandidate("tenure_months", months, evidence=message)]


def _income_source_candidates(state: SessionState, message: str) -> list[FactCandidate]:
    normalized = _normalize_text(message)
    false_markers = (
        "side job",
        "side gig",
        "side work",
        "second job",
        "rental",
        "rent income",
        "self employed",
        "self-employed",
        "1099",
        "freelance",
        "consulting",
        "contractor",
        "doordash",
        "door dash",
        "uber",
        "lyft",
        "airbnb",
        "also earn",
        "also have income",
        "additional income",
    )
    true_markers = (
        "only income",
        "only source",
        "sole income",
        "single source",
        "all i have",
        "all we have",
        "no other income",
        "no other earnings",
        "no side",
        "no rental",
        "no 1099",
        "no self employment",
        "no self-employment",
        "just my w2",
        "just my w-2",
        "just my job",
        "only payroll",
    )
    candidates: list[FactCandidate] = []
    if any(marker in normalized for marker in true_markers):
        candidates.append(FactCandidate("single_income_source", True, evidence=message))
    if any(marker in normalized for marker in false_markers):
        if any(f"no {marker}" in normalized for marker in false_markers):
            return candidates
        candidates.append(FactCandidate("single_income_source", False, evidence=message))
    if expected_uc1_uc2_field(state) == "single_income_source":
        if normalized in {"same job only", "my job only", "payroll only", "w2 only", "w-2 only"}:
            candidates.append(FactCandidate("single_income_source", True, evidence=message))
    return candidates


def _property_type_candidates(state: SessionState, message: str) -> list[FactCandidate]:
    normalized = _normalize_text(message).replace("-", " ")
    property_type = _normalize_property_type(message)
    if property_type is None:
        return []
    explicit = any(
        marker in normalized
        for marker in (
            "condo",
            "condominium",
            "townhome",
            "town house",
            "townhouse",
            "row home",
            "rowhouse",
            "single family",
            "sfr",
            "sfh",
            "detached",
            "standalone",
            "stand alone",
            "free standing",
            "freestanding",
        )
    )
    if explicit or expected_uc1_uc2_field(state) == "property_type":
        return [FactCandidate("property_type", property_type, evidence=message)]
    return []


def _pmi_candidates(message: str) -> list[FactCandidate]:
    pmi_type = _normalize_pmi_type(message)
    if pmi_type is None:
        return []
    return [FactCandidate("pmi_type", pmi_type, evidence=message)]


MONEY_PATTERN = r"\$?\s*([\d]+(?:,[\d]{3})*(?:\.\d+)?|[\d]+(?:\.\d+)?)\s*([kKmM]?)"


def _purchase_amount(message: str) -> float | None:
    patterns = [
        rf"(?:purchase(?: price)?|price|bought|paid)(?:\s+\w+){{0,4}}?\s+(?:for|was|at)?\s*{MONEY_PATTERN}",
        rf"{MONEY_PATTERN}\s+(?:purchase|purchase price|home|house|property)",
        rf"(?:on|for)\s+(?:a\s+)?{MONEY_PATTERN}\s+(?:purchase|home|house|property)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return _amount_from_match(match, 1)
    return None


def _down_payment_amount(message: str) -> float | None:
    patterns = [
        rf"(?:down payment|down|put down)(?:\s+was|\s+of)?\s*{MONEY_PATTERN}",
        rf"{MONEY_PATTERN}\s+(?:down|down payment)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return _amount_from_match(match, 1)
    return None


def _percent_down(message: str) -> float | None:
    normalized = _normalize_text(message)
    if "down" not in normalized:
        return None
    numeric_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+down", normalized)
    if numeric_match:
        return float(numeric_match.group(1)) / 100
    word_numbers = {
        "five": 0.05,
        "ten": 0.10,
        "fifteen": 0.15,
        "twenty": 0.20,
        "twenty five": 0.25,
        "twenty-five": 0.25,
        "thirty": 0.30,
    }
    for word, value in word_numbers.items():
        if f"{word} percent down" in normalized:
            return value
    return None


def _purchase_candidates(state: SessionState, message: str) -> list[FactCandidate]:
    normalized = _normalize_text(message)
    candidates: list[FactCandidate] = []
    purchase_price = _purchase_amount(message)
    down_payment = _down_payment_amount(message)
    percent_down = _percent_down(message)

    if purchase_price is None and expected_uc1_uc2_field(state) == "purchase_price":
        money_matches = list(re.finditer(MONEY_PATTERN, message, flags=re.IGNORECASE))
        if len(money_matches) >= 1:
            purchase_price = _amount_from_match(money_matches[0], 1)
        if len(money_matches) >= 2 and down_payment is None:
            down_payment = _amount_from_match(money_matches[1], 1)

    if purchase_price is not None:
        candidates.append(FactCandidate("purchase_price", purchase_price, evidence=message))
    if down_payment is None and percent_down is not None:
        base_price = purchase_price or state.borrower_facts.purchase_price
        if base_price is not None:
            down_payment = round(base_price * percent_down, 2)
    if down_payment is not None:
        candidates.append(FactCandidate("down_payment_amount", down_payment, evidence=message))

    if any(token in normalized for token in ("not sure", "do not know", "don't know", "no idea")) and any(
        token in normalized for token in ("purchase", "bought", "paid", "down")
    ):
        candidates.append(FactCandidate("factual_uncertainty", "purchase_price", evidence=message))
    return candidates


def _second_lien_candidates(message: str) -> list[FactCandidate]:
    normalized = _normalize_text(message)
    lien_markers = (
        "heloc",
        "home equity",
        "line of credit",
        "second mortgage",
        "second lien",
        "second loan",
        "junior lien",
    )
    no_lien_markers = (
        "no heloc",
        "no home equity",
        "no line of credit",
        "no second mortgage",
        "no second lien",
        "no second loan",
        "not have a heloc",
        "don't have a heloc",
        "do not have a heloc",
        "just the first mortgage",
        "only the first mortgage",
        "only one mortgage",
        "nothing else on the property",
    )
    candidates: list[FactCandidate] = []
    if any(marker in normalized for marker in no_lien_markers):
        candidates.append(FactCandidate("has_second_lien", False, evidence=message))
        return candidates
    if any(marker in normalized for marker in lien_markers):
        candidates.append(FactCandidate("has_second_lien", True, evidence=message))
        balance_match = re.search(
            rf"(?:heloc|home equity|line of credit|second mortgage|second lien|second loan)(?:\s+balance)?(?:\s+is|\s+of|\s+for|\s+around|\s+about)?\s*{MONEY_PATTERN}",
            message,
            flags=re.IGNORECASE,
        )
        if balance_match:
            balance = _amount_from_match(balance_match, 1)
            if balance is not None:
                candidates.append(FactCandidate("second_lien_balance", balance, evidence=message))
    return candidates


def _employment_gap_candidates(message: str) -> list[FactCandidate]:
    normalized = _normalize_text(message)
    if any(marker in normalized for marker in ("employment gap", "gap in employment", "laid off", "unemployed for")):
        if any(marker in normalized for marker in ("no employment gap", "no gap", "not laid off")):
            return [FactCandidate("employment_gap", False, evidence=message)]
        return [FactCandidate("employment_gap", True, evidence=message)]
    return []


def _semantic_candidates(state: SessionState, message: str) -> list[FactCandidate]:
    candidates: list[FactCandidate] = []
    candidates.extend(_short_answer_candidate(state, message))
    if candidates:
        return candidates
    candidates.extend(_fico_candidates(message))
    candidates.extend(_tenure_candidates(message))
    candidates.extend(_income_source_candidates(state, message))
    candidates.extend(_property_type_candidates(state, message))
    candidates.extend(_pmi_candidates(message))
    candidates.extend(_purchase_candidates(state, message))
    candidates.extend(_second_lien_candidates(message))
    candidates.extend(_employment_gap_candidates(message))

    deduped: dict[tuple[str, str], FactCandidate] = {}
    order: list[tuple[str, str]] = []
    for candidate in candidates:
        key = (
            candidate.field_name,
            str(candidate.value) if candidate.field_name == "factual_uncertainty" else "",
        )
        if key not in deduped:
            order.append(key)
        deduped[key] = candidate
    return [deduped[key] for key in order]


def _append_candidate_trace(
    resolution: UC1UC2IntakeResolution,
    candidate: FactCandidate,
    result: dict[str, Any],
) -> None:
    resolution.tool_trace.append(
        {
            "tool": "resolve_uc1_uc2_intake",
            "arguments": {
                "field_name": candidate.field_name,
                "value": candidate.value,
                "source": candidate.source,
                "confidence": candidate.confidence,
                "evidence": candidate.evidence,
            },
            "result": result,
        }
    )
    if result["status"] in {"needs_confirmation", "needs_clarification"} and result["message"]:
        resolution.clarification_questions.append(result["message"])


class DeterministicUC1UC2IntakeResolver:
    def resolve(self, state: SessionState, message: str) -> UC1UC2IntakeResolution:
        resolution = UC1UC2IntakeResolution(state=state)
        for candidate in _semantic_candidates(state, message):
            result, changed_field = validate_and_apply_uc1_uc2_fact(
                state,
                field_name=candidate.field_name,
                value=candidate.value,
                confidence=candidate.confidence,
            )
            _append_candidate_trace(resolution, candidate, result)
            if changed_field is not None:
                resolution.changed_fields.add(changed_field)
        return resolution


class AgenticUC1UC2IntakeResolver:
    def __init__(
        self,
        settings: Settings,
        *,
        fallback: UC1UC2IntakeResolver | None = None,
    ) -> None:
        self.settings = settings
        self.fallback = fallback or DeterministicUC1UC2IntakeResolver()

    def resolve(self, state: SessionState, message: str) -> UC1UC2IntakeResolution:
        if not os.getenv("OPENAI_API_KEY"):
            return self.fallback.resolve(state, message)

        resolution = UC1UC2IntakeResolution(state=state)
        try:
            from agno.agent import Agent
            from agno.tools import tool
            from turborefi.agents.common import build_openai_chat
        except Exception:
            logger.exception("Agno is unavailable for UC1/UC2 intake resolution")
            return self.fallback.resolve(state, message)

        @tool(show_result=True)
        def resolve_uc1_uc2_fact(
            field_name: str,
            value: Any,
            confidence: float = 1.0,
            evidence: str = "",
        ) -> dict[str, Any]:
            candidate = FactCandidate(
                field_name=field_name,
                value=value,
                confidence=confidence,
                source="agentic_structured_extractor",
                evidence=evidence or message,
            )
            result, changed_field = validate_and_apply_uc1_uc2_fact(
                state,
                field_name=field_name,
                value=value,
                confidence=confidence,
            )
            _append_candidate_trace(resolution, candidate, result)
            if changed_field is not None:
                resolution.changed_fields.add(changed_field)
            return result

        agent_kwargs: dict[str, Any] = {
            "name": "TurboRefi UC1/UC2 Intake Resolver",
            "description": "Resolve structured UC1/UC2 borrower facts from natural borrower replies.",
            "model": build_openai_chat(self.settings.openai_model_loa),
            "instructions": UC1_UC2_AGENT_INSTRUCTIONS,
            "tools": [resolve_uc1_uc2_fact],
            "markdown": False,
        }
        agent_params = inspect.signature(Agent).parameters
        if "session_state" in agent_params:
            agent_kwargs["session_state"] = state.model_dump(mode="json")
        if "add_session_state_to_context" in agent_params:
            agent_kwargs["add_session_state_to_context"] = True
        if "show_tool_calls" in agent_params:
            agent_kwargs["show_tool_calls"] = True

        agent = Agent(**agent_kwargs)
        prompt = (
            f"Borrower message:\n{message}\n\n"
            f"Expected next field: {expected_uc1_uc2_field(state) or 'none'}\n"
            f"Use case: {state.use_case}\n"
            f"Borrower facts: {state.borrower_facts.model_dump(mode='json')}\n"
            f"Received mortgage data: "
            f"{state.received_mortgage.model_dump(mode='json') if state.received_mortgage else None}\n"
            "Call resolve_uc1_uc2_fact for each explicit fact. Do not include narrative."
        )
        try:
            agent.run(prompt)
        except Exception:
            logger.exception("Agentic UC1/UC2 intake resolution failed")
            return self.fallback.resolve(state, message)

        if not resolution.tool_trace:
            return self.fallback.resolve(state, message)
        return resolution
