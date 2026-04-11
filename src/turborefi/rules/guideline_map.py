EXPECTED_GUIDELINES = {
    "uc1_rate_term_refi": {
        "fnma": ["B3-3.1-01", "B3-3.2-01", "B2-1.3-01"],
        "fhlmc": ["5301.1", "5302.2"],
    },
    "uc2_pmi_removal": {
        "fnma": ["B3-3.1-01", "B3-3.2-01", "B2-1.3-01", "B4-1.3-04"],
        "fhlmc": ["5301.1", "5302.2"],
    },
    "uc3_se_rate_term": {
        "fnma": ["B3-3.3-01", "B3-3.3-03", "B2-1.3-01"],
        "fhlmc": ["5304.1", "5304.2"],
    },
}


GUIDELINE_FINDINGS = {
    "B3-3.1-01": "Income stability and continuity of employment reviewed.",
    "B3-3.2-01": "Employment documentation requirements reviewed for W-2 income.",
    "B2-1.3-01": "Rate-term refinance eligibility and transaction structure reviewed.",
    "B4-1.3-04": "Property value and mortgage insurance considerations reviewed.",
    "B3-3.3-01": "Self-employed documentation requirements reviewed.",
    "B3-3.3-03": "Self-employed income calculation treatment reviewed.",
    "5301.1": "Freddie Mac refinance underwriting baseline reviewed.",
    "5302.2": "Freddie Mac employment documentation requirements reviewed.",
    "5304.1": "Freddie Mac self-employed income documentation reviewed.",
    "5304.2": "Freddie Mac self-employed income analysis reviewed.",
}


USE_CASE_MAX_LTV = {
    "uc1_rate_term_refi": 97.0,
    "uc2_pmi_removal": 80.0,
    "uc3_se_rate_term": 97.0,
}
