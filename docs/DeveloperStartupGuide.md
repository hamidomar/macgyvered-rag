# TurboRefi Startup Guide

This guide is the fastest way for a developer to run the current `old/macgyvered-rag` app locally.

## Prerequisites

- Python `3.11+`
- Node `18+`
- an `OPENAI_API_KEY`
- a generated FNMA guide index directory

## Backend Setup

From the project root:

```bash
cd /Users/vansh/Desktop/personal_project/refi_agent/old/macgyvered-rag

python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

cp .env.example .env
```

Set at minimum in `.env`:

```bash
OPENAI_API_KEY=...
FNMA_INDEX_DIR=/Users/vansh/Desktop/personal_project/refi_agent/old/macgyvered-rag/retrival/output/selling_guide_preprocessed
```

Optional:

```bash
FHLMC_INDEX_DIR=
PLAYGROUND_HOST=0.0.0.0
PLAYGROUND_PORT=7777
AGNO_HISTORY_LENGTH=12
AGNO_STORAGE_DB=runtime/agents.db
```

## Start The Backend

```bash
cd /Users/vansh/Desktop/personal_project/refi_agent/old/macgyvered-rag
source .venv/bin/activate
python3 playground.py
```

This starts:

- product API on `http://localhost:7777`
- LOA AG-UI on `http://localhost:7777/v1`
- verifier AG-UI on `http://localhost:7777/verifier`
- runner AG-UI on `http://localhost:7777/runner`

## Frontend Setup

In a second terminal:

```bash
cd /Users/vansh/Desktop/personal_project/refi_agent/old/macgyvered-rag/frontend
npm install
```

## Start The Frontend

```bash
npm run dev
```

The frontend runs on `http://localhost:3000` and points to `http://localhost:7777` by default.

## Smoke Test

1. Open `http://localhost:3000`
2. Upload a mortgage statement
3. Follow the intake prompts
4. Upload the requested supporting documents
5. Check `GET /session/{session_id}/status` or the chat UI for progress
6. After completion, load the recommendation packet and run verification

## Backend Test Command

```bash
cd /Users/vansh/Desktop/personal_project/refi_agent/old/macgyvered-rag
source .venv/bin/activate
PYTHONPATH=src pytest
```
