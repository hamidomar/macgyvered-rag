from __future__ import annotations

import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Protocol

from turborefi.agents.common import build_base_agent_kwargs
from turborefi.config import Settings
from turborefi.prompts import GSE_ANALYSIS_INSTRUCTIONS
from turborefi.schemas import GSEAnalysisSummary, GSEFocusFinding, GuidelineCitation, SessionState
from turborefi.services.information_firewall import build_loa_visible_session
from turborefi.services.retrieval_policy import focus_definitions_for_state
from turborefi.services.retrieval_service import RetrievalService


logger = logging.getLogger(__name__)

MAX_PRIMARY_TEXT_CHARS = 1200
MAX_REFERENCE_TEXT_CHARS = 350
MAX_REFERENCE_SECTIONS = 2
MAX_LINK_IDS = 6


class GSEAnalyzer(Protocol):
    def analyze(
        self,
        session_state: SessionState,
        citations: list[GuidelineCitation],
    ) -> dict[str, GSEAnalysisSummary]: ...


def _group_citations(citations: list[GuidelineCitation]) -> dict[tuple[str, str], list[GuidelineCitation]]:
    grouped: dict[tuple[str, str], list[GuidelineCitation]] = defaultdict(list)
    for citation in citations:
        if citation.gse is None or citation.focus_key is None:
            continue
        grouped[(citation.gse, citation.focus_key)].append(citation)
    return grouped


def _borrower_fact_labels(state: SessionState) -> list[str]:
    outputs = state.calculated_outputs or {}
    labels: list[str] = []
    if state.borrower_facts.tenure_months is not None:
        labels.append(f"tenure_months={state.borrower_facts.tenure_months}")
    if state.borrower_facts.single_income_source is not None:
        labels.append(f"single_income_source={state.borrower_facts.single_income_source}")
    if state.borrower_facts.property_type:
        labels.append(f"property_type={state.borrower_facts.property_type}")
    if state.borrower_facts.pmi_type:
        labels.append(f"pmi_type={state.borrower_facts.pmi_type}")
    if state.borrower_facts.has_second_lien is not None:
        labels.append(f"has_second_lien={state.borrower_facts.has_second_lien}")
    if isinstance(outputs.get("gmi"), (int, float)):
        labels.append(f"gmi={outputs['gmi']}")
    if isinstance(outputs.get("ltv_percent"), (int, float)):
        labels.append(f"ltv_percent={outputs['ltv_percent']}")
    if state.lars_result is not None:
        labels.append(f"lars_decision={state.lars_result.decision}")
    return labels


def _effective_ltv_percent(state: SessionState) -> float:
    outputs = state.calculated_outputs or {}
    if isinstance(outputs.get("ltv_percent"), (int, float)):
        return float(outputs["ltv_percent"])
    statement = state.documents.mortgage_statement
    if (
        statement is not None
        and statement.loan_balance > 0
        and statement.original_property_value
        and statement.original_property_value > 0
    ):
        return round((statement.loan_balance / statement.original_property_value) * 100, 1)
    return 0.0


def _has_established_income(state: SessionState) -> bool:
    outputs = state.calculated_outputs or {}
    if isinstance(outputs.get("gmi"), (int, float)) and float(outputs["gmi"]) > 0:
        return True
    return bool(state.documents.paystubs or state.documents.w2s or state.documents.schedule_c)


