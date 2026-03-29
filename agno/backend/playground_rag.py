# A dedicated AgentOS playground solely for the RAG agent.
# This runs on a different port than the main LOA app so they don't collide.
from fastapi import FastAPI
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

from src.agent import get_rag_agent
from src.config import PLAYGROUND_HOST, PLAYGROUND_PORT

api = FastAPI(title="Guide Expert RAG API (Agno)")

rag_agent = get_rag_agent()

agent_os_kwargs = {
    "id": "guide-expert-rag",
    "name": "Guide Expert (RAG)",
    "description": "AgentOS dedicated app for exploring FNMA/FHLMC guidelines.",
    "agents": [rag_agent],
    "base_app": api,
    "interfaces": [AGUI(agent=rag_agent, prefix="/v1")],
}

agent_os = AgentOS(**agent_os_kwargs)
app = agent_os.get_app()

if __name__ == "__main__":
    import uvicorn
    # Make sure we run on a different port than the main playground
    rag_port = PLAYGROUND_PORT + 1
    print(f"Starting Dedicated RAG Playground at http://{PLAYGROUND_HOST}:{rag_port}")
    agent_os.serve(app="playground_rag:app", host=PLAYGROUND_HOST, port=rag_port, reload=True)
