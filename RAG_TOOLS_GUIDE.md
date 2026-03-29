# RAG Tools Guide

These tools allow the agent to interact with the preprocessed Fannie Mae (FNMA) and Freddie Mac (FHLMC) guideline indices.

| Tool Name | Description | Key Arguments |
| :--- | :--- | :--- |
| **`list_guide_contents`** | **Navigate the Hierarchy.** Shows one level of the guide's Table of Contents at a time. Used to "click through" chapters and sub-chapters. | `path`: The ID to drill into (e.g., "B3" or "1.3"). <br> `gse`: "fnma" or "fhlmc" |
| **`search_guideline_titles`** | **Keyword Search.** Performs a fast, deterministic keyword search across all chapter and section titles. Best for finding relevant IDs quickly. | `query`: Keywords (e.g., "income verification"). <br> `gse`: "fnma" or "fhlmc" |
| **`get_guideline_section`** | **Fetch Rule Text.** Retrieves the full, exact text and metadata of a specific guideline section once you have its ID. | `section_id`: The ID (e.g., "B3-3.1-01"). <br> `gse`: "fnma" or "fhlmc" |
| **`get_section_with_references`** | **Contextual Retrieval.** Fetches a primary section plus every other section it explicitly cites (1-hop expansion). Useful for complex rules. | `section_id`: The starting section. <br> `gse`: "fnma" or "fhlmc" |

---

### Implementation Details
*   **Location:** Defined in [guide_tools.py](file:///c:/Users/omrha/Desktop/Projects/RAG_Loan_Refinance/agno/backend/src/tools/guide_tools.py).
*   **Logic:** Powered by the `GuideTool` engine in [guide_tool.py](file:///c:/Users/omrha/Desktop/Projects/RAG_Loan_Refinance/agno/backend/scripts/guide_tool.py).
*   **Philosophy:** These tools are designed to be "deterministic." Unlike vector search, which might return "similar" but irrelevant text, these tools allow the agent to traverse the actual, structured regulatory index, ensuring 100% accuracy in citations.