class DeterministicGSEAnalyzer:
    def __init__(self, retrieval_service: RetrievalService) -> None:
        self.retrieval_service = retrieval_service

    def _deterministic_focus_result(
        self,
        state: SessionState,
        *,
        gse: str,
        focus_key: str,
        focus_label: str,
        citations: list[GuidelineCitation],
        required: bool,
    ) -> GSEFocusFinding:
        section_ids = [citation.section for citation in citations]
        fact_labels = _borrower_fact_labels(state)
        docs_ready = not state.missing_documents
        automated = bool(state.lars_result and state.lars_result.decision == "AUTOMATED")
        ltv_percent = _effective_ltv_percent(state)
        has_income = _has_established_income(state)

        if not citations:
            return GSEFocusFinding(
                gse=gse,  # type: ignore[arg-type]
                focus_key=focus_key,
                focus_label=focus_label,
                section_ids=[],
                assessment="fail" if required else "not_applicable",
                rule_summary="No supporting guideline sections were retrieved for this focus.",
                decision_description="The system could not validate this focus against the selected GSE because no accepted sections were retrieved.",
                borrower_facts_used=fact_labels,
                confidence="low",
                source="deterministic",
            )

        title_or_label = citations[0].title or focus_label
        assessment = "pass"
        decision_description = f"The borrower profile and current screening outputs satisfy {focus_label} for {gse.upper()}."

        if focus_key == "refinance_eligibility":
            if state.source_mode == "received_json_uc1_uc2" and not automated:
                assessment = "fail"
                decision_description = "The file did not remain in the automated path, so refinance eligibility is not supportable for automated GSE analysis."
        elif focus_key == "income_stability":
            if not has_income:
                assessment = "fail"
                decision_description = "Qualifying income was not established from the borrower documents."
            elif state.borrower_facts.tenure_months is not None and state.borrower_facts.tenure_months < 24:
                assessment = "unclear"
                decision_description = "Income is present, but short employment tenure makes stable-income support less certain."
        elif focus_key == "employment_documentation":
            if state.income_type == "w2" and not docs_ready:
                assessment = "fail"
                decision_description = "Required W-2 employment documents are incomplete."
            elif state.income_type == "self_employed" and not docs_ready:
                assessment = "fail"
                decision_description = "Required self-employed tax documents are incomplete."
        elif focus_key == "self_employed_documentation":
            if not docs_ready:
                assessment = "fail"
                decision_description = "Schedule C documentation is incomplete for self-employed analysis."
        elif focus_key == "self_employed_income_analysis":
            if not has_income:
                assessment = "fail"
                decision_description = "Self-employed qualifying income could not be established from the available tax data."
        elif focus_key == "property_value_and_mi":
            threshold = 75.0 if state.use_case == "uc2_pmi_removal" else 80.0
            if ltv_percent > threshold:
                assessment = "fail"
                decision_description = f"The packet LTV of {ltv_percent:.1f}% exceeds the supported threshold for this flow."
            elif state.use_case == "uc2_pmi_removal" and state.borrower_facts.pmi_type is None:
                assessment = "unclear"
                decision_description = "Property value support is present, but PMI treatment remains unclear."

        if not docs_ready and focus_key in {
            "income_stability",
            "employment_documentation",
            "self_employed_documentation",
            "self_employed_income_analysis",
            "property_value_and_mi",
        }:
            assessment = "fail"
            decision_description = "The borrower file is not document-complete for this focus."

        return GSEFocusFinding(
            gse=gse,  # type: ignore[arg-type]
            focus_key=focus_key,
            focus_label=focus_label,
            section_ids=section_ids,
            assessment=assessment,  # type: ignore[arg-type]
            rule_summary=f"{title_or_label} supports {focus_label}.",
            decision_description=decision_description,
            borrower_facts_used=fact_labels,
            confidence="high" if assessment in {"pass", "fail"} else "medium",
            source="deterministic",
        )

    def analyze(
        self,
        session_state: SessionState,
        citations: list[GuidelineCitation],
    ) -> dict[str, GSEAnalysisSummary]:
        grouped = _group_citations(citations)
        results: dict[str, GSEAnalysisSummary] = {}
        focus_defs = focus_definitions_for_state(session_state)

        for gse in self.retrieval_service.available_guides():
            focus_results: list[GSEFocusFinding] = []
            for focus in focus_defs:
                focus_results.append(
                    self._deterministic_focus_result(
                        session_state,
                        gse=gse,
                        focus_key=focus.key,
                        focus_label=focus.label,
                        citations=grouped.get((gse, focus.key), []),
                        required=focus.required,
                    )
                )

            required_results = [
                finding for finding in focus_results if next((focus for focus in focus_defs if focus.key == finding.focus_key), None)
            ]
            required_findings = [
                finding for finding in required_results if any(focus.key == finding.focus_key and focus.required for focus in focus_defs)
            ]
            supported = all(finding.assessment == "pass" for finding in required_findings)
            blockers = [
                finding.focus_label
                for finding in required_findings
                if finding.assessment in {"fail", "unclear"}
            ]
            overall_reason = (
                "All required focus areas are supported."
                if supported
                else "Support is limited by: " + ", ".join(blockers)
            )
            results[gse] = GSEAnalysisSummary(
                gse=gse,  # type: ignore[arg-type]
                supported=supported,
                overall_reason=overall_reason,
                focus_results=focus_results,
            )
        return results


