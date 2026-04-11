# TurboRefi Agno Implementation Plan

## Purpose

This plan replaces the earlier standalone MVP plan with a merged design based on:

- `docs/TurboRefi_System_Overview.md`
- `docs/TurboRefi_Agent_Technical_Design.md`
- `docs/TurboRefi_ConversationFlows.jsx`
- `docs/TurboRefi_TechnicalSpecs_UC1-UC3.md`

The goal is to keep the **system structure** introduced in the new docs, while implementing it using the **Agno-based localhost approach** we had already chosen:

- Agno agents
- Agno Playground server
- Agno UI for testing
- OpenAI models
- deterministic guideline retrieval from `retrival/`
- local-first runtime and storage

This document is the implementation blueprint we should follow.

---

## Merge Decision

### What we are taking from the new docs

From the new system docs, we keep these ideas:

- the two-phase product structure:
  - document extraction
  - LOA reasoning
- the conversational loan-officer workflow
- the Loan Recommendation Packet as the main structured output
- on-demand guideline retrieval through tools rather than stuffing guides into context
- module boundaries such as extraction, tools, prompts, and session/workflow layers

### What we are keeping from the previous Agno plan

From the earlier `plan.md`, we keep these implementation choices:

- Agno Playground as the local app server
- Agno UI as the playground client
- OpenAI models configured by env vars
- deterministic guide access through the existing `retrival/` code
- explicit local orchestration instead of raw provider API loops
- local SQLite + JSON trace storage
- verifier/compliance support designed in from the start, even if introduced after the first LOA-only milestone

### What we are changing

We are **not** going to implement the new docs literally where they conflict with the repo we already have.

Examples:

- We will not use raw `anthropic_client.messages.create(...)` loops.
- We will not create a separate custom session loop if Agno already handles agent runs, tools, and storage well.
- We will not replace the current deterministic retrieval format with a brand-new `guides/.../sections/*.json` format.

Instead:

- Agno manages agent execution and tool calling.
- Our Python workflow layer manages product sequencing.
- The existing `retrival/` toolchain remains the retrieval backend.

---

## Target Product Shape

TurboRefi is a refinance advisor with a deterministic conversational shape:

1. borrower provides mortgage documents
2. extraction returns structured JSON
3. LOA requests only the missing supporting docs
4. LOA retrieves guidelines and calls calculator tools
5. LOA produces a Loan Recommendation Packet
6. later phase: Verifier independently checks the packet and computes compliance

This is not a general chatbot. It is a guided underwriting workflow with agent language on top.

---

## Recommended Delivery Sequence

### V1

Build:

- extraction layer
- LOA agent
- Loan Recommendation Packet
- Agno Playground app
- Agno UI local testing
- UC1 first

### V1.5

Add:

- Verifier agent
- compliance scoring
- audit comparison report

### V2

Add:

- UC2 and UC3 full flows
- stronger calculator coverage
- richer file upload experience
- better Freddie support when local source material exists

This sequence matches the newer docs better than forcing verifier/compliance into the very first working cut, while still preserving space for it in the code layout.

---

## Agno-Based Runtime Architecture

```text
Agno UI (localhost:3000)
        |
        v
Agno Playground App (localhost:7777)
        |
        v
TurboRefi Runner
        |
        +--> Extraction Service / Extraction Agent
        |       |
        |       +--> OpenAI multimodal model
        |       +--> extraction prompts
        |       +--> document normalizers
        |
        +--> Loan Officer Agent
        |       |
        |       +--> guideline retrieval tools
        |       +--> calculator tools
        |       +--> document/state tools
        |
        +--> Verifier Agent (phase after V1)
        |       |
        |       +--> same retrieval tools
        |       +--> same calculators
        |       +--> compliance scoring service
        |
        +--> local storage
                |
                +--> Agno SQLite history
                +--> JSON traces / workflow state
```

### Key design choice

The new docs describe a custom session loop. In our implementation, that becomes:

- Agno agents for model execution and tool calling
- a Python workflow/orchestrator for the TurboRefi product logic

So the workflow is **structured by our code**, but the LOA and Verifier are still real Agno agents.

That is the right compromise for a deterministic mortgage workflow.

---

## Phase Model

## Phase 1: Document Extraction

This stays as a distinct layer, exactly as the new system docs intend.

Responsibilities:

- accept uploaded PDFs or structured mock inputs
- run document-specific extraction prompts
- return normalized JSON
- do no eligibility reasoning

Supported document types:

- mortgage statement
- paystub
- W-2
- 1040 / Schedule C

### MVP implementation note

For the first localhost build, we should support **two input modes**:

1. `fixture mode`
   - load mock borrower/doc JSON from disk
   - fastest path to validate the workflow

