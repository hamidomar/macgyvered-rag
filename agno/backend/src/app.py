import inspect

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

from src.agent import get_loa_agent
from src.config import PLAYGROUND_HOST, PLAYGROUND_PORT
from src.runtime import TurboRefiSessionService
from src.tools.extraction import (
    SECONDARY_DOCUMENT_TYPES,
    extract_document,
    infer_supporting_doc_type,
)

api = FastAPI(title="TurboRefi LOA V1 API (Agno)")
service = TurboRefiSessionService(get_loa_agent())


class MessageRequest(BaseModel):
    message: str


def _resolve_ingest_doc_type(
    file_bytes: bytes,
    mime_type: str,
    filename: str | None,
    session_id: str | None = None,
    doc_type: str | None = None,
) -> str:
    if not session_id:
        if doc_type and doc_type != "mortgage_statement":
            raise HTTPException(status_code=400, detail="The first upload must be a mortgage statement")
        return "mortgage_statement"

    if doc_type:
        if doc_type not in SECONDARY_DOCUMENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Supporting uploads must be paystub, w2, or schedule_c",
            )
        return doc_type

    try:
        return infer_supporting_doc_type(file_bytes, filename=filename, mime_type=mime_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _ingest_document_bytes(
    file_bytes: bytes,
    mime_type: str,
    filename: str | None,
    session_id: str | None = None,
    doc_type: str | None = None,
) -> dict:
    before_tool_count = 0
    if session_id and not service.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if session_id:
        before_tool_count = len(service.get_state(session_id).get("tool_call_history", []))

    effective_doc_type = _resolve_ingest_doc_type(
        file_bytes=file_bytes,
        mime_type=mime_type,
        filename=filename,
        session_id=session_id,
        doc_type=doc_type,
    )
    extracted_data = extract_document(file_bytes, effective_doc_type, mime_type)

    if not session_id:
        next_session_id, response_text, state = service.create_session_from_mortgage_data(extracted_data)
    else:
        next_session_id = session_id
        response_text, state = service.upload_secondary_document(session_id, effective_doc_type, extracted_data)

    return {
        "session_id": next_session_id,
        "response": response_text,
        "current_phase": state.get("current_phase", "greeting"),
        "document_type": effective_doc_type,
        "tool_trace": state.get("tool_call_history", [])[before_tool_count:],
    }


@api.post("/session")
async def create_session(file: UploadFile = File(...)):
    """
    Accepts a mortgage statement file upload.
    Extracts the document using OpenAI multimodal API,
    creates session state, runs the LOA, and returns the first response.
    """
    try:
        file_bytes = await file.read()
        result = _ingest_document_bytes(
            file_bytes=file_bytes,
            mime_type=file.content_type or "application/pdf",
            filename=file.filename,
            doc_type="mortgage_statement",
        )
        return {
            "session_id": result["session_id"],
            "response": result["response"],
            "current_phase": result["current_phase"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@api.post("/session/{session_id}/upload")
async def upload_document(session_id: str, doc_type: str = Form(...), file: UploadFile = File(...)):
    """
    Uploads secondary documents to an existing session and resumes the Agno agent.
    """
    try:
        file_bytes = await file.read()
        result = _ingest_document_bytes(
            file_bytes=file_bytes,
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
    """
    Unified document ingestion endpoint for the chat UI.
    Without a session_id, the file is treated as the initial mortgage statement.
    With a session_id, supporting document type is inferred unless explicitly provided.
    """
    try:
        file_bytes = await file.read()
        return _ingest_document_bytes(
            file_bytes=file_bytes,
            mime_type=file.content_type or "application/pdf",
            filename=file.filename,
            session_id=session_id,
            doc_type=doc_type,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@api.post("/session/{session_id}/message")
async def send_message(session_id: str, request: MessageRequest):
    """
    Sends a text message from the borrower and returns the LOA response.
    """
    if not service.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        response_text, _ = service.send_message(session_id, request.message)
        return {"response": response_text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@api.get("/session/{session_id}/status")
async def get_status(session_id: str):
    """
    Returns current phase, docs received/pending, and extracted structured data.
    """
    if not service.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    state = service.get_state(session_id)

    return {
        "current_phase": state.get("current_phase"),
        "documents_received": state.get("documents_received", []),
        "documents_pending": state.get("documents_pending", []),
        "mortgage_data": state.get("mortgage_data"),
        "income_docs": state.get("income_docs", []),
    }


@api.get("/session/{session_id}/result")
async def get_result(session_id: str):
    """
    Returns the Loan Recommendation Packet when available.
    """
    if not service.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    state = service.get_state(session_id)
    packet = state.get("loan_recommendation_packet")
    if not packet:
        raise HTTPException(status_code=400, detail="Recommendation packet not generated yet")
    return packet


agent_os_kwargs = {
    "id": "turborefi-loa",
    "name": "TurboRefi LOA",
    "description": "AgentOS app for the TurboRefi refinance LOA.",
    "agents": [service.agent],
    "base_app": api,
    "interfaces": [AGUI(agent=service.agent, prefix="/v1")],
}
agent_os_params = inspect.signature(AgentOS).parameters
if "on_route_conflict" in agent_os_params:
    agent_os_kwargs["on_route_conflict"] = "preserve_base_app"

agent_os = AgentOS(**agent_os_kwargs)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="src.app:app", host=PLAYGROUND_HOST, port=PLAYGROUND_PORT, reload=True)
