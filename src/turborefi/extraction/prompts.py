EXTRACTION_PROMPTS = {
    "mortgage_statement": """
Extract the following fields from this mortgage statement and return only JSON:
{
  "borrower_name": "<string or null>",
  "current_rate_percent": <number>,
  "loan_balance": <number>,
  "servicer_name": "<string>",
  "loan_number": "<string>",
  "gse_owner": "<fnma | fhlmc | unknown>",
  "monthly_pi": <number>,
  "monthly_pmi": <number or null>,
  "original_property_value": <number or null>
}
""".strip(),
    "paystub": """
Extract the following fields from this paystub and return only JSON:
{
  "employer_name": "<string>",
  "gross_this_period": <number>,
  "pay_frequency": "<weekly | biweekly | semimonthly | monthly>",
  "ytd_gross": <number>,
  "pay_period_end_date": "<YYYY-MM-DD>"
}
""".strip(),
    "w2": """
Extract the following fields from this W-2 and return only JSON:
{
  "employer_name": "<string>",
  "wages_box1": <number>,
  "tax_year": <number>
}
""".strip(),
    "schedule_c": """
Extract the following fields from this Schedule C and return only JSON:
{
  "tax_year": <number>,
  "net_profit_loss": <number>,
  "depreciation": <number>,
  "business_name": "<string>"
}
""".strip(),
    "identity": """
Extract the following fields from this identity document and return only JSON:
{
  "document_present": true,
  "document_type": "<driver_license | state_id | passport | other | null>",
  "borrower_name": "<string or null>",
  "issuing_state": "<string or null>",
  "id_last4": "<string or null>",
  "expiration_date": "<YYYY-MM-DD or null>"
}
""".strip(),
    "tax_bill": """
Extract the following fields from this property tax bill and return only JSON:
{
  "document_present": true,
  "tax_bill_annual": <number or null>,
  "tax_year": <number or null>,
  "property_address": "<string or null>",
  "parcel_number": "<string or null>"
}
""".strip(),
    "insurance": """
Extract the following fields from this homeowners insurance declarations page and return only JSON:
{
  "document_present": true,
  "insurance_annual": <number or null>,
  "carrier_name": "<string or null>",
  "policy_number_last4": "<string or null>",
  "effective_date": "<YYYY-MM-DD or null>"
}
""".strip(),
    "pmi_statement": """
Extract the following fields from this mortgage insurance document and return only JSON:
{
  "document_present": true,
  "pmi_monthly": <number or null>,
  "pmi_type": "<borrower_paid | lender_paid | unknown | null>",
  "servicer_name": "<string or null>"
}
""".strip(),
    "closing_disclosure": """
Extract the following fields from this closing disclosure and return only JSON:
{
  "document_present": true,
  "closing_date": "<YYYY-MM-DD or null>",
  "loan_amount": <number or null>,
  "cash_to_close": <number or null>,
  "borrower_name": "<string or null>"
}
""".strip(),
}


DOCUMENT_TYPE_PROMPT = """
Classify this document as exactly one of: paystub, w2, schedule_c, identity, tax_bill, insurance, pmi_statement, closing_disclosure, unknown.
If the document content is insufficient or it does not match one of the supported types, return unknown.
Return only JSON in the format:
{
  "doc_type": "<paystub | w2 | schedule_c | identity | tax_bill | insurance | pmi_statement | closing_disclosure | unknown>"
}
""".strip()