2. `upload mode`
   - parse uploaded documents through the extraction layer
   - introduced once the Agno Playground upload path is wired

This lets us keep the architecture from the new docs without blocking the first working demo on document ingestion details.

## Phase 2: LOA Reasoning

The LOA agent receives structured extracted data, not raw PDFs.

Responsibilities:

- identify income type
- request missing docs
- retrieve relevant guideline sections
- call calculators
- assess FNMA and FHLMC eligibility
- produce the Loan Recommendation Packet

The LOA must:

- never do inline math
- always use tools for calculations
- always cite the guideline section supporting a claim
- ask for documents in the expected order

## Phase 3: Independent Verification

This is built into the architecture now, but can come after the first LOA milestone.

Responsibilities:

- receive raw normalized borrower data plus the LOA packet
- independently retrieve supporting sections
- rerun the calculators
- compare field by field
- generate the Verification Report and compliance score

---

## What Changes When Using Agno

The new technical design doc uses direct provider calls and a hand-built session class. In the Agno version:

### We keep

- system prompts
- tools
- structured outputs
- agent separation
- session state model

### We replace

- manual provider loops with Agno `Agent`
- hand-managed tool dispatch with Agno tool wrappers
- direct message-array management with Agno storage/session handling
- custom entrypoint with `Playground(...)`

### Result

The product design remains the same, but the execution model becomes:

- simpler
- more inspectable in the playground
- easier to expose locally
- easier to extend with separate debugging agents

---

## Proposed Repository Structure

```text
macgyvered-rag/
├── plan.md
├── pyproject.toml
├── .env.example
├── README.md
├── playground.py
├── data/
│   └── mock_cases/
│       ├── uc1_sarah_chen.json
│       ├── uc2_james_wilson.json
│       └── uc3_maria_garcia.json
├── runtime/
│   ├── agents.db
│   ├── traces/
│   └── sessions/
├── src/
│   └── turborefi/
│       ├── __init__.py
│       ├── config.py
│       ├── schemas.py
│       ├── prompts.py
│       ├── workflow.py
│       ├── extraction/
│       │   ├── __init__.py
│       │   ├── prompts.py
│       │   ├── service.py
│       │   └── normalizers.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── loan_officer.py
│       │   ├── verifier.py
│       │   └── runner.py
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── guideline_tools.py
│       │   ├── calculators.py
│       │   ├── document_tools.py
│       │   └── case_tools.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── retrieval_service.py
│       │   ├── packet_builder.py
│       │   ├── compliance.py
│       │   ├── session_state.py
│       │   └── audit_log.py
│       └── rules/
│           ├── __init__.py
│           ├── document_requirements.py
│           └── guideline_map.py
├── tests/
│   ├── test_extraction_service.py
│   ├── test_calculators.py
│   ├── test_retrieval_service.py
│   ├── test_uc1_workflow.py
│   └── test_compliance.py
└── retrival/
    ├── README.md
    ├── scripts/
    ├── docs/
    └── data/
```

---

## File Responsibilities

## Root

### `playground.py`

Main local entrypoint.

Responsibilities:

- create Agno agents
- register them in `Playground(...)`
- attach SQLite storage
- expose localhost endpoint for Agno UI

Recommended playground surfaces:

- `TurboRefi Runner`
- `TurboRefi LOA`
- `TurboRefi Verifier`

The runner is the main demo surface. The other two are for isolated prompt/tool debugging.

### `pyproject.toml`

Defines the Python app and dependencies.

Expected core deps:

- `agno`
- `openai`
- `pydantic`
- `python-dotenv`
- `sqlalchemy`
- `fastapi[standard]`
- `pytest`

### `.env.example`

Required env vars:

- `OPENAI_API_KEY`
- `OPENAI_MODEL_EXTRACTION`
- `OPENAI_MODEL_LOA`
- `OPENAI_MODEL_VERIFIER`
- `FNMA_INDEX_DIR`
- `FHLMC_INDEX_DIR`
- `AGNO_STORAGE_DB`

If `FHLMC_INDEX_DIR` is absent, the app should still boot in FNMA-only mode and clearly mark Freddie support as partial.

### `README.md`

Documents:

- local setup
- guide preprocessing
- how to run the playground
- how to connect Agno UI
- how to run fixture mode vs upload mode

---

## Core package

### `src/turborefi/config.py`

Single source of truth for:

- env vars
- model IDs
- path resolution
- runtime folder setup

### `src/turborefi/schemas.py`

Pydantic models for:

- extracted mortgage statement
- extracted paystub
- extracted W-2
- extracted Schedule C / tax-return data
- borrower case
- document state
- Loan Recommendation Packet
- Verification Report
- compliance score
- session state
- audit events

The new docs are heavily schema-driven, so this file is foundational.

