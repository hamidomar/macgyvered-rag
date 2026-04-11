from __future__ import annotations


REQUIRED_DOCUMENT_COUNTS = {
    "w2": {
        "mortgage_statement": 1,
        "paystubs": 2,
        "w2s": 1,
    },
    "self_employed": {
        "mortgage_statement": 1,
        "schedule_c": 2,
    },
    "gig_1099": {
        "mortgage_statement": 1,
        "tax_returns": 2,
        "1099s": 2,
    },
    "rental": {
        "mortgage_statement": 1,
        "schedule_e": 2,
    },
}


PENDING_PRE_CLOSING_ITEMS = {
    "w2": ["verbal_voe"],
    "self_employed": ["business_verification", "irs_transcript_validation"],
    "gig_1099": ["irs_transcript_validation"],
    "rental": ["appraisal"],
}


def get_document_status(income_type: str, document_counts: dict[str, int]) -> dict[str, list[str]]:
    requirements = REQUIRED_DOCUMENT_COUNTS.get(income_type, {})
    received: list[str] = []
    missing: list[str] = []

    for category, required_count in requirements.items():
        actual_count = document_counts.get(category, 0)
        if actual_count >= required_count:
            received.append(category)
        else:
            missing.append(category)

    not_required = [
        category
        for category in {"mortgage_statement", "paystubs", "w2s", "schedule_c", "tax_returns", "1099s", "schedule_e"}
        if category not in requirements
    ]
    return {
        "received": sorted(received),
        "missing": sorted(missing),
        "pending": PENDING_PRE_CLOSING_ITEMS.get(income_type, []),
        "not_required": sorted(not_required),
    }


def get_document_requirements(income_type: str) -> dict[str, list[str] | dict[str, int]]:
    return {
        "required_counts": REQUIRED_DOCUMENT_COUNTS.get(income_type, {}),
        "pending_pre_closing": PENDING_PRE_CLOSING_ITEMS.get(income_type, []),
    }
