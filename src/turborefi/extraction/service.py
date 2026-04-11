from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI
from pypdf import PdfReader

from turborefi.config import Settings, load_settings
from turborefi.extraction.normalizers import normalize_document_payload
from turborefi.extraction.prompts import DOCUMENT_TYPE_PROMPT, EXTRACTION_PROMPTS
from turborefi.schemas import MortgageStatementData, PaystubData, ScheduleCData, W2Data


SECONDARY_DOCUMENT_TYPES = ("paystub", "w2", "schedule_c")

SCHEMA_BY_DOC_TYPE = {
    "mortgage_statement": MortgageStatementData,
    "paystub": PaystubData,
    "w2": W2Data,
    "schedule_c": ScheduleCData,
}


class DocumentExtractionService:
    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.client = client or OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-tests"))

    @staticmethod
    def _extract_pdf_text(file_bytes: bytes) -> str:
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() for page in reader.pages if page.extract_text())

    @staticmethod
    def _clean_json_content(raw_content: str) -> str:
        cleaned = raw_content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    def validate_fixture_payload(self, doc_type: str, payload: dict[str, Any]):
        if doc_type not in SCHEMA_BY_DOC_TYPE:
            raise ValueError(f"Unsupported document type: {doc_type}")
        normalized = normalize_document_payload(payload)
        schema = SCHEMA_BY_DOC_TYPE[doc_type]
        return schema.model_validate(normalized)

    def _parse_doc_type(self, raw_content: str) -> str | None:
        cleaned = self._clean_json_content(raw_content).strip().strip('"').strip("'")

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
        self,
        file_bytes: bytes,
        mime_type: str,
        document_text: str = "",
    ) -> str | None:
        content_blocks = [{"type": "text", "text": DOCUMENT_TYPE_PROMPT}]

        if document_text:
            content_blocks.append({"type": "text", "text": f"\n--- DOCUMENT TEXT ---\n{document_text}"})
        elif "pdf" not in mime_type.lower():
            base64_data = base64.b64encode(file_bytes).decode("utf-8")
            data_url = f"data:{mime_type};base64,{base64_data}"
            content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})

        try:
            response = self.client.chat.completions.create(
                model=self.settings.openai_model_extraction,
                messages=[{"role": "user", "content": content_blocks}],
                max_tokens=100,
                temperature=0,
            )
            raw_content = response.choices[0].message.content.strip()
            return self._parse_doc_type(raw_content)
        except Exception:
            return None

    def infer_supporting_doc_type(
        self,
        file_bytes: bytes,
        *,
        filename: str | None = None,
        mime_type: str = "application/pdf",
    ) -> str:
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
                document_text = self._extract_pdf_text(file_bytes)
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

        inferred = self._infer_supporting_doc_type_with_model(
            file_bytes,
            mime_type,
            document_text=document_text,
        )
        if inferred:
            return inferred

        raise ValueError(
            "Could not determine the supporting document type. Supported uploads are paystub, W-2, and Schedule C."
        )

    def extract_bytes(
        self,
        doc_type: str,
        file_bytes: bytes,
        *,
        mime_type: str = "application/pdf",
    ):
        if doc_type not in EXTRACTION_PROMPTS:
            raise ValueError(f"Unsupported document type: {doc_type}")

        prompt = EXTRACTION_PROMPTS[doc_type]
        content_blocks = [{"type": "text", "text": prompt}]

        if "pdf" in mime_type.lower():
            text = self._extract_pdf_text(file_bytes)
            content_blocks.append({"type": "text", "text": f"\n--- PDF TEXT ---\n{text}"})
        else:
            base64_data = base64.b64encode(file_bytes).decode("utf-8")
            data_url = f"data:{mime_type};base64,{base64_data}"
            content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})

        response = self.client.chat.completions.create(
            model=self.settings.openai_model_extraction,
            messages=[{"role": "user", "content": content_blocks}],
            max_tokens=500,
            temperature=0,
        )

        raw_content = response.choices[0].message.content.strip()
        payload = json.loads(self._clean_json_content(raw_content))
        return self.validate_fixture_payload(doc_type, payload)

    def extract_file(
        self,
        doc_type: str,
        file_path: str,
        *,
        mime_type: str | None = None,
    ):
        path = Path(file_path)
        guessed_mime_type = mime_type or ("application/pdf" if path.suffix.lower() == ".pdf" else "image/png")
        file_bytes = path.read_bytes()
        return self.extract_bytes(doc_type, file_bytes, mime_type=guessed_mime_type)

    def extract_upload(
        self,
        *,
        file_bytes: bytes,
        filename: str | None,
        mime_type: str,
        doc_type: str | None = None,
        is_new_session: bool = False,
    ) -> tuple[str, Any]:
        effective_doc_type = doc_type
        if effective_doc_type is None:
            effective_doc_type = "mortgage_statement" if is_new_session else self.infer_supporting_doc_type(
                file_bytes,
                filename=filename,
                mime_type=mime_type,
            )

        extracted = self.extract_bytes(
            effective_doc_type,
            file_bytes,
            mime_type=mime_type,
        )
        return effective_doc_type, extracted
