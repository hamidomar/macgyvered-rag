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
}


DOCUMENT_TYPE_PROMPT = """
Classify this document as exactly one of: paystub, w2, schedule_c.
Return only JSON in the format:
{
  "doc_type": "<paystub | w2 | schedule_c>"
}
""".strip()
