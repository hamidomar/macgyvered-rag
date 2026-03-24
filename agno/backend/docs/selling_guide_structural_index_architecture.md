# Deterministic Retrieval Architecture for the Fannie Mae Selling Guide

## Goal

Build a **deterministic, non‑embedding retrieval system** for the Fannie
Mae Selling Guide where an agent can:

1.  Understand a user question.
2.  Navigate the document hierarchy.
3.  Identify relevant sections.
4.  Fetch the exact text from those sections.
5.  Insert it into the LLM context.

The system prioritizes **clarity, reliability, and traceability** rather
than semantic similarity search.

------------------------------------------------------------------------

# Core Principle

The Selling Guide behaves more like a **legal code** than a normal
document.

Example section IDs:

A1-1-01\
A2-1-01\
B3-3-05

These identifiers already encode hierarchy.

Structure:

Part → Subpart → Chapter → Section

Example:

A1-1-01

A = Part A\
A1 = Subpart A1\
A1-1 = Chapter A1-1\
A1-1-01 = Section

Because of this, the document can be indexed **deterministically**.

------------------------------------------------------------------------

# First Iteration (Recommended MVP)

Only build a **Structural Index**.

This alone will handle \~90% of the problem.

## Pipeline

PDF\
↓\
Extract outline (or detect section headers)\
↓\
Determine section start and end pages\
↓\
Extract text for each section\
↓\
Store structured index

Output:

structured_sections.json

------------------------------------------------------------------------

# Structural Index Design

Example entry:

{ "section_id": "A1-1-01", "title": "Application and Approval of
Seller/Servicer", "part": "A", "subpart": "A1", "chapter": "A1-1",
"start_page": 60, "end_page": 62, "text": "...section text..." }

This becomes the **primary knowledge source** for the agent.

The PDF is only needed during preprocessing.

------------------------------------------------------------------------

# Agent Retrieval Flow

User question\
↓\
Agent reasons about which section(s) apply\
↓\
Lookup section_id in structured index\
↓\
Fetch section text\
↓\
Insert into LLM context

Example:

User: "What are the lender approval requirements?"

Agent reasoning:

Part A → Doing Business with Fannie Mae\
Subpart A1 → Approval Qualification\
Chapter A1-1 → Seller/Servicer Application\
Section A1-1-01 → Application and Approval

Agent calls:

get_section("A1-1-01")

------------------------------------------------------------------------

# Agent Tools

Tool 1: list_sections()

Returns available hierarchy.

Example:

list_sections("A")

Returns:

Subpart A1\
Subpart A2

------------------------------------------------------------------------

Tool 2: get_section(section_id)

Example:

get_section("A1-1-01")

Returns:

title\
text\
page range

------------------------------------------------------------------------

# Why This Works

Advantages:

• deterministic retrieval\
• no embedding drift\
• perfect source traceability\
• very fast lookup\
• simple architecture

This is similar to how **legal research systems** retrieve statutes.

------------------------------------------------------------------------

# Future Iteration Ideas

These are **not required for the MVP**, but can greatly improve accuracy
later.

------------------------------------------------------------------------

## Citation Index

Sections often reference other sections.

Example:

"See A2-1-01 for contractual obligations."

During preprocessing:

Detect section references with regex:

\[A-Z\]`\d-`{=tex}`\d-`{=tex}`\d{2}`{=tex}

Build graph:

{ "A1-1-01": \["A2-1-01", "B3-3-05"\] }

Then the agent can expand context:

Primary section\
+ referenced sections

This dramatically improves completeness.

------------------------------------------------------------------------

## Keyword Index (Optional)

Not required if the agent already knows which section to retrieve.

But later you could build:

keyword → section_id mapping

Example:

{ "lender approval": \["A1-1-01"\], "contractual obligations":
\["A2-1-01"\] }

This allows deterministic search without embeddings.

------------------------------------------------------------------------

# Final Architecture

Preprocessing:

PDF\
↓\
Parse hierarchy\
↓\
Extract section text\
↓\
Build structural index

Runtime:

User question\
↓\
Agent selects section(s)\
↓\
Lookup in structured index\
↓\
Provide text to LLM

------------------------------------------------------------------------

# Key Takeaway

The Selling Guide is unusually well‑structured.\
Its **section identifiers act like primary keys in a database**.

Because of this, you can build a **high‑precision retrieval system
without vector embeddings**, using only deterministic indexing.
