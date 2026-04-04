import json
import base64
import os
import io
from pypdf import PdfReader
from openai import OpenAI
from src.config import OPENAI_EXTRACTION_MODEL

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-tests"))

SECONDARY_DOCUMENT_TYPES = ("paystub", "w2", "schedule_c")

EXTRACTION_PROMPTS = {
    "mortgage_statement": """
        Extract the following fields from this mortgage statement.
        Return ONLY a JSON object with no explanation.
        
        {
            "borrower_name": "<string or null>",
            "current_rate_percent": <number>,
            "loan_balance": <number>,
            "servicer_name": "<string>",
            "loan_number": "<string>",
            "gse_owner": "<fnma | unknown>",
            "monthly_pi": <number>,
            "monthly_pmi": <number or null>,
            "original_property_value": <number or null>
        }
    """,
    "paystub": """
        Extract the following fields from this paystub.
        Return ONLY a JSON object with no explanation.
        
        {
            "employer_name": "<string>",
            "gross_this_period": <number>,
            "pay_frequency": "<weekly | biweekly | semimonthly | monthly>",
            "ytd_gross": <number>,
            "pay_period_end_date": "<YYYY-MM-DD>"
        }
    """,
    "w2": """
        Extract the following fields from this W-2 form.
        Return ONLY a JSON object with no explanation.
        
        {
            "employer_name": "<string>",
            "wages_box1": <number>,
            "tax_year": <number>
        }
    """,
    "schedule_c": """
        Extract the following fields from this Schedule C (Form 1040).
        Return ONLY a JSON object with no explanation.
        
        {
            "tax_year": <number>,
            "net_profit_loss": <number>,
            "depreciation": <number>,
            "business_name": "<string>"
        }
    """
}


def _extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join(page.extract_text() for page in reader.pages if page.extract_text())


def _parse_doc_type(raw_content: str) -> str | None:
    cleaned = raw_content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip().strip('"').strip("'")

    if cleaned in SECONDARY_DOCUMENT_TYPES:
        return cleaned

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        doc_type = payload.get("doc_type")
        if doc_type in SECONDARY_DOCUMENT_TYPES:
            return doc_type
    return None


def _infer_supporting_doc_type_with_model(
    file_bytes: bytes,
    mime_type: str,
    document_text: str = "",
) -> str | None:
    prompt = (
        "Classify this document as exactly one of: paystub, w2, schedule_c. "
        "Return only JSON like {\"doc_type\": \"paystub\"}."
    )
    content_blocks = [{"type": "text", "text": prompt}]

    if document_text:
        content_blocks.append({"type": "text", "text": f"\n--- DOCUMENT TEXT ---\n{document_text}"})
    elif "pdf" not in mime_type.lower():
        base64_data = base64.b64encode(file_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{base64_data}"
        content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})

    try:
        response = client.chat.completions.create(
            model=OPENAI_EXTRACTION_MODEL,
            messages=[{"role": "user", "content": content_blocks}],
            max_tokens=100,
            temperature=0,
        )
        raw_content = response.choices[0].message.content.strip()
        return _parse_doc_type(raw_content)
    except Exception:
        return None


def infer_supporting_doc_type(
    file_bytes: bytes,
    filename: str | None = None,
    mime_type: str = "application/pdf",
) -> str:
    """
    Infer the supporting document type for uploads after the initial mortgage statement.
    """
    normalized_filename = (filename or "").lower()
    filename_hints = (
        ("schedule_c", ("schedule_c", "schedule-c", "schedule c", "sch c")),
        ("w2", ("w2", "w-2")),
        ("paystub", ("paystub", "pay-stub", "pay stub", "earnings")),
    )
    for doc_type, hints in filename_hints:
        if any(hint in normalized_filename for hint in hints):
            return doc_type

    document_text = ""
    if "pdf" in mime_type.lower():
        try:
            document_text = _extract_pdf_text(file_bytes)
        except Exception:
            document_text = ""

    normalized_text = " ".join(document_text.upper().split())
    if "SCHEDULE C" in normalized_text or "PROFIT OR LOSS FROM BUSINESS" in normalized_text:
        return "schedule_c"
    if (
        "FORM W-2" in normalized_text
        or "WAGE AND TAX STATEMENT" in normalized_text
        or "WAGES, TIPS, OTHER COMPENSATION" in normalized_text
    ):
        return "w2"
    if any(
        marker in normalized_text
        for marker in (
            "PAY PERIOD",
            "EARNINGS STATEMENT",
            "GROSS PAY",
            "NET PAY",
            "YTD GROSS",
            "PAY DATE",
        )
    ):
        return "paystub"

    inferred = _infer_supporting_doc_type_with_model(file_bytes, mime_type, document_text=document_text)
    if inferred:
        return inferred

    raise ValueError(
        "Could not determine the supporting document type. "
        "Supported uploads are paystub, W-2, and Schedule C."
    )

def extract_document(file_bytes: bytes, doc_type: str, mime_type: str = "application/pdf") -> dict:
    """
    Send a document to OpenAI's multimodal endpoint for structured extraction.

    Args:
        file_bytes: raw bytes of the uploaded file
        doc_type: key into EXTRACTION_PROMPTS
        mime_type: MIME type of the file
    """
    if doc_type not in EXTRACTION_PROMPTS:
        raise ValueError(f"Unknown document type: {doc_type}")

    prompt = EXTRACTION_PROMPTS[doc_type]
    content_blocks = [{"type": "text", "text": prompt}]

    if "pdf" in mime_type.lower():
        try:
            text = _extract_pdf_text(file_bytes)
            print(f"DEBUG: Extracted PDF text for {doc_type}:\n{text[:500]}...") # Log start of text
            content_blocks.append({"type": "text", "text": f"\n--- PDF TEXT ---\n{text}"})
        except Exception as e:
            return {"extraction_warnings": [f"Failed to read PDF text: {str(e)}"]}
    else:
        # Assume it's an image, pass via vision endpoint
        base64_data = base64.b64encode(file_bytes).decode('utf-8')
        data_url = f"data:{mime_type};base64,{base64_data}"
        content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})

    try:
        response = client.chat.completions.create(
            model=OPENAI_EXTRACTION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": content_blocks
                }
            ],
            max_tokens=500,
            temperature=0,
        )
        
        raw_content = response.choices[0].message.content.strip()
        print(f"DEBUG: Raw LLM response for {doc_type}: {raw_content}") # Log raw response
        
        # Clean up markdown formatting if present
        if raw_content.startswith("```json"):
            raw_content = raw_content[7:]
        if raw_content.startswith("```"):
            raw_content = raw_content[3:]
        if raw_content.endswith("```"):
            raw_content = raw_content[:-3]
            
        return json.loads(raw_content.strip())
        
    except json.JSONDecodeError:
        return {"extraction_warnings": ["Failed to parse JSON response"], "raw_response": raw_content}
    except Exception as e:
        return {"extraction_warnings": [f"Extraction failed: {str(e)}"]}
