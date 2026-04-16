from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from turborefi.rules.guideline_map import USE_CASE_MAX_LTV
from turborefi.schemas import (
    GuidelineCitation,
    LoanRecommendationPacket,
    RetrievalEvent,
    SessionState,
    ToolCallRecord,
)
from turborefi.services.guideline_research import (
    DeterministicGuidelineResearcher,
    GuidelineResearcher,
    required_focus_keys_for_state,
)
from turborefi.services.gse_analysis import DeterministicGSEAnalyzer, GSEAnalyzer
from turborefi.services.retrieval_service import RetrievalService


logger = logging.getLogger(__name__)


@dataclass
class PacketBuildResult:
    packet: LoanRecommendationPacket
    retrieval_events: list[RetrievalEvent]
    tool_calls: list[ToolCallRecord]


def coerce_loan_packet(raw_response: Any) -> LoanRecommendationPacket:
    content = getattr(raw_response, "content", raw_response)
    if isinstance(content, LoanRecommendationPacket):
        return content
    if isinstance(content, dict):
        return LoanRecommendationPacket.model_validate(content)
    if isinstance(content, str):
        return LoanRecommendationPacket.model_validate(json.loads(content))
    raise TypeError(f"Unsupported LOA response type: {type(content)!r}")


def _tool_call(tool_name: str, inputs: dict[str, Any], result: dict[str, Any]) -> ToolCallRecord:
    return ToolCallRecord(tool=tool_name, inputs=inputs, result=result)


