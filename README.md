# TurboRefi RAG Project

This repository contains two different approaches to the TurboRefi Loan Refinance RAG system.

## Project Structure

### 1. Agno Implementation (`/agno`)
The primary, feature-complete implementation using the **Agno** framework.
- **Backend:** `agno/backend/`
- **Frontend:** `agno/frontend/`
- **Virtual Environment:** `agno/backend/.venv/` (Contains `agno`, `fastapi`, etc.)
- **Start:** `python playground.py` (inside `agno/backend`)

### 2. LangGraph Implementation (`/lang-graph`)
A research/alternative implementation using **LangGraph** and **LangChain**.
- **Source:** `lang-graph/src/`
- **Virtual Environment:** `venv/` (Root directory. Contains `langgraph`, `langchain`, etc.)
- **Note:** This environment is separate from the Agno one to avoid dependency conflicts.

---

## Environment Quick Reference

| Service | Location | Virtual Environment | Purpose |
| :--- | :--- | :--- | :--- |
| **Agno Backend** | `agno/backend/` | `agno/backend/.venv` | Loan Officer Agent & RAG Explorer |
| **LangGraph** | `lang-graph/` | `venv/` (Root) | Research & Alternative Flow |

To run any script, ensure you are using the correct `python.exe` from the corresponding virtual environment.
