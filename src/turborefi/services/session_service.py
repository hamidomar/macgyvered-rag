from __future__ import annotations

import json
import logging
from inspect import signature
from pathlib import Path
from typing import Any

from turborefi.agents.loan_officer import build_loan_officer_agent
from turborefi.agents.verifier import build_verifier_agent
from turborefi.config import Settings, load_settings
from turborefi.extraction.service import DocumentExtractionService
from turborefi.schemas import (
    ConversationMessage,
    LoanRecommendationPacket,
    MortgageStatementData,
    ScheduleCData,
    SessionState,
    ToolCallRecord,
    VerificationReport,
    W2Data,
    PaystubData,
)
from turborefi.services.packet_builder import build_deterministic_loan_packet
from turborefi.services.guideline_research import DeterministicGuidelineResearcher, GuidelineResearcher
from turborefi.services.intake_service import (
    IntakeUpdate,
    build_guided_follow_up,
    build_initial_intake_prompt,
    intake_labels,
    missing_document_labels,
)
from turborefi.services.intake_resolver import AgentIntakeResolver, IntakeResolver
from turborefi.services.retrieval_service import RetrievalService
from turborefi.services.session_state import (
    add_document_to_session,
    build_upload_session_state,
    refresh_session_state,
    session_to_agent_state,
)
from turborefi.services.verification_service import VerificationService


logger = logging.getLogger(__name__)


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _guide_limitations(state: SessionState) -> list[str]:
    limitations: list[str] = []
    for event in state.retrieval_events:
        lowered = event.result_summary.lower()
        if "incompatible with this single-family refinance workflow" in lowered:
            message = f"{event.gse.upper()} guide support is unavailable because the configured index is not compatible with this workflow."
            limitations.append(message)
        elif "no guide index configured" in lowered:
            message = f"{event.gse.upper()} guide support is unavailable because no compatible index is configured."
            limitations.append(message)
    return _unique_preserving_order(limitations)


def _response_text(run_response: Any) -> str:
    for attr in ("content", "response", "text"):
        value = getattr(run_response, attr, None)
        if isinstance(value, str):
            return value
    return str(run_response)


class TurboRefiSessionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        retrieval_service: RetrievalService | None = None,
        extraction_service: DocumentExtractionService | None = None,
        loa_agent=None,
        verifier_agent=None,
        intake_resolver: IntakeResolver | None = None,
        guideline_researcher: GuidelineResearcher | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.retrieval_service = retrieval_service or RetrievalService(
            repo_root=self.settings.repo_root,
            fnma_index_dir=self.settings.fnma_index_dir,
            fhlmc_index_dir=self.settings.fhlmc_index_dir,
        )
        self.extraction_service = extraction_service or DocumentExtractionService(settings=self.settings)
        self.guideline_researcher = guideline_researcher or DeterministicGuidelineResearcher(self.retrieval_service)
        initial_state = SessionState()
        self.loa_agent = loa_agent or build_loan_officer_agent(
            settings=self.settings,
            retrieval_service=self.retrieval_service,
            session_state=initial_state,
        )
        self.verifier_agent = verifier_agent or build_verifier_agent(
            settings=self.settings,
            retrieval_service=self.retrieval_service,
            session_state=initial_state,
        )
        self.verification_service = VerificationService(self.retrieval_service)
        self.intake_resolver = intake_resolver or AgentIntakeResolver(self.settings)

    def _session_path(self, session_id: str) -> Path:
        return self.settings.sessions_dir / f"{session_id}.json"

    def _save_state(self, state: SessionState) -> None:
        path = self._session_path(state.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state.model_dump(mode="json"), indent=2), encoding="utf-8")

    def session_exists(self, session_id: str) -> bool:
        return self._session_path(session_id).exists()

    def get_state(self, session_id: str) -> SessionState:
        path = self._session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Unknown session: {session_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SessionState.model_validate(payload)

    def list_states(self) -> list[SessionState]:
        states: list[SessionState] = []
        for path in sorted(self.settings.sessions_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                states.append(SessionState.model_validate(payload))
            except Exception:
                logger.exception("Failed to load TurboRefi session from %s", path)
        states.sort(key=lambda state: state.updated_at, reverse=True)
        return states

    def delete_session(self, session_id: str) -> None:
        path = self._session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Unknown session: {session_id}")
        path.unlink()

    def _append_conversation_message(
        self,
        state: SessionState,
        *,
        role: str,
        content: str,
        tool_trace: list[dict[str, Any]] | None = None,
    ) -> None:
        state.conversation.append(
            ConversationMessage(
                role=role,
                content=content,
                tool_trace=tool_trace or [],
            )
        )

    def _append_exchange(
        self,
        state: SessionState,
        *,
        user_content: str,
        agent_content: str,
        tool_trace: list[dict[str, Any]] | None = None,
    ) -> None:
        self._append_conversation_message(state, role="user", content=user_content)
        self._append_conversation_message(
            state,
            role="agent",
            content=agent_content,
            tool_trace=tool_trace,
        )

    def _upload_message(self, doc_type: str, filename: str | None = None) -> str:
        label = {
            "mortgage_statement": "mortgage statement",
            "paystub": "paystub",
            "w2": "W-2",
            "schedule_c": "Schedule C",
        }.get(doc_type, doc_type.replace("_", " "))
        if filename:
            return f"Uploaded {label}: {filename}"
        return f"Uploaded {label}"

    def _tool_call_entry(self, record: ToolCallRecord) -> dict[str, Any]:
        return {
            "tool": record.tool,
            "arguments": record.inputs,
            "result": record.result,
        }

    def _retrieval_trace_entries(self, state: SessionState) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for event in state.retrieval_events:
            result_summary = event.result_summary
            lowered = result_summary.lower()
            if lowered.startswith("no guide index configured") or "not found" in lowered:
                status = "error"
            elif lowered.startswith("no matches found"):
                status = "empty"
            else:
                status = "ok"
            arguments: dict[str, Any] = {"gse": event.gse}
            if event.tool == "search_guideline_titles":
                arguments["query"] = event.query
            elif event.tool in {"list_guideline_contents", "list_guide_contents"}:
                arguments["path"] = event.query or None
            else:
                arguments["section_id"] = event.query
            entries.append(
                {
                    "tool": event.tool,
                    "arguments": arguments,
                    "result": {
                        "status": status,
                        "summary": result_summary,
                    },
                }
            )
        return entries

    def _verifier_trace_entry(self, report: VerificationReport) -> dict[str, Any]:
        return {
            "tool": "verify_recommendation_packet",
            "arguments": {},
            "result": report.model_dump(mode="json"),
        }

    def _visible_tool_trace(
        self,
        build_tool_calls: list[ToolCallRecord],
        state: SessionState,
        report: VerificationReport | None = None,
    ) -> list[dict[str, Any]]:
        entries = self._retrieval_trace_entries(state)
        entries.extend(self._tool_call_entry(record) for record in build_tool_calls)
        if report is not None:
            entries.append(self._verifier_trace_entry(report))
        return entries

    def _sync_agent_session_state(self, agent, state: SessionState) -> None:
        update_fn = getattr(agent, "update_session_state", None)
        if not callable(update_fn):
            return

        payload = session_to_agent_state(state)
        params = signature(update_fn).parameters
        try:
            if "session_state_updates" in params:
                update_fn(session_id=state.session_id, session_state_updates=payload)
            else:
                update_fn(state.session_id, payload)
        except Exception as exc:
            # Agno only allows updating session state after a backing session exists.
            # For brand-new TurboRefi uploads we may not have an AgentOS session yet.
            if "Session not found" in str(exc):
                logger.warning(
                    "Skipping agent session-state sync for session_id=%s because AgentOS session does not exist yet",
                    state.session_id,
                )
                return
            raise

    def _sync_all_agent_state(self, state: SessionState) -> None:
        self._sync_agent_session_state(self.loa_agent, state)
        self._sync_agent_session_state(self.verifier_agent, state)

    def _run_agent(self, agent, state: SessionState, message: str) -> str:
        response = agent.run(
            message,
            session_id=state.session_id,
            session_state=session_to_agent_state(state),
        )
        return _response_text(response)

    def _missing_docs_message(self, state: SessionState) -> str:
        if not state.missing_documents:
            return "I have what I need to continue the assessment."
        labels = ", ".join(missing_document_labels(state.missing_documents))
        if state.income_type == "self_employed":
            return (
                "I reviewed the file and I still need the remaining Schedule C tax-year documents "
                f"before I can complete the refinance assessment: {labels}."
            )
        return (
            "I reviewed the file and I still need the remaining employment documents before I can continue: "
            f"{labels}."
        )

    def _intake_message(self, state: SessionState) -> str:
        if not state.intake_pending:
            return "I have the intake details I need."
        labels = ", ".join(intake_labels(state.intake_pending))
        return f"I still need a few intake details before I request the final documents: {labels}."

    def _packet_summary_message(self, state: SessionState) -> str:
        packet = state.loa_output
        if packet is None:
            return "I have enough information to proceed with the assessment."

        supported_sections = ", ".join(
            f"{citation.gse.upper()} {citation.section}" if citation.gse else citation.section
            for citation in packet.guideline_citations
        )
        limitations = _guide_limitations(state)

        summary = (
            f"You are {'eligible' if packet.fnma_eligible else 'not eligible'} for the recommended {packet.recommended_gse.upper()} refinance path. "
            f"Your qualifying monthly income is ${packet.qualifying_monthly_income:,.2f} and your LTV is {packet.ltv_percent:.1f}%. "
            f"The recommendation is supported by {supported_sections or 'no guide citations'}."
        )
        if packet.documentation_status.pending:
            summary = (
                f"{summary} Pending pre-closing items: "
                f"{', '.join(packet.documentation_status.pending)}."
            )
        if limitations:
            summary = f"{summary} {' '.join(limitations)}"
        if state.verifier_output is None:
            return summary
        return (
            f"{summary} Independent verification status: {state.verifier_output.verification_status}. "
            f"Compliance score: {state.verifier_output.compliance_score.total:.1f}."
            if state.verifier_output.compliance_score is not None
            else f"{summary} Independent verification status: {state.verifier_output.verification_status}."
        )

    def _workflow_response(
        self,
        state: SessionState,
        *,
        event: str,
        intake_update: IntakeUpdate | None = None,
    ) -> str:
        if state.current_phase == "awaiting_intake":
            if event == "mortgage_statement":
                return build_initial_intake_prompt(state)
            return build_guided_follow_up(
                state,
                changed_fields=intake_update.changed_fields if intake_update else set(),
            )

        if state.current_phase == "awaiting_docs":
            return build_guided_follow_up(
                state,
                changed_fields=intake_update.changed_fields if intake_update else set(),
            )

        if event != "assessment_ready":
            return self._missing_docs_message(state)

        packet = state.loa_output
        citation_lines = []
        if packet is not None:
            for citation in packet.guideline_citations:
                prefix = citation.gse.upper() if citation.gse is not None else "GUIDE"
                citation_lines.append(f"- {prefix} {citation.section}: {citation.finding}")

        try:
            citations_text = "\n".join(citation_lines) if citation_lines else "- none"
            limitation_lines = _guide_limitations(state)
            limitations_text = "\n".join(f"- {line}" for line in limitation_lines) if limitation_lines else "- none"
            return self._run_agent(
                self.loa_agent,
                state,
                "The refinance recommendation packet and verification report are now available in session state. "
                "Summarize the recommendation, guideline support, and verification status conversationally. "
                "Requirements:\n"
                "1. Start with a short, user-friendly explanation of the recommendation in plain English.\n"
                "2. State FNMA eligibility, FHLMC eligibility, recommended path, income, and LTV.\n"
                "3. Cite the exact relied-on section IDs, but keep the citation explanation compact and natural.\n"
                "4. Do not use formal report headings or checklist formatting.\n"
                "5. If a guide source was unavailable or incompatible, mention that briefly in one sentence.\n"
                "6. Mention verification status and any pending pre-closing items.\n"
                "7. Respond in plain English with no JSON.\n\n"
                f"Relied-on citations:\n{citations_text}\n\n"
                f"Guide limitations:\n{limitations_text}",
            )
        except Exception:
            return self._packet_summary_message(state)

    def _apply_packet_if_ready(self, state: SessionState) -> list[dict[str, Any]]:
        if state.intake_pending or state.missing_documents:
            state.loa_output = None
            state.verifier_output = None
            return []

        build_result = build_deterministic_loan_packet(
            state,
            self.retrieval_service,
            guideline_researcher=self.guideline_researcher,
        )
        state.loa_output = build_result.packet
        state.retrieval_events = build_result.retrieval_events
        state.tool_calls = build_result.tool_calls
        state.verifier_output = self.verification_service.build_report(state, build_result.packet)
        refresh_session_state(state)
        return self._visible_tool_trace(
            build_result.tool_calls,
            state,
            state.verifier_output,
        )

    def create_session_from_mortgage_data(
        self,
        mortgage_statement: MortgageStatementData,
        *,
        session_name: str | None = None,
        session_id: str | None = None,
    ) -> tuple[str, str, SessionState, list[dict[str, Any]]]:
        state = build_upload_session_state(
            mortgage_statement,
            borrower_name=mortgage_statement.borrower_name,
            session_name=session_name or mortgage_statement.borrower_name or "Mortgage Statement",
            session_id=session_id,
        )
        tool_trace = self._apply_packet_if_ready(state)
        event = "assessment_ready" if state.loa_output is not None else "mortgage_statement"
        response_text = self._workflow_response(state, event=event)
        self._append_exchange(
            state,
            user_content=self._upload_message("mortgage_statement", filename=session_name),
            agent_content=response_text,
            tool_trace=tool_trace,
        )
        self._save_state(state)
        self._sync_all_agent_state(state)
        return state.session_id, response_text, state, tool_trace

    def upload_secondary_document(
        self,
        session_id: str,
        doc_type: str,
        document: PaystubData | W2Data | ScheduleCData,
        *,
        filename: str | None = None,
    ) -> tuple[str, SessionState, list[dict[str, Any]]]:
        state = self.get_state(session_id)
        state = add_document_to_session(state, doc_type=doc_type, document=document)
        tool_trace = self._apply_packet_if_ready(state)
        event = "assessment_ready" if state.loa_output is not None else "supporting_document_missing"
        response_text = self._workflow_response(state, event=event)
        self._append_exchange(
            state,
            user_content=self._upload_message(doc_type, filename=filename),
            agent_content=response_text,
            tool_trace=tool_trace,
        )
        self._save_state(state)
        self._sync_all_agent_state(state)
        return response_text, state, tool_trace

    def send_message(self, session_id: str, message: str) -> tuple[str, SessionState, list[dict[str, Any]]]:
        state = self.get_state(session_id)
        packet_was_ready = state.loa_output is not None
        if not packet_was_ready:
            intake_resolution = self.intake_resolver.resolve(state, message)
            state = refresh_session_state(intake_resolution.state)
            tool_trace = [*intake_resolution.tool_trace, *self._apply_packet_if_ready(state)]

            if state.loa_output is not None:
                response_text = self._workflow_response(state, event="assessment_ready")
                self._append_exchange(
                    state,
                    user_content=message,
                    agent_content=response_text,
                    tool_trace=tool_trace,
                )
                self._save_state(state)
                self._sync_all_agent_state(state)
                return response_text, state, tool_trace

            response_text = build_guided_follow_up(
                state,
                changed_fields=intake_resolution.changed_fields,
                clarification_questions=intake_resolution.clarification_questions,
            )
            self._append_exchange(
                state,
                user_content=message,
                agent_content=response_text,
                tool_trace=tool_trace,
            )
            self._save_state(state)
            self._sync_all_agent_state(state)
            return response_text, state, tool_trace

        self._sync_all_agent_state(state)
        try:
            response_text = self._run_agent(self.loa_agent, state, message)
        except Exception:
            if state.loa_output is not None:
                response_text = self._packet_summary_message(state)
            elif state.intake_pending:
                response_text = self._intake_message(state)
            else:
                response_text = self._missing_docs_message(state)
        self._append_exchange(state, user_content=message, agent_content=response_text)
        self._save_state(state)
        return response_text, state, []

    def get_result(self, session_id: str) -> LoanRecommendationPacket:
        state = self.get_state(session_id)
        if state.loa_output is None:
            tool_trace = self._apply_packet_if_ready(state)
            if state.loa_output is None:
                if state.intake_pending:
                    raise ValueError(
                        "Recommendation packet is not ready yet. Missing intake details: "
                        + ", ".join(intake_labels(state.intake_pending))
                    )
                raise ValueError("Recommendation packet is not ready yet.")
            if tool_trace:
                self._save_state(state)
                self._sync_all_agent_state(state)
        return state.loa_output

    def verify_session(self, session_id: str) -> tuple[VerificationReport, SessionState]:
        state = self.get_state(session_id)
        if state.loa_output is None:
            self.get_result(session_id)
            state = self.get_state(session_id)
        report = self.verification_service.build_report(state, state.loa_output)
        state.verifier_output = report
        refresh_session_state(state)
        self._save_state(state)
        self._sync_all_agent_state(state)
        return report, state
