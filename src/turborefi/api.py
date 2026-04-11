from __future__ import annotations

import json
import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from turborefi.extraction.service import SECONDARY_DOCUMENT_TYPES
from turborefi.services.session_service import TurboRefiSessionService


logger = logging.getLogger(__name__)


class MessageRequest(BaseModel):
    message: str


def _status_income_docs(state) -> list[dict]:
    documents = []
    for paystub in state.documents.paystubs:
        payload = paystub.model_dump(mode="json")
        payload["document_type"] = "paystub"
        documents.append(payload)
    for w2 in state.documents.w2s:
        payload = w2.model_dump(mode="json")
        payload["document_type"] = "w2"
        documents.append(payload)
    for schedule_c in state.documents.schedule_c:
        payload = schedule_c.model_dump(mode="json")
        payload["document_type"] = "schedule_c"
        documents.append(payload)
    return documents


def _serialize_session_summary(state) -> dict:
    return {
        "session_id": state.session_id,
        "session_name": state.borrower_name or state.session_name or "Borrower",
        "created_at": int(state.created_at.timestamp()),
        "updated_at": int(state.updated_at.timestamp()),
        "current_phase": state.current_phase,
    }


def _serialize_session_detail(state) -> dict:
    return {
        **_serialize_session_summary(state),
        "intake_pending": state.intake_pending,
        "documents_received": state.received_documents,
        "documents_pending": state.pending_documents if state.loa_output is not None else state.missing_documents,
        "borrower_facts": state.borrower_facts.model_dump(mode="json"),
        "mortgage_data": (
            state.documents.mortgage_statement.model_dump(mode="json")
            if state.documents.mortgage_statement
            else None
        ),
        "income_docs": _status_income_docs(state),
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "created_at": int(message.created_at.timestamp()),
                "tool_calls": [
                    {
                        "role": "tool",
                        "content": (
                            trace.result
                            if isinstance(trace.result, str)
                            else str(trace.result)
                            if trace.result is None
                            else json.dumps(trace.result, indent=2)
                        ),
                        "tool_call_id": f"{trace.tool}-{index}",
                        "tool_name": trace.tool,
                        "tool_args": {
                            key: value if isinstance(value, str) else json.dumps(value)
                            for key, value in trace.arguments.items()
                        },
                        "tool_call_error": (
                            isinstance(trace.result, dict)
                            and trace.result.get("status") == "error"
                        ),
                        "metrics": {"time": 0},
                        "created_at": int(message.created_at.timestamp()),
                    }
                    for index, trace in enumerate(message.tool_trace)
                ],
            }
            for message in state.conversation
        ],
        "recommendation_packet": (
            state.loa_output.model_dump(mode="json")
            if state.loa_output is not None
            else None
        ),
        "verification_report": (
            state.verifier_output.model_dump(mode="json")
            if state.verifier_output is not None
            else None
        ),
    }