class AgenticGSEAnalyzer:
    def __init__(self, settings: Settings, retrieval_service: RetrievalService) -> None:
        self.settings = settings
        self.retrieval_service = retrieval_service
        self.fallback = DeterministicGSEAnalyzer(retrieval_service)

    def _build_agent(self):
        if not os.getenv("OPENAI_API_KEY"):
            return None
        try:
            from agno.agent import Agent
        except ModuleNotFoundError:
            return None

        kwargs = build_base_agent_kwargs(
            settings=self.settings,
            name="TurboRefi GSE Analysis",
            description="Structured interpreter for GSE eligibility analysis by focus area.",
            model_id=self.settings.openai_model_loa,
            instructions=GSE_ANALYSIS_INSTRUCTIONS,
            tools=[],
            session_state={},
            response_model=GSEAnalysisSummary,
        )
        kwargs.pop("show_tool_calls", None)
        return Agent(**kwargs)

    def _section_payload(self, gse: str, section_id: str) -> dict[str, object]:
        payload = self.retrieval_service.get_section_with_references(section_id=section_id, gse=gse, depth=1)
        return payload if isinstance(payload, dict) else {"primary": section_id, "sections": []}

    def _truncate_text(self, value: object, limit: int) -> str:
        if not isinstance(value, str):
            return ""
        normalized = " ".join(value.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3].rstrip() + "..."

    def _compact_section(self, section: dict[str, object], *, text_limit: int) -> dict[str, object]:
        return {
            "section_id": section.get("section_id"),
            "title": section.get("title"),
            "text_excerpt": self._truncate_text(section.get("text"), text_limit),
            "text_length": section.get("text_length"),
            "references": list(section.get("references") or [])[:MAX_LINK_IDS],
            "cited_by": list(section.get("cited_by") or [])[:MAX_LINK_IDS],
        }

    def _compact_section_payload(self, gse: str, section_id: str) -> dict[str, object]:
        payload = self._section_payload(gse, section_id)
        sections = payload.get("sections")
        if not isinstance(sections, list):
            sections = []

        primary_section = next(
            (
                section
                for section in sections
                if isinstance(section, dict) and section.get("section_id") == section_id
            ),
            sections[0] if sections and isinstance(sections[0], dict) else {},
        )
        related_sections = [
            section
            for section in sections
            if isinstance(section, dict) and section.get("section_id") != section_id
        ][:MAX_REFERENCE_SECTIONS]

        return {
            "primary": payload.get("primary"),
            "total_text_length": payload.get("total_text_length"),
            "primary_section": self._compact_section(primary_section, text_limit=MAX_PRIMARY_TEXT_CHARS)
            if isinstance(primary_section, dict)
            else {"section_id": section_id},
            "related_sections": [
                self._compact_section(section, text_limit=MAX_REFERENCE_TEXT_CHARS) for section in related_sections
            ],
        }

    def _dump_prompt(self, *, session_id: str, gse: str, prompt: str) -> Path | None:
        try:
            prompt_dir = self.settings.traces_dir / "gse_analysis_prompts"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            path = prompt_dir / f"{session_id}_{gse}_{timestamp}.txt"
            path.write_text(prompt, encoding="utf-8")
            return path
        except Exception:
            logger.exception(
                "[TEMP timing] Failed to dump GSE analysis prompt for session_id=%s gse=%s",
                session_id,
                gse,
            )
            return None

    def _analyze_single_gse(
        self,
        *,
        session_state: SessionState,
        gse: str,
        summary: GSEAnalysisSummary,
        grouped: dict[tuple[str, str], list[GuidelineCitation]],
        visible_state: dict[str, object],
        focus_defs,
    ) -> GSEAnalysisSummary:
        gse_started = perf_counter()
        section_expand_started = perf_counter()
        sections_by_focus = {}
        for finding in summary.focus_results:
            focus_citations = grouped.get((gse, finding.focus_key), [])
            sections_by_focus[finding.focus_key] = [
                self._compact_section_payload(gse, citation.section) for citation in focus_citations
            ]
        section_expand_ms = (perf_counter() - section_expand_started) * 1000
        prompt = (
            "Assess one GSE path for a TurboRefi borrower.\n"
            f"GSE: {gse}\n"
            f"Borrower profile: {visible_state}\n"
            f"Retrieved guideline sections by focus: {sections_by_focus}\n"
            f"Deterministic baseline summary: {summary.model_dump(mode='json')}\n"
            "Return a structured GSEAnalysisSummary. Preserve the same gse and focus_results ordering. "
            "Only change the semantic interpretation if the provided guideline text supports that change."
        )
        prompt_path = self._dump_prompt(session_id=session_state.session_id, gse=gse, prompt=prompt)
        agent = self._build_agent()
        if agent is None:
            logger.warning(
                "[TEMP timing] AgenticGSEAnalyzer per-gse fallback session_id=%s gse=%s elapsed_ms=%.1f",
                session_state.session_id,
                gse,
                (perf_counter() - gse_started) * 1000,
            )
            return summary
        try:
            agent_started = perf_counter()
            response = agent.run(prompt)
            agent_ms = (perf_counter() - agent_started) * 1000
            content = getattr(response, "content", response)
            upgraded_summary = (
                content if isinstance(content, GSEAnalysisSummary) else GSEAnalysisSummary.model_validate(content)
            )
            upgraded_summary.gse = summary.gse
            normalized_focus_results: list[GSEFocusFinding] = []
            for focus in summary.focus_results:
                candidate = next(
                    (result for result in upgraded_summary.focus_results if result.focus_key == focus.focus_key),
                    None,
                )
                if candidate is None:
                    normalized_focus_results.append(focus)
                    continue
                candidate.gse = focus.gse
                candidate.focus_key = focus.focus_key
                candidate.focus_label = focus.focus_label
                candidate.section_ids = focus.section_ids
                candidate.source = "agentic"
                normalized_focus_results.append(candidate)
            required_results = [
                finding
                for finding in normalized_focus_results
                if any(focus.key == finding.focus_key and focus.required for focus in focus_defs)
            ]
            supported = all(finding.assessment == "pass" for finding in required_results)
            blockers = [
                finding.focus_label
                for finding in required_results
                if finding.assessment in {"fail", "unclear"}
            ]
            result = GSEAnalysisSummary(
                gse=summary.gse,
                supported=supported,
                overall_reason=(
                    "All required focus areas are supported."
                    if supported
                    else "Support is limited by: " + ", ".join(blockers)
                ),
                focus_results=normalized_focus_results,
            )
            logger.warning(
                "[TEMP timing] AgenticGSEAnalyzer gse=%s session_id=%s citations=%s section_expand_ms=%.1f agent_ms=%.1f total_ms=%.1f prompt_chars=%s prompt_dump=%s",
                gse,
                session_state.session_id,
                sum(len(grouped.get((gse, finding.focus_key), [])) for finding in summary.focus_results),
                section_expand_ms,
                agent_ms,
                (perf_counter() - gse_started) * 1000,
                len(prompt),
                str(prompt_path) if prompt_path else "n/a",
            )
            return result
        except Exception:
            logger.exception(
                "[TEMP timing] AgenticGSEAnalyzer failed for gse=%s session_id=%s after_ms=%.1f",
                gse,
                session_state.session_id,
                (perf_counter() - gse_started) * 1000,
            )
            return summary

    def analyze(
        self,
        session_state: SessionState,
        citations: list[GuidelineCitation],
    ) -> dict[str, GSEAnalysisSummary]:
        analysis_started = perf_counter()
        baseline = self.fallback.analyze(session_state, citations)
        focus_defs = focus_definitions_for_state(session_state)
        agent = self._build_agent()
        if agent is None:
            logger.warning(
                "[TEMP timing] AgenticGSEAnalyzer fallback only: session_id=%s citations=%s elapsed_ms=%.1f",
                session_state.session_id,
                len(citations),
                (perf_counter() - analysis_started) * 1000,
            )
            return baseline

        visible_state = build_loa_visible_session(session_state)
        grouped = _group_citations(citations)
        if len(baseline) == 1:
            gse, summary = next(iter(baseline.items()))
            baseline[gse] = self._analyze_single_gse(
                session_state=session_state,
                gse=gse,
                summary=summary,
                grouped=grouped,
                visible_state=visible_state,
                focus_defs=focus_defs,
            )
        else:
            with ThreadPoolExecutor(max_workers=min(2, len(baseline))) as executor:
                future_map = {
                    executor.submit(
                        self._analyze_single_gse,
                        session_state=session_state,
                        gse=gse,
                        summary=summary,
                        grouped=grouped,
                        visible_state=visible_state,
                        focus_defs=focus_defs,
                    ): gse
                    for gse, summary in baseline.items()
                }
                for future in as_completed(future_map):
                    gse = future_map[future]
                    try:
                        baseline[gse] = future.result()
                    except Exception:
                        logger.exception(
                            "[TEMP timing] AgenticGSEAnalyzer future failed for gse=%s session_id=%s",
                            gse,
                            session_state.session_id,
                        )
        logger.warning(
            "[TEMP timing] AgenticGSEAnalyzer total session_id=%s citations=%s elapsed_ms=%.1f",
            session_state.session_id,
            len(citations),
            (perf_counter() - analysis_started) * 1000,
        )
        return baseline
