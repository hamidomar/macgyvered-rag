# TurboRefi Agno Migration

This folder is the Agno-based copy of the original `macgyvered-rag/` application.
The retrieval indices, extraction prompts, calculator behavior, and LOA system prompt are preserved, but the LangGraph runtime has been replaced with:

- an Agno `Agent` for tool-calling and multi-turn execution
- an Agno `AgentOS` app with the `AGUI` interface for Agent UI connectivity
- a small session service that preserves the existing upload/message/status/result API surface

Run the backend with:

```bash
python playground.py
```

By default this serves the Agno AgentOS app on `http://localhost:7777`.
Connect Agent UI to `http://localhost:7777/v1`.
The document endpoints remain available on the same server:

- `POST /session`
- `POST /session/{session_id}/upload`
- `POST /session/{session_id}/message`
- `GET /session/{session_id}/status`
- `GET /session/{session_id}/result`

# RAG Loan Refinance — Fannie Mae Selling Guide Parser & Tooling

This project provides a deterministic pipeline for transforming the massive Fannie Mae Single Family Selling Guide PDF into a structured, navigable, and queryable JSON index. It is designed to be used both by human experts (via a CLI explorer) and by AI agents (via a structured retrieval tool).

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Setup & Installation](#setup--installation)
4. [Workflow](#workflow)
    - [Step 1: Add the PDF](#step-1-add-the-pdf)
    - [Step 2: Preprocess/Parse](#step-2-preprocess-parse)
    - [Step 3: Interactive Exploration](#step-3-interactive-exploration)
    - [Step 4: Agent Integration](#step-4-agent-integration)
5. [File Inventory](#file-inventory)

---

## Overview

The Selling Guide is a ~1,200 page PDF with a complex hierarchy of Parts, Subparts, Chapters, and Topics. This project uses the PDF's internal bookmark (outline) tree to surgically extract text for every "topic" (leaf node), preserving the parent-child relationships and cross-references.

- **Deterministic**: No LLMs are used for parsing; the structure is derived directly from PDF metadata.
- **Structured**: Outputs include a full navigation tree and a citation index.
- **Tool-Ready**: Includes a retrieval class specifically designed for LLM function calling.

## Prerequisites

- Python 3.10+
- `pypdf` (for outline extraction)
- `pdfplumber` (for coordinate-based text extraction)

## Setup & Installation

1. **Create and activate a virtual environment:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```powershell
   pip install pypdf pdfplumber
   ```

---

## Workflow

### Step 1: Add the PDF
Place your Fannie Mae Selling Guide PDF in the `data/pdfs/` directory. 
Example path: `data/pdfs/02 04 2026 Single Family Selling Guide_highlighting.pdf`

### Step 2: Preprocess (Parse)
Run the preprocessor script to generate the structured index. This script walks the bookmarks, computes navigable IDs (like `A2-1-01`), and extracts text between coordinates.

```powershell
python scripts/preprocess_selling_guide.py "data/pdfs/02 04 2026 Single Family Selling Guide_highlighting.pdf" --output-dir "output/selling_guide_preprocessed"
```

**What happens here?**
- It identifies 400+ leaf topics.
- It extracts ~2.4 million characters of text.
- It builds a `cross_references.json` showing which sections cite each other.

### Step 3: Interactive Exploration (For Humans)
To validate the extraction or search for specific guidelines manually, use the `explore_guide.py` script. It acts like a "terminal-based browser" for the guide.

```powershell
python scripts/explore_guide.py "output/selling_guide_preprocessed"
```

**Commands inside the explorer:**
- `B` -> Navigate into Part B (Origination).
- `B2-1.3-03` -> Directly read the "Cash-Out Refinance" topic.
- `search cash-out` -> Find all topics containing those keywords.
- `refs B2-1.3-03` -> See what other sections cite this one (and vice versa).
- `back` / `top` / `quit` -> General navigation.

### Step 4: Agent Integration (For AI)
The `scripts/selling_guide_tool.py` contains the `SellingGuideTool` class. This is the script an AI agent (like Antigravity) uses as its "eyes" to read the guide.

**Key Methods:**
- `list_contents(path)`: Returns the titles/IDs for a specific level of the tree.
- `get_section(section_id)`: Returns full text, metadata, and references for a topic.
- `get_section_with_references(section_id, depth)`: Fetches a section and its cited relatives to expand context.
- `search_titles(query)`: High-speed keyword search across the table of contents.

---

## File Inventory

| File | Description |
| :--- | :--- |
| **`scripts/preprocess_selling_guide.py`** | The parser. Converts PDF -> JSON. |
| **`scripts/selling_guide_tool.py`** | Retrieval class for programmatic/agent access. |
| **`scripts/explore_guide.py`** | Interactive CLI REPL for human users. |
| **`output/.../hierarchy_tree.json`** | Nested navigation metadata. |
| **`output/.../structured_sections.json`** | The core data: text chunks with IDs and metadata. |
| **`output/.../cross_references.json`** | Citation map for context expansion. |
