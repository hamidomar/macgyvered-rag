import json
import base64
import os
import io
from pypdf import PdfReader
from openai import OpenAI
from src.config import OPENAI_EXTRACTION_MODEL

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-tests"))

EXTRACTION_PROMPTS = {
    "mortgage_statement": """
        Extract the following fields from this mortgage statement.
        Return ONLY a JSON object with no explanation.
        
        {
            "current_rate_percent": <number>,
            "loan_balance": <number>,
            "servicer_name": "<string>",
            "loan_number": "<string>",
            "gse_owner": "<fnma | fhlmc | unknown>",
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
            reader = PdfReader(io.BytesIO(file_bytes))
            text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
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