### `src/turborefi/prompts.py`

Holds:

- LOA system prompt
- Verifier system prompt
- extraction prompt text per document type
- any runner/orchestrator instruction text

The prompt content should follow the new docs, but rewritten for Agno/OpenAI rather than Anthropic-specific loops.

### `src/turborefi/workflow.py`

The real application orchestrator.

Responsibilities:

- intake a fixture or uploaded document set
- call extraction service when needed
- update session state
- invoke LOA agent
- optionally invoke Verifier
- write traces
- return final structured outputs

This file replaces the custom `LOASession` design from the new docs with an Agno-compatible workflow coordinator.

---

## Extraction layer

### `src/turborefi/extraction/prompts.py`

Document-specific extraction prompt templates for:

- mortgage statement
- paystub
- W-2
- Schedule C / 1040

These should be based directly on the extraction JSON specs in `TurboRefi_Agent_Technical_Design.md`.

### `src/turborefi/extraction/service.py`

Non-conversational extraction service.

Responsibilities:

- route by document type
- call the configured OpenAI multimodal model
- parse JSON output
- validate with Pydantic
- return normalized extraction results

This does not need to be exposed as a chat agent to end users. It can remain an internal service.

### `src/turborefi/extraction/normalizers.py`

Handles normalization rules:

- numeric cleanup
- date normalization
- consistent enum values
- merging multiple paystubs or tax years into one structured view

This keeps prompt outputs from bleeding straight into underwriting logic.

---

## Agent layer

### `src/turborefi/agents/loan_officer.py`

Builds the Agno LOA agent.

Tools exposed:

- guideline retrieval tools
- calculator tools
- document/state inspection tools

Behavior:

- asks for missing docs
- retrieves support sections
- calls calculators
- returns the Loan Recommendation Packet

### `src/turborefi/agents/verifier.py`

Builds the Agno Verifier agent.

Tools exposed:

- same guideline retrieval tools
- same calculators
- packet/state inspection tools

Behavior:

- independently re-derives the LOA findings
- returns field comparisons
- feeds the compliance scorer

### `src/turborefi/agents/runner.py`

Optional runner wrapper if we want a top-level Agno-facing surface instead of invoking workflow functions directly.

This can expose friendly commands like:

- load UC1 fixture
- show missing docs
- run LOA assessment
- run full verification

---

## Tool layer

### `src/turborefi/tools/guideline_tools.py`

Agno tool wrappers around the existing deterministic retrieval backend.

Initial tools:

- `get_guideline_section(section_id, gse)`
- `search_guideline_titles(query, gse)`
- `get_section_with_references(section_id, gse)`

Optional helper:

- `get_expected_guidelines(use_case, stage)`

### `src/turborefi/tools/calculators.py`

Deterministic finance/math functions.

Initial tools:

- `calc_w2_income(...)`
- `calc_ltv(...)`
- `calc_pmi_savings(...)`
- `calc_se_income(...)`

Where the formulas are already clear, we should implement real deterministic logic now rather than placeholder stubs.

### `src/turborefi/tools/document_tools.py`

Helpers for the agents to inspect normalized document data and session state.

Examples:

- `list_received_documents(session_id)`
- `list_missing_documents(session_id)`
- `get_extracted_document(session_id, doc_type)`

### `src/turborefi/tools/case_tools.py`

Fixture-mode helpers.

Examples:

- `list_mock_cases()`
- `load_mock_case(case_id)`
- `seed_session_from_case(case_id)`

This is important for getting the localhost playground working before upload mode is perfect.

---

## Services and rules

### `src/turborefi/services/retrieval_service.py`

Adapter over `retrival/`.

Responsibilities:

- load the guide indices once at startup
- resolve FNMA vs FHLMC guide instances
- normalize return shapes for tools and audits
- keep the existing deterministic retrieval implementation intact

### `src/turborefi/services/packet_builder.py`

Creates:

- Loan Recommendation Packet
- Verification Report
- combined workflow outputs

The new docs treat these as structured outputs. This service makes that explicit and testable.

### `src/turborefi/services/session_state.py`

Owns the local version of the state object.

Tracks:

- borrower data
- extracted documents
- requested/received/pending documents
- retrieval events
- tool calls
- LOA result
- verifier result
- final status

### `src/turborefi/services/audit_log.py`

Writes local JSON traces for:

- extraction events
- retrieval calls
- calculator calls
- final packets

### `src/turborefi/services/compliance.py`

Deterministic scorer for verifier mode.

This is phase after the first LOA-only milestone, but the file should exist in the layout from the beginning.

### `src/turborefi/rules/document_requirements.py`

Encodes document requirements by income type.

Examples:

- W-2 salaried
- self-employed
- gig / 1099
- rental income

