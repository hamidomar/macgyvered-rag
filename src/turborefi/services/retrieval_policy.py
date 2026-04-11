from __future__ import annotations

from dataclasses import dataclass

from turborefi.schemas import SessionState


@dataclass(frozen=True)
class TraversalBranchHint:
    path: tuple[str, ...]
    selection_terms: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class RetrievalFocus:
    key: str
    label: str
    branch_hints_by_gse: dict[str, tuple[TraversalBranchHint, ...]]
    fallback_queries_by_gse: dict[str, tuple[str, ...]]
    required: bool = True
    max_sections_per_gse: int = 1


def _branch(path: tuple[str, ...], *selection_terms: str, note: str = "") -> TraversalBranchHint:
    return TraversalBranchHint(path=path, selection_terms=selection_terms, note=note)


def _property_value_focus_required(session_state: SessionState) -> bool:
    return session_state.use_case == "uc2_pmi_removal"


def focus_definitions_for_state(session_state: SessionState) -> list[RetrievalFocus]:
    focuses = [
        RetrievalFocus(
            key="refinance_eligibility",
            label="rate-term refinance eligibility and transaction structure",
            branch_hints_by_gse={
                "fnma": (
                    _branch(
                        ("B", "B2", "B2-1", "B2-1.3"),
                        "limited cash-out refinance",
                        "refinance transactions",
                    ),
                ),
                "fhlmc": (
                    _branch(
                        ("guide_root", "Selling", "4000", "4300", "4301"),
                        "no cash-out refinance",
                        "refinance mortgages",
                        "borrower requirements for refinance",
                    ),
                ),
            },
            fallback_queries_by_gse={
                "fnma": ("limited cash-out refinance", "refinance transactions"),
                "fhlmc": ("no cash-out refinance", "refinance mortgages"),
            },
        )
    ]

    if session_state.income_type == "self_employed":
        focuses.extend(
            [
                RetrievalFocus(
                    key="self_employed_documentation",
                    label="documentation requirements for self-employed borrowers",
                    branch_hints_by_gse={
                        "fnma": (
                            _branch(
                                ("B", "B3", "B3-3", "B3-3.2"),
                                "self-employed borrower",
                                "documentation",
                                "underwriting factors",
                            ),
                        ),
                        "fhlmc": (
                            _branch(
                                ("guide_root", "Selling", "5000", "5300", "5304"),
                                "self-employed borrowers",
                                "documentation requirements",
                                "self-employed income",
                            ),
                        ),
                    },
                    fallback_queries_by_gse={
                        "fnma": ("self-employed borrower documentation", "self-employed borrower"),
                        "fhlmc": ("self-employed borrower documentation", "self-employed income"),
                    },
                ),
                RetrievalFocus(
                    key="self_employed_income_analysis",
                    label="income analysis for Schedule C or self-employed borrowers",
                    branch_hints_by_gse={
                        "fnma": (
                            _branch(
                                ("B", "B3", "B3-3", "B3-3.3"),
                                "schedule c",
                                "income or loss reported on irs form 1040 schedule c",
                                "income reported on irs form 1040",
                            ),
                        ),
                        "fhlmc": (
                            _branch(
                                ("guide_root", "Selling", "5000", "5300", "5304"),
                                "self-employed borrowers",
                                "tax data",
                                "self-employed income",
                            ),
                        ),
                    },
                    fallback_queries_by_gse={
                        "fnma": ("schedule c", "self-employed income"),
                        "fhlmc": ("self-employed income", "tax data self-employed"),
                    },
                    required=False,
                ),
            ]
        )
    else:
        focuses.extend(
            [
                RetrievalFocus(
                    key="income_stability",
                    label="income stability and continuity",
                    branch_hints_by_gse={
                        "fnma": (
                            _branch(
                                ("B", "B3", "B3-3", "B3-3.1"),
                                "general income information",
                                "income continuity",
                                "income stability",
                            ),
                        ),
                        "fhlmc": (
                            _branch(
                                ("guide_root", "Selling", "5000", "5300", "5301"),
                                "general requirements for all stable monthly income",
                                "stable monthly income",
                            ),
                            _branch(
                                ("guide_root", "Selling", "5000", "5300", "5303"),
                                "employed income",
                                "salary",
                                "hourly",
                            ),
                        ),
                    },
                    fallback_queries_by_gse={
                        "fnma": ("general income information", "income continuity"),
                        "fhlmc": ("stable monthly income", "employed income"),
                    },
                ),
                RetrievalFocus(
                    key="employment_documentation",
                    label="employment documentation for salaried or W-2 income",
                    branch_hints_by_gse={
                        "fnma": (
                            _branch(
                                ("B", "B3", "B3-3", "B3-3.1"),
                                "standards for employment documentation",
                                "employment documentation",
                                "verification of employment",
                            ),
                        ),
                        "fhlmc": (
                            _branch(
                                ("guide_root", "Selling", "5000", "5300", "5302"),
                                "documentation requirements",
                                "verification requirements",
                                "employed income documentation",
                            ),
                        ),
                    },
                    fallback_queries_by_gse={
                        "fnma": ("standards for employment documentation", "employment documentation"),
                        "fhlmc": ("employed income documentation", "verification requirements"),
                    },
                ),
            ]
        )

    if (
        _property_value_focus_required(session_state)
        or session_state.borrower_facts.current_property_value is not None
        or (
            session_state.documents.mortgage_statement is not None
            and session_state.documents.mortgage_statement.original_property_value is not None
        )
    ):
        focuses.append(
            RetrievalFocus(
                key="property_value_and_mi",
                label="property value, LTV, and mortgage insurance considerations",
                branch_hints_by_gse={
                    "fnma": (
                        _branch(
                            ("B", "B2", "B2-1", "B2-1.2"),
                            "loan-to-value ratios",
                            "ltv ratios",
                        ),
                        _branch(
                            ("B", "B4", "B4-1", "B4-1.4"),
                            "value acceptance",
                            "property data",
                            "property value",
                        ),
                    ),
                    "fhlmc": (
                        _branch(
                            ("guide_root", "Selling", "4000", "4200", "4203"),
                            "loan-to-value",
                            "ltv",
                            "loan amount",
                        ),
                        _branch(
                            ("guide_root", "Selling", "5000", "5600", "5602"),
                            "property valuation",
                            "automated collateral evaluation",
                            "ace",
                        ),
                    ),
                },
                fallback_queries_by_gse={
                    "fnma": ("ltv ratio", "value acceptance property data"),
                    "fhlmc": ("ltv ratio", "property valuation"),
                },
                required=_property_value_focus_required(session_state),
                max_sections_per_gse=2,
            )
        )

    return focuses


def required_focus_keys_for_state(session_state: SessionState) -> set[str]:
    return {focus.key for focus in focus_definitions_for_state(session_state) if focus.required}
