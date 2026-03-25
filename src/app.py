from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
import uuid
import json

from src.graph.builder import build_graph
from langchain_core.messages import HumanMessage
from src.tools.extraction import extract_document
from src.logger import get_logger

logger = get_logger("api_backend")

app = FastAPI(title="TurboRefi LOA V1 API")

# Compile the graph
graph = build_graph()

class MessageRequest(BaseModel):
    message: str

@app.post("/session")
async def create_session(file: UploadFile = File(...)):
    """
    Accepts a mortgage statement file upload.
    Extracts the document using OpenAI multimodal API, 
    creates graph state, runs extract_mortgage + loa_call.
    Returns: session_id + LOA's first response.
    """
    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}
    
    try:
        # Extract data from the uploaded file
        file_bytes = await file.read()
        extracted_data = extract_document(file_bytes, "mortgage_statement", file.content_type)
        
        # Inject the extracted JSON into the conversation history
        content = f"[SYSTEM: Document received - mortgage_statement]\n{json.dumps(extracted_data, indent=2)}"
        
        # Initialize state
        initial_state = {
            "session_id": session_id,
            "messages": [HumanMessage(content=content)],
            "documents_received": ["mortgage_statement"],
            "documents_pending": [],
            "mortgage_data": extracted_data
        }
    
        # Run the graph
        logger.info(f"Initializing new session ID: {session_id}")
        final_state = graph.invoke(initial_state, config=config)
        ai_message = final_state["messages"][-1].content
        
        return {
            "session_id": session_id,
            "response": ai_message,
            "current_phase": final_state.get("current_phase", "greeting")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/session/{session_id}/upload")
async def upload_document(session_id: str, doc_type: str = Form(...), file: UploadFile = File(...)):
    """
    Uploads secondary documents to an existing session.
    Extracts data and updates State WITHOUT invoking the graph.
    """
    config = {"configurable": {"thread_id": session_id}}
    
    try:
        logger.info(f"Processing upload request for doc_type: '{doc_type}' on session: {session_id}")
        # Extract data from the uploaded file
        file_bytes = await file.read()
        from src.tools.extraction import extract_document
        extracted_data = extract_document(file_bytes, doc_type, file.content_type)
        
        logger.info(f"Extraction successful for {doc_type}. Fields mapped: {list(extracted_data.keys())}")
        
        # Inject the new document data as a system notification
        content = f"[SYSTEM: Document received - {doc_type}]\n{json.dumps(extracted_data, indent=2)}"
        
        # Update state directly accumulating doc payload without unpausing graph
        graph.update_state(config, {
            "messages": [HumanMessage(content=content)],
            "documents_received": [doc_type],
            "income_docs": [extracted_data]
        })
        return {
            "status": "received",
            "message": f"{doc_type} successfully parsed and stored in memory."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/session/{session_id}/resume")
async def resume_session(session_id: str):
    """
    Explicitly resumes the LangGraph orchestration. To be called once user clicks 'Done Uploading'.
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        logger.info(f"Explicit graph resume triggered for session: {session_id}. Advancing assessment...")
        # Resume the graph with no new input payload
        final_state = graph.invoke(None, config=config)
        ai_message = final_state["messages"][-1].content
        return {
            "response": ai_message,
            "current_phase": final_state.get("current_phase", "assessment")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/session/{session_id}/message")
async def send_message(session_id: str, request: MessageRequest):
    """
    Sends a text message from the borrower.
    Returns: LOA's next response
    """
    config = {"configurable": {"thread_id": session_id}}
    
    input_message = HumanMessage(content=request.message)
    
    try:
        final_state = graph.invoke({"messages": [input_message]}, config=config)
        ai_message = final_state["messages"][-1].content
        return {"response": ai_message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/session/{session_id}/status")
async def get_status(session_id: str):
    """
    Returns current phase, docs received/pending, whether complete
    """
    config = {"configurable": {"thread_id": session_id}}
    state = graph.get_state(config)
    
    if not state or not state.values:
        raise HTTPException(status_code=404, detail="Session not found")
        
    vs = state.values
    return {
        "current_phase": vs.get("current_phase"),
        "documents_received": vs.get("documents_received", []),
        "documents_pending": vs.get("documents_pending", []),
        "mortgage_data": vs.get("mortgage_data"),
        "income_docs": vs.get("income_docs", [])
    }

@app.get("/session/{session_id}/result")
async def get_result(session_id: str):
    """
    Returns the Loan Recommendation Packet (only when phase == "complete")
    """
    config = {"configurable": {"thread_id": session_id}}
    state = graph.get_state(config)
    
    if not state or not state.values:
        raise HTTPException(status_code=404, detail="Session not found")
        
    packet = state.values.get("loan_recommendation_packet")
    if not packet:
        raise HTTPException(status_code=400, detail="Recommendation packet not generated yet")
        
    return packet

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