def build_api(service: TurboRefiSessionService) -> FastAPI:
    api = FastAPI(title="TurboRefi API")

    def ingest_document_bytes(
        file_bytes: bytes,
        *,
        mime_type: str,
        filename: str | None,
        session_id: str | None = None,
        doc_type: str | None = None,
    ) -> dict:
        logger.warning(
            "TurboRefi ingest start filename=%s mime_type=%s session_id=%r doc_type=%r bytes=%s",
            filename,
            mime_type,
            session_id,
            doc_type,
            len(file_bytes),
        )
        if session_id and not service.session_exists(session_id):
            # Stale frontend state should not block the first mortgage upload.
            if doc_type in (None, "mortgage_statement"):
                logger.warning(
                    "TurboRefi ingest clearing stale session_id=%r for initial mortgage upload",
                    session_id,
                )
                session_id = None
            else:
                logger.exception(
                    "TurboRefi ingest rejected unknown session_id=%r for supporting upload",
                    session_id,
                )
                raise HTTPException(status_code=404, detail="Session not found")

        if not session_id:
            if doc_type and doc_type != "mortgage_statement":
                raise HTTPException(status_code=400, detail="The first upload must be a mortgage statement")
            effective_doc_type, document = service.extraction_service.extract_upload(
                file_bytes=file_bytes,
                filename=filename,
                mime_type=mime_type,
                doc_type="mortgage_statement",
                is_new_session=True,
            )
            next_session_id, response_text, state, tool_trace = service.create_session_from_mortgage_data(
                document,
                session_name=filename,
            )
            return {
                "session_id": next_session_id,
                "response": response_text,
                "current_phase": state.current_phase,
                "document_type": effective_doc_type,
                "tool_trace": tool_trace,
            }

        if doc_type and doc_type not in SECONDARY_DOCUMENT_TYPES:
            raise HTTPException(status_code=400, detail="Supporting uploads must be paystub, w2, or schedule_c")

        effective_doc_type, document = service.extraction_service.extract_upload(
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
            doc_type=doc_type,
            is_new_session=False,
        )
        response_text, state, tool_trace = service.upload_secondary_document(
            session_id,
            effective_doc_type,
            document,
            filename=filename,
        )
        return {
            "session_id": session_id,
            "response": response_text,
            "current_phase": state.current_phase,
            "document_type": effective_doc_type,
            "tool_trace": tool_trace,
        }

    @api.post("/session")
    async def create_session(file: UploadFile = File(...)):
        try:
            file_bytes = await file.read()
            result = ingest_document_bytes(
                file_bytes,
                mime_type=file.content_type or "application/pdf",
                filename=file.filename,
            )
            return {
                "session_id": result["session_id"],
                "response": result["response"],
                "current_phase": result["current_phase"],
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @api.post("/session/{session_id}/upload")
    async def upload_document(session_id: str, doc_type: str = Form(...), file: UploadFile = File(...)):
        try:
            file_bytes = await file.read()
            result = ingest_document_bytes(
                file_bytes,
                mime_type=file.content_type or "application/pdf",
                filename=file.filename,
                session_id=session_id,
                doc_type=doc_type,
            )
            return {
                "response": result["response"],
                "current_phase": result["current_phase"],
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @api.post("/ingest")
    async def ingest_document(
        file: UploadFile = File(...),
        session_id: str | None = Form(None),
        doc_type: str | None = Form(None),
    ):
        try:
            file_bytes = await file.read()
            logger.warning(
                "TurboRefi ingest endpoint received filename=%s content_type=%s session_id=%r doc_type=%r",
                file.filename,
                file.content_type,
                session_id,
                doc_type,
            )
            return ingest_document_bytes(
                file_bytes,
                mime_type=file.content_type or "application/pdf",
                filename=file.filename,
                session_id=session_id,
                doc_type=doc_type,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("TurboRefi ingest endpoint failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @api.post("/session/{session_id}/message")
    async def send_message(session_id: str, request: MessageRequest):
        if not service.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            response_text, _state, tool_trace = service.send_message(session_id, request.message)
            return {"response": response_text, "tool_trace": tool_trace}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @api.get("/session/{session_id}/status")
    async def get_status(session_id: str):
        if not service.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        state = service.get_state(session_id)
        pending = state.pending_documents if state.loa_output is not None else state.missing_documents
        return {
            "current_phase": state.current_phase,
            "intake_pending": state.intake_pending,
            "documents_received": state.received_documents,
            "documents_pending": pending,
            "verification_status": (
                state.verifier_output.verification_status
                if state.verifier_output is not None
                else None
            ),
            "borrower_facts": state.borrower_facts.model_dump(mode="json"),
            "mortgage_data": (
                state.documents.mortgage_statement.model_dump(mode="json")
                if state.documents.mortgage_statement
                else None
            ),
            "income_docs": _status_income_docs(state),
        }

    @api.get("/refi/sessions")
    async def list_refi_sessions():
        data = [_serialize_session_summary(state) for state in service.list_states()]
        return {"data": data}

    @api.get("/refi/sessions/{session_id}")
    async def get_refi_session(session_id: str):
        if not service.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        state = service.get_state(session_id)
        return _serialize_session_detail(state)

    @api.delete("/refi/sessions/{session_id}")
    async def delete_refi_session(session_id: str):
        if not service.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        service.delete_session(session_id)
        return {"ok": True}

    @api.get("/session/{session_id}/result")
    async def get_result(session_id: str):
        if not service.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            packet = service.get_result(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return packet.model_dump(mode="json")

    @api.post("/session/{session_id}/verify")
    async def verify_session(session_id: str):
        if not service.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        try:
            report, _state = service.verify_session(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report.model_dump(mode="json")

    @api.get("/session/{session_id}/verification")
    async def get_verification(session_id: str):
        if not service.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        state = service.get_state(session_id)
        if state.verifier_output is None:
            raise HTTPException(status_code=400, detail="Verification report not generated yet")
        return state.verifier_output.model_dump(mode="json")

    return api
