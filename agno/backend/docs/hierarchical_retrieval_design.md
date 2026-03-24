# Deterministic Hierarchical Retrieval for the Fannie Mae Selling Guide

## Objective

Build a retrieval system that allows an agent to locate relevant policy
sections within the Fannie Mae Selling Guide **without vector
embeddings**.

The system relies on two components:

1.  **A hierarchical document index** derived from the table of
    contents\
2.  **A structured section store** containing extracted section text

This allows the agent to **navigate the document structure like a human
reader**, then retrieve the exact section content.

------------------------------------------------------------------------

# Core Concept

The Selling Guide is organized hierarchically:

Part → Subpart → Chapter → Section

Example:

Part B -- Origination Through Closing\
Subpart B3 -- Underwriting Borrowers\
Chapter B3-3 -- Income Assessment\
Section B3-3-05 -- Income from Employment

Each section has a **stable identifier**:

B3-3-05

These identifiers serve as **primary keys for retrieval**.

------------------------------------------------------------------------

# Preprocessing Step

Before the agent can retrieve information, the PDF is processed once to
create a **structured document index**.

Pipeline:

PDF\
↓\
Parse outline / section headings\
↓\
Determine section start and end pages\
↓\
Extract text for each section\
↓\
Build hierarchical structure\
↓\
Build section lookup table\
↓\
Write structured_sections.json

The PDF itself is not needed during runtime after this preprocessing
step.

------------------------------------------------------------------------

# Structured JSON Output

The preprocessing script produces a JSON file containing two structures.

## 1. Section Lookup (Hash Index)

Provides fast retrieval by section ID.

Example:

    sections = {
      "B3-3-05": {
        "title": "Income from Employment",
        "part": "B",
        "subpart": "B3",
        "chapter": "B3-3",
        "start_page": 221,
        "end_page": 226,
        "text": "..."
      }
    }

Lookup complexity is constant time.

    sections["B3-3-05"]

------------------------------------------------------------------------

## 2. Hierarchical Navigation Structure

Represents the document table of contents.

Example:

    hierarchy = {
      "B": {
        "title": "Origination Through Closing",
        "subparts": {
          "B3": {
            "title": "Underwriting Borrowers",
            "chapters": {
              "B3-3": {
                "title": "Income Assessment",
                "sections": [
                  {
                    "id": "B3-3-05",
                    "title": "Income from Employment"
                  },
                  {
                    "id": "B3-3-06",
                    "title": "Self-Employment Income"
                  }
                ]
              }
            }
          }
        }
      }
    }

This structure allows the agent to **explore the document hierarchy**.

------------------------------------------------------------------------

# Agent Retrieval Flow

The agent does not initially know the correct section ID.

Instead it navigates the document structure.

Example user query:

How should lenders evaluate W-2 income?

Agent navigation:

    list_parts()
    → Part B – Origination Through Closing

    list_subparts("B")
    → Subpart B3 – Underwriting Borrowers

    list_chapters("B3")
    → Chapter B3-3 – Income Assessment

    list_sections("B3-3")
    → B3-3-05 – Income from Employment

Once the agent identifies the relevant section:

    get_section("B3-3-05")

The system returns the extracted section text.

------------------------------------------------------------------------

# Tool Interface for the Agent

The agent interacts with the document through simple navigation tools.

Example tools:

    list_parts()

    list_subparts(part_id)

    list_chapters(subpart_id)

    list_sections(chapter_id)

    get_section(section_id)

These tools mirror how a human would navigate a policy manual.

------------------------------------------------------------------------

# Runtime Retrieval Architecture

User question\
↓\
Agent navigates hierarchy\
↓\
Agent selects section ID\
↓\
Section lookup retrieves text\
↓\
Text inserted into LLM context

This approach provides:

-   deterministic retrieval
-   full source traceability
-   fast lookup
-   no reliance on embeddings

------------------------------------------------------------------------

# Optional Future Enhancements

## Citation Index

Some sections reference other sections.

Example text:

See A2-1-01 for contractual obligations.

During preprocessing these references could be extracted to build a
**section citation graph**.

Example:

    citations = {
      "A1-1-01": ["A2-1-01", "B3-3-05"]
    }

This would allow the agent to automatically retrieve **related policy
sections**.

------------------------------------------------------------------------

# Summary

The system relies on two core ideas:

1.  **Hierarchical navigation** using the document structure\
2.  **Direct section retrieval** using section identifiers

The preprocessing step converts the PDF into a structured dataset that
the agent can navigate efficiently.

This allows accurate retrieval from a large regulatory document
**without vector embeddings**.