### `src/turborefi/rules/guideline_map.py`

Maps use case + reasoning stage to the guideline sections we expect the agent to need.

This does not replace retrieval. It provides deterministic anchors and reduces agent drift.

---

## Guide Retrieval Plan

## What we keep from the new docs

We keep the retrieval philosophy exactly:

- do not preload the full guides into context
- load the guide index once at startup
- expose retrieval as callable tools
- fetch sections at the moment the agent needs them

## What we adapt to match the current repo

The new docs describe a guide storage layout like:

```text
guides/selling_guide_index/
guides/fhlmc_guide_index/
```

Our repo currently already has deterministic guide tooling in:

- `retrival/scripts/guide_tool.py`
- `retrival/scripts/selling_guide_tool.py`

and those tools expect a directory containing:

- `hierarchy_tree.json`
- `structured_sections.json`
- `cross_references.json`

So the implementation plan is:

1. keep the current deterministic retrieval format
2. preprocess guides into that format
3. wrap that backend with Agno tools

We should not redesign the retrieval substrate before the first app exists.

## Current repo constraint

At the moment:

- FNMA source material exists locally
- preprocessed index output is not checked in
- FHLMC single-family source material does not appear to be present locally

Therefore:

- FNMA can be the first complete path
- FHLMC support should be designed in, but may remain partial until source data is added

---

## Conversation Design

We should keep the four-turn LOA structure from the new docs and specs:

1. review mortgage statement and request supporting docs
2. receive extracted docs and begin guideline retrieval
3. present findings with citations and tool results
4. emit Loan Recommendation Packet JSON

The difference is only the runtime implementation:

- Agno agent instead of direct provider loop
- workflow state instead of manual message wiring

For the first working build, the UI can still feel conversational even if internally the runner is guiding the user through a more deterministic sequence.

---

## Recommended Playground Surfaces

### `TurboRefi Runner`

Primary end-to-end experience.

Use it for:

- loading fixtures
- simulating uploads
- running the extraction-to-LOA flow
- later invoking verification

### `TurboRefi LOA`

Use it for:

- prompt tuning
- tool-call debugging
- section citation behavior

### `TurboRefi Verifier`

Use it later for:

- independent re-derivation testing
- compliance scoring checks

This separation is one of the main advantages of using Agno here.

---

## MVP Scope

## Milestone 1

**UC1 end-to-end in Agno Playground with fixture mode**

Definition of done:

- app boots locally
- Agno UI connects
- user can load UC1 fixture
- LOA requests or confirms required docs
- LOA uses deterministic retrieval + calculator tools
- LOA emits a valid Loan Recommendation Packet
- traces are stored locally

## Milestone 2

**Add upload-driven extraction for the same UC1 flow**

Definition of done:

- user uploads mortgage statement / supporting docs
- extraction service returns validated JSON
- workflow state updates correctly
- LOA flow still works end to end

## Milestone 3

**Add verifier and compliance**

Definition of done:

- verifier reruns retrieval and math from raw data
- comparisons are structured
- compliance score is deterministic

## Milestone 4

**Extend to UC2 and UC3**

Add:

- PMI removal flow
- self-employed flow
- appraisal/business-verification pending items
- stronger tool coverage

---

## Test Plan

### `tests/test_extraction_service.py`

Validate:

- extraction prompt routing
- JSON parsing
- schema validation
- normalization

### `tests/test_calculators.py`

Validate:

- W-2 income
- LTV
- PMI savings
- self-employed averaging

### `tests/test_retrieval_service.py`

Validate:

- guide loading
- section retrieval
- title search
- references traversal

### `tests/test_uc1_workflow.py`

End-to-end fixture-mode smoke test.

### `tests/test_compliance.py`

Verifier/compliance scoring tests, added once that phase starts.

---

## Risks and Constraints

### 1. FNMA preprocessing output is still required

The runtime app depends on a generated index directory. That needs to exist before retrieval tools can work.

### 2. Freddie support is structurally planned but locally incomplete

The current repo does not yet look ready for a full FHLMC implementation path.

### 3. Upload mode is more fragile than fixture mode

The architecture should include it now, but the first success criterion should still be fixture-mode UC1.

### 4. The `retrival/` folder name is misspelled but already established

Keep it as-is for the first implementation to avoid unnecessary churn.

---

## Final Recommendation

Yes, we should use the **new structure** from the two new design docs.

But we should implement that structure through the **Agno-based localhost architecture** rather than copying the non-Agno session design directly.

The practical outcome is:

- extraction stays a separate phase
- LOA stays the primary reasoning agent
- verifier stays in the design
- guides stay tool-accessed and deterministic
- Agno handles agent runtime, Playground exposure, and local testing

That is the cleanest merged direction for this repo.