def _citation_summary_by_gse(citations: list[GuidelineCitation]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for citation in citations:
        gse = citation.gse or "unknown"
        grouped.setdefault(gse, []).append(
            {
                "focus_key": citation.focus_key,
                "focus_label": citation.focus_label,
                "section": citation.section,
                "title": citation.title,
                "finding": citation.finding,
                "why_selected": citation.why_selected,
            }
        )
    return grouped


def _guideline_review_tool_call(
    *,
    citations: list[GuidelineCitation],
    retrieved_gses: set[str],
) -> ToolCallRecord:
    return _tool_call(
        "review_guideline_support",
        {
            "retrieved_gses": sorted(retrieved_gses),
            "citation_count": len(citations),
        },
        {
            "retrieved_gses": sorted(retrieved_gses),
            "citations_by_gse": _citation_summary_by_gse(citations),
        },
    )


def _gse_analysis_tool_call(gse_analysis: dict[str, Any]) -> ToolCallRecord:
    return _tool_call(
        "analyze_gse_eligibility",
        {},
        {
            "gse_analysis": gse_analysis,
        },
    )


def _packet_generation_tool_call(
    tool_name: str,
    *,
    session_state: SessionState,
    packet: LoanRecommendationPacket,
    retrieved_gses: set[str],
) -> ToolCallRecord:
    return _tool_call(
        tool_name,
        {
            "use_case": session_state.use_case,
            "documents_pending": list(session_state.missing_documents),
            "full_application_intent": session_state.full_application_intent,
            "retrieved_gses": sorted(retrieved_gses),
        },
        {
            "recommended_gse": packet.recommended_gse,
            "recommended_gse_reason": packet.recommended_gse_reason,
            "fnma_eligible": packet.fnma_eligible,
            "fhlmc_eligible": packet.fhlmc_eligible,
            "qualifying_monthly_income": packet.qualifying_monthly_income,
            "ltv_percent": packet.ltv_percent,
            "monthly_savings_estimate": packet.monthly_savings_estimate,
            "documentation_status": packet.documentation_status.model_dump(mode="json"),
            "citations_by_gse": _citation_summary_by_gse(packet.guideline_citations),
        },
    )


def _guideline_artifacts(
    session_state: SessionState,
    retrieval_service: RetrievalService,
    guideline_researcher: GuidelineResearcher | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[GuidelineCitation], list[RetrievalEvent], set[str]]:
    researcher = guideline_researcher or DeterministicGuidelineResearcher(retrieval_service)
    research_result = researcher.research(session_state, progress_callback=progress_callback)
    supported_gses = research_result.supported_gses(required_focus_keys_for_state(session_state))
    citations = [citation for citation in research_result.citations if citation.gse in supported_gses]
    return citations, research_result.retrieval_events, supported_gses


def _assessment_priority(value: str) -> int:
    return {
        "pass": 3,
        "not_applicable": 2,
        "unclear": 1,
        "fail": 0,
    }.get(value, 0)


def _confidence_priority(value: str) -> int:
    return {
        "high": 2,
        "medium": 1,
        "low": 0,
    }.get(value, 0)


def _analysis_score(summary) -> tuple[int, int, int, int]:
    pass_score = sum(_assessment_priority(finding.assessment) for finding in summary.focus_results)
    confidence_score = sum(_confidence_priority(finding.confidence) for finding in summary.focus_results)
    fail_count = sum(1 for finding in summary.focus_results if finding.assessment == "fail")
    unclear_count = sum(1 for finding in summary.focus_results if finding.assessment == "unclear")
    return pass_score, confidence_score, -fail_count, -unclear_count


def _citation_count(citations: list[GuidelineCitation], gse: str) -> int:
    return sum(1 for citation in citations if citation.gse == gse)


def _choose_recommended_gse_from_analysis(
    session_state: SessionState,
    *,
    fnma_eligible: bool,
    fhlmc_eligible: bool,
    gse_analysis: dict[str, Any],
    citations: list[GuidelineCitation],
    default_if_tied: str = "fnma",
) -> tuple[str, str]:
    if fnma_eligible and not fhlmc_eligible:
        return "fnma", "FNMA is selected because the current packet supports FNMA while FHLMC is not fully supported."
    if fhlmc_eligible and not fnma_eligible:
        return "fhlmc", "FHLMC is selected because the current packet supports FHLMC while FNMA is not fully supported."

    statement_owner = (
        session_state.documents.mortgage_statement.gse_owner if session_state.documents.mortgage_statement else "unknown"
    )
    if statement_owner == "fnma" and fnma_eligible:
        return "fnma", "FNMA is selected because the current loan already appears Fannie Mae-backed and the FNMA path is supportable."
    if statement_owner == "fhlmc" and fhlmc_eligible:
        return "fhlmc", "FHLMC is selected because the current loan already appears Freddie Mac-backed and the FHLMC path is supportable."

    fnma_summary = gse_analysis.get("fnma")
    fhlmc_summary = gse_analysis.get("fhlmc")
    if fnma_summary is not None and fhlmc_summary is not None:
        fnma_score = _analysis_score(fnma_summary)
        fhlmc_score = _analysis_score(fhlmc_summary)
        if fnma_score > fhlmc_score:
            return "fnma", "FNMA is selected because its GSE analysis shows the stronger overall focus-level support across the required guideline checks."
        if fhlmc_score > fnma_score:
            return "fhlmc", "FHLMC is selected because its GSE analysis shows the stronger overall focus-level support across the required guideline checks."

    fnma_citations = _citation_count(citations, "fnma")
    fhlmc_citations = _citation_count(citations, "fhlmc")
    if fnma_citations > fhlmc_citations:
        return "fnma", "FNMA is selected because it retained more accepted guideline support for this case."
    if fhlmc_citations > fnma_citations:
        return "fhlmc", "FHLMC is selected because it retained more accepted guideline support for this case."

    if default_if_tied == "fhlmc":
        return "fhlmc", "Both FNMA and FHLMC remain equally supportable after the comparative analysis, so FHLMC is retained as the deterministic tie-break."
    return "fnma", "Both FNMA and FHLMC remain equally supportable after the comparative analysis, so FNMA is retained as the deterministic tie-break."


def _json_first_tool_calls(session_state: SessionState) -> list[ToolCallRecord]:
    outputs = session_state.calculated_outputs
    lars = session_state.lars_result
    return [
        _tool_call("calculate_uc1_uc2_outputs", {}, outputs),
        _tool_call("evaluate_lars", {}, lars.model_dump(mode="json") if lars else {}),
    ]


def _json_first_doc_status(session_state: SessionState) -> dict[str, list[str]]:
    not_required: list[str] = []
    if session_state.use_case != "uc2_pmi_removal":
        not_required.append("pmi_statement")
    return {
        "received": list(session_state.received_documents),
        "pending": list(session_state.pending_documents or session_state.missing_documents),
        "not_required": not_required,
    }


def _json_first_monthly_income(session_state: SessionState) -> float:
    return float(session_state.calculated_outputs.get("gmi") or 0.0)


def _json_first_ltv_percent(session_state: SessionState) -> float:
    return float(session_state.calculated_outputs.get("ltv_percent") or 0.0)


def _json_first_monthly_savings(session_state: SessionState) -> float:
    return float(session_state.calculated_outputs.get("total_monthly_savings") or 0.0)


def _json_first_recommended_gse(
    *,
    fnma_eligible: bool,
    fhlmc_eligible: bool,
    retrieved_gses: set[str],
) -> str:
    if fnma_eligible and not fhlmc_eligible:
        return "fnma"
    if fhlmc_eligible and not fnma_eligible:
        return "fhlmc"
    if "fnma" in retrieved_gses:
        return "fnma"
    if "fhlmc" in retrieved_gses:
        return "fhlmc"
    return "fnma"


def _json_first_reasoning_chain(
    session_state: SessionState,
    *,
    doc_status: dict[str, list[str]],
    retrieved_gses: set[str],
    fnma_eligible: bool,
    fhlmc_eligible: bool,
) -> list[str]:
    lars = session_state.lars_result
    return [
        "UC1/UC2 JSON-first packet built from deterministic screening outputs and guide_tool retrieval.",
        f"LARS decision: {lars.decision if lars else 'not evaluated'}.",
        f"Required documents received: {', '.join(doc_status['received']) or 'none'}.",
        f"Expected guideline sections retrieved for available guides: {', '.join(sorted(retrieved_gses)) or 'none'}.",
        f"FNMA eligible: {fnma_eligible}. FHLMC eligible: {fhlmc_eligible}.",
    ]


def build_json_first_recommendation_packet(
    session_state: SessionState,
    retrieval_service: RetrievalService,
    guideline_researcher: GuidelineResearcher | None = None,
    gse_analyzer: GSEAnalyzer | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> PacketBuildResult:
    packet_started = perf_counter()
    research_started = perf_counter()
    citations, retrieval_events, retrieved_gses = _guideline_artifacts(
        session_state,
        retrieval_service,
        guideline_researcher=guideline_researcher,
        progress_callback=progress_callback,
    )
    research_ms = (perf_counter() - research_started) * 1000
    if callable(progress_callback):
        progress_callback("Building recommendation packet...")
    tool_calls = _json_first_tool_calls(session_state)
    doc_status = _json_first_doc_status(session_state)
    analyzer = gse_analyzer or DeterministicGSEAnalyzer(retrieval_service)
    analysis_started = perf_counter()
    gse_analysis_models = analyzer.analyze(session_state, citations)
    analysis_ms = (perf_counter() - analysis_started) * 1000
    gse_analysis = {gse: summary.model_dump(mode="json") for gse, summary in gse_analysis_models.items()}
    fnma_eligible = bool(gse_analysis_models.get("fnma") and gse_analysis_models["fnma"].supported)
    fhlmc_eligible = bool(gse_analysis_models.get("fhlmc") and gse_analysis_models["fhlmc"].supported)
    recommended_gse, recommended_gse_reason = _choose_recommended_gse_from_analysis(
        session_state,
        fnma_eligible=fnma_eligible,
        fhlmc_eligible=fhlmc_eligible,
        gse_analysis=gse_analysis_models,
        citations=citations,
        default_if_tied=_json_first_recommended_gse(
            fnma_eligible=fnma_eligible,
            fhlmc_eligible=fhlmc_eligible,
            retrieved_gses=retrieved_gses,
        ),
    )

    packet = LoanRecommendationPacket(
        borrower_name="Borrower",
        borrower_id_token=session_state.borrower_id_token,
        use_case=session_state.use_case,
        fnma_eligible=fnma_eligible,
        fhlmc_eligible=fhlmc_eligible,
        recommended_gse=recommended_gse,
        recommended_gse_reason=recommended_gse_reason,
        qualifying_monthly_income=_json_first_monthly_income(session_state),
        ltv_percent=_json_first_ltv_percent(session_state),
        monthly_savings_estimate=_json_first_monthly_savings(session_state),
        guideline_citations=citations,
        calculations={record.tool: record for record in tool_calls},
        documentation_status=doc_status,
        reasoning_chain=_json_first_reasoning_chain(
            session_state,
            doc_status=doc_status,
            retrieved_gses=retrieved_gses,
            fnma_eligible=fnma_eligible,
            fhlmc_eligible=fhlmc_eligible,
        ),
        calculated_outputs=session_state.calculated_outputs,
        lars_result=session_state.lars_result,
        handoff_package=session_state.handoff_package,
        screening_assumptions=session_state.screening_assumptions,
        source_data_warnings=session_state.source_data_warnings,
        gse_analysis=gse_analysis_models,
    )
    guideline_review_call = _guideline_review_tool_call(
        citations=citations,
        retrieved_gses=retrieved_gses,
    )
    gse_analysis_call = _gse_analysis_tool_call(gse_analysis)
    packet_generation_call = _packet_generation_tool_call(
        "build_json_first_recommendation_packet",
        session_state=session_state,
        packet=packet,
        retrieved_gses=retrieved_gses,
    )
    tool_calls.extend([guideline_review_call, gse_analysis_call, packet_generation_call])
    logger.warning(
        "[TEMP timing] build_json_first_recommendation_packet session_id=%s research_ms=%.1f gse_analysis_ms=%.1f citations=%s retrieval_events=%s total_ms=%.1f",
        session_state.session_id,
        research_ms,
        analysis_ms,
        len(citations),
        len(retrieval_events),
        (perf_counter() - packet_started) * 1000,
    )
    return PacketBuildResult(
        packet=packet,
        retrieval_events=retrieval_events,
        tool_calls=tool_calls,
    )
