from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI
import pdfplumber
from pypdf import PdfReader

from turborefi.config import Settings, load_settings
from turborefi.extraction.normalizers import normalize_document_payload
from turborefi.extraction.prompts import DOCUMENT_TYPE_PROMPT, EXTRACTION_PROMPTS
from turborefi.schemas import (
    ClosingDisclosureData,
    IdentityDocumentData,
    InsuranceDeclarationData,
    MortgageStatementData,
    PaystubData,
    PmiStatementData,
    ScheduleCData,
    TaxBillData,
    W2Data,
)

SECONDARY_DOCUMENT_TYPES = (
    "paystub",
    "w2",
    "schedule_c",
    "identity",
    "tax_bill",
    "insurance",
    "pmi_statement",
    "closing_disclosure",
)

SCHEMA_BY_DOC_TYPE = {
    "mortgage_statement": MortgageStatementData,
    "paystub": PaystubData,
    "w2": W2Data,
    "schedule_c": ScheduleCData,
    "identity": IdentityDocumentData,
    "tax_bill": TaxBillData,
    "insurance": InsuranceDeclarationData,
    "pmi_statement": PmiStatementData,
    "closing_disclosure": ClosingDisclosureData,
}


class UnsupportedDocumentError(ValueError):
    pass


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
    def _pdf_page_images(file_bytes: bytes, *, max_pages: int = 2) -> list[str]:
        images: list[str] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages[:max_pages]:
                image = page.to_image(resolution=144)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                images.append(base64.b64encode(buffer.getvalue()).decode("utf-8"))
        return images

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

    @staticmethod
    def _text_block(text: str) -> dict[str, Any]:
        return {"type": "text", "text": text}

    @staticmethod
    def _image_block(data_url: str) -> dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": data_url}}

    def _parse_doc_type(self, raw_content: str) -> str | None:
        cleaned = self._clean_json_content(raw_content).strip().strip('"').strip("'")

        if cleaned in SECONDARY_DOCUMENT_TYPES:
            return cleaned
        if cleaned == "unknown":
            return "unknown"

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

        if isinstance(payload, dict):
            doc_type = payload.get("doc_type")
            if doc_type in SECONDARY_DOCUMENT_TYPES or doc_type == "unknown":
                return doc_type
        return None

    def _build_content_blocks(
        self,
        *,
        prompt: str,
        file_bytes: bytes,
        mime_type: str,
        filename: str | None = None,
        document_text: str = "",
    ) -> list[dict[str, Any]]:
        content_blocks = [self._text_block(prompt)]
        if filename:
            content_blocks.append(self._text_block(f"Filename: {filename}"))
        if document_text:
            label = "PDF TEXT" if "pdf" in mime_type.lower() else "DOCUMENT TEXT"
            content_blocks.append(self._text_block(f"\n--- {label} ---\n{document_text}"))
            return content_blocks

        if "pdf" in mime_type.lower():
            try:
                for encoded_image in self._pdf_page_images(file_bytes):
                    content_blocks.append(self._image_block(f"data:image/png;base64,{encoded_image}"))
            except Exception:
                pass
            return content_blocks

        base64_data = base64.b64encode(file_bytes).decode("utf-8")
        content_blocks.append(self._image_block(f"data:{mime_type};base64,{base64_data}"))
        return content_blocks

    @staticmethod
    def _normalized_upper(document_text: str) -> str:
        return " ".join(document_text.upper().split())

    @staticmethod
    def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)

    def _filename_hint(self, filename: str | None) -> str | None:
        normalized_filename = (filename or "").lower()
        filename_hints = (
            ("schedule_c", ("schedule_c", "schedule-c", "schedule c", "sch c")),
            ("w2", ("w2", "w-2")),
            ("paystub", ("paystub", "pay-stub", "pay stub", "earnings")),
            ("identity", ("driver", "license", "state id", "identity", "passport", "government id")),
            ("tax_bill", ("tax bill", "property tax", "taxes", "county tax")),
            ("insurance", ("insurance", "declaration", "declarations", "dec page", "homeowners")),
            ("pmi_statement", ("pmi", "mortgage insurance", "mip")),
            ("closing_disclosure", ("closing disclosure", "closing-disclosure", "cash to close")),
        )
        for doc_type, hints in filename_hints:
            if any(hint in normalized_filename for hint in hints):
                return doc_type
        return None

    def _text_hint(self, normalized_text: str) -> str | None:
        if self._contains_any(
            normalized_text,
            ("SCHEDULE C", "PROFIT OR LOSS FROM BUSINESS"),
        ):
            return "schedule_c"
        if self._contains_any(
            normalized_text,
            ("FORM W-2", "WAGE AND TAX STATEMENT", "WAGES, TIPS, OTHER COMPENSATION"),
        ):
            return "w2"
        if self._contains_any(
            normalized_text,
            ("PAY PERIOD", "EARNINGS STATEMENT", "GROSS PAY", "NET PAY", "YTD GROSS", "PAY DATE"),
        ):
            return "paystub"
        if self._contains_any(
            normalized_text,
            ("DRIVER LICENSE", "DRIVER'S LICENSE", "IDENTIFICATION CARD", "DOB", "DATE OF BIRTH"),
        ):
            return "identity"
        if self._contains_any(
            normalized_text,
            ("PROPERTY TAX BILL", "TAX BILL", "ASSESSED VALUE", "PARCEL", "TAX YEAR"),
        ):
            return "tax_bill"
        if self._contains_any(
            normalized_text,
            ("DECLARATIONS", "NAMED INSURED", "COVERAGE A", "DWELLING", "POLICY NUMBER"),
        ):
            return "insurance"
        if self._contains_any(
            normalized_text,
            ("PRIVATE MORTGAGE INSURANCE", "MORTGAGE INSURANCE PREMIUM", "PMI", "MIP"),
        ):
            return "pmi_statement"
        if self._contains_any(
            normalized_text,
            ("CLOSING DISCLOSURE", "CALCULATION OF CASH TO CLOSE", "SUMMARIES OF TRANSACTIONS"),
        ):
            return "closing_disclosure"
        return None

    def _infer_supporting_doc_type_with_model(
        self,
        file_bytes: bytes,
        mime_type: str,
        *,
        filename: str | None = None,
        document_text: str = "",
    ) -> str | None:
        content_blocks = self._build_content_blocks(
            prompt=DOCUMENT_TYPE_PROMPT,
            file_bytes=file_bytes,
            mime_type=mime_type,
            filename=filename,
            document_text=document_text,
        )
        if len(content_blocks) == 1:
            return None

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
        filename_hint = self._filename_hint(filename)
        if filename_hint:
            return filename_hint

        document_text = ""
        if "pdf" in mime_type.lower():
            try:
                document_text = self._extract_pdf_text(file_bytes)
            except Exception:
                document_text = ""

        text_hint = self._text_hint(self._normalized_upper(document_text))
        if text_hint:
            return text_hint

        inferred = self._infer_supporting_doc_type_with_model(
            file_bytes,
            mime_type,
            filename=filename,
            document_text=document_text,
        )
        if inferred and inferred != "unknown":
            return inferred

        raise UnsupportedDocumentError(
            "Could not determine the supporting document type. Supported uploads are paystub, W-2, Schedule C, government ID, tax bill, insurance declaration, PMI statement, and closing disclosure."
        )

    def _fallback_payload_for_sparse_document(
        self,
        doc_type: str,
        *,
        filename: str | None = None,
        document_text: str = "",
    ) -> dict[str, Any] | None:
        if doc_type != "identity":
            return None
        lowered_filename = (filename or "").lower()
        normalized_text = self._normalized_upper(document_text)
        document_kind = "driver_license" if "driver" in lowered_filename or "DRIVER LICENSE" in normalized_text else None
        return {
            "document_present": True,
            "document_type": document_kind,
        }

    def extract_bytes(
        self,
        doc_type: str,
        file_bytes: bytes,
        *,
        mime_type: str = "application/pdf",
        filename: str | None = None,
    ):
        if doc_type not in EXTRACTION_PROMPTS:
            raise ValueError(f"Unsupported document type: {doc_type}")

        prompt = EXTRACTION_PROMPTS[doc_type]
        document_text = ""
        if "pdf" in mime_type.lower():
            try:
                document_text = self._extract_pdf_text(file_bytes)
            except Exception:
                document_text = ""

        fallback_payload = self._fallback_payload_for_sparse_document(
            doc_type,
            filename=filename,
            document_text=document_text,
        )
        if fallback_payload is not None and not document_text and "pdf" in mime_type.lower():
            return self.validate_fixture_payload(doc_type, fallback_payload)

        content_blocks = self._build_content_blocks(
            prompt=prompt,
            file_bytes=file_bytes,
            mime_type=mime_type,
            filename=filename,
            document_text=document_text,
        )
        if len(content_blocks) == 1:
            raise UnsupportedDocumentError(
                f"Could not read the uploaded {doc_type.replace('_', ' ')}. Upload a clearer file or provide the structured document JSON."
            )

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
        return self.extract_bytes(doc_type, file_bytes, mime_type=guessed_mime_type, filename=path.name)

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
            filename=filename,
        )
        return effective_doc_type, extracted
