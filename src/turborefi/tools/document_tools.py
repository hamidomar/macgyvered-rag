from __future__ import annotations

from turborefi.rules.document_requirements import get_document_requirements, get_document_status


def summarize_document_state(
    income_type: str,
    document_counts: dict[str, int] | None = None,
) -> dict[str, list[str]]:
    document_counts = document_counts or {}
    return get_document_status(income_type=income_type, document_counts=document_counts)


def build_document_tools():
    from agno.tools import tool

    @tool(show_result=True)
    def summarize_documents(
        income_type: str,
        document_counts: dict[str, int] | None = None,
    ) -> dict[str, list[str]]:
        """Summarize received and missing documents for a borrower income type."""
        return summarize_document_state(income_type=income_type, document_counts=document_counts)

    @tool(show_result=True)
    def get_required_documents(income_type: str) -> dict:
        """Return the required document counts and pending pre-closing items for an income type."""
        return get_document_requirements(income_type=income_type)

    return [summarize_documents, get_required_documents]
