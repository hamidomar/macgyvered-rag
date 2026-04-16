from __future__ import annotations

import json
import logging
import os
from inspect import signature
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from turborefi.agents.json_first_conversation import build_json_first_conversation_agent
from turborefi.agents.loan_officer import build_loan_officer_agent
from turborefi.agents.verifier import build_verifier_agent
from turborefi.config import Settings, load_settings
from turborefi.extraction.service import DocumentExtractionService
from turborefi.schemas import (
    ClosingDisclosureData,
    ConversationMessage,
    DocumentSet,
    IdentityDocumentData,
    InsuranceDeclarationData,
    LoanRecommendationPacket,
    MortgageStatementData,
    ScheduleCData,
    SessionState,
    TaxBillData,
    ToolCallRecord,
    VerificationReport,
    W2Data,
    PaystubData,
    PmiStatementData,
)
from turborefi.services.conversation_flows import (
    automated_ready_message,
    document_upload_follow_up,
    next_question,
    opening_message,
)
from turborefi.services.full_application_resolver import (
    AgenticFullApplicationResolver,
    FullApplicationResolver,
    is_full_application_decision_pending,
)
from turborefi.services.minimal_assessment import refresh_minimal_uc1_uc2_assessment
from turborefi.services.packet_builder import (
    build_deterministic_loan_packet,
    build_json_first_recommendation_packet,
)
from turborefi.services.received_input import parse_received_json
from turborefi.services.guideline_research import DeterministicGuidelineResearcher, GuidelineResearcher
from turborefi.services.gse_analysis import AgenticGSEAnalyzer, GSEAnalyzer
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
from turborefi.services.uc1_uc2_intake_resolver import AgenticUC1UC2IntakeResolver, UC1UC2IntakeResolver
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


def _looks_like_recommendation_why_question(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    if "why" not in lowered:
        return False
    return any(token in lowered for token in ("fnma", "fhlmc", "selected", "chosen", "recommend", "path"))


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
        json_first_conversation_agent=None,
        intake_resolver: IntakeResolver | None = None,
        uc1_uc2_intake_resolver: UC1UC2IntakeResolver | None = None,
        full_application_resolver: FullApplicationResolver | None = None,
        guideline_researcher: GuidelineResearcher | None = None,
        gse_analyzer: GSEAnalyzer | None = None,
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
        if json_first_conversation_agent is not None:
            self.json_first_conversation_agent = json_first_conversation_agent
        elif os.getenv("OPENAI_API_KEY"):
            try:
                self.json_first_conversation_agent = build_json_first_conversation_agent(self.settings)
            except ModuleNotFoundError:
                self.json_first_conversation_agent = None
            except Exception:
                logger.exception("Failed to initialize JSON-first conversation agent; falling back to deterministic copy.")
                self.json_first_conversation_agent = None
        else:
            self.json_first_conversation_agent = None
        self.verification_service = VerificationService(self.retrieval_service)
        self.intake_resolver = intake_resolver or AgentIntakeResolver(self.settings)
        self.uc1_uc2_intake_resolver = uc1_uc2_intake_resolver or AgenticUC1UC2IntakeResolver(self.settings)
        self.full_application_resolver = full_application_resolver or AgenticFullApplicationResolver(self.settings)
        self.gse_analyzer = gse_analyzer or AgenticGSEAnalyzer(self.settings, self.retrieval_service)

    @staticmethod
    def _full_application_packet_summary(state: SessionState) -> str:
        packet = state.loa_output
        if packet is None:
            return "The recommendation packet is ready for review."

        recommended_gse = packet.recommended_gse.upper()
        savings = packet.monthly_savings_estimate
        ltv_percent = packet.ltv_percent
        income = packet.qualifying_monthly_income
        grouped_citations: dict[str, dict[str, list[str]]] = {}
        for citation in packet.guideline_citations:
            if citation.gse is None:
                continue
            gse = citation.gse.upper()
            focus_label = citation.focus_label or "guideline support"
            grouped_citations.setdefault(gse, {})
            grouped_citations[gse].setdefault(focus_label, [])
            if citation.section not in grouped_citations[gse][focus_label]:
                grouped_citations[gse][focus_label].append(citation.section)
        status_text = (
            "Both FNMA and FHLMC appear supportable on the preliminary screen. "
            if packet.fnma_eligible and packet.fhlmc_eligible
            else "FNMA appears supportable on the preliminary screen. "
            if packet.fnma_eligible
            else "FHLMC appears supportable on the preliminary screen. "
            if packet.fhlmc_eligible
            else "Neither GSE is fully supportable on the preliminary screen yet. "
        )
        citation_parts: list[str] = []
        for gse in ("FNMA", "FHLMC"):
            focus_map = grouped_citations.get(gse, {})
            if not focus_map:
                continue
            focus_parts = [
                f"{focus.lower()} ({', '.join(sections[:2])})"
                for focus, sections in list(focus_map.items())[:3]
                if sections
            ]
            if focus_parts:
                citation_parts.append(f"{gse} support covers " + "; ".join(focus_parts))
        citation_text = f"{' '.join(citation_parts)}." if citation_parts else ""
        doc_text = ""
        if not packet.documentation_status.pending:
            received_count = len(packet.documentation_status.received)
            doc_text = f" The packet is document-complete with {received_count} received item(s)."
        return (
            f"Recommendation summary: {status_text}{recommended_gse} is the current best fit. "
            f"Qualifying monthly income is ${income:,.0f}, packet LTV is {ltv_percent:.1f}%, "
            f"and estimated monthly savings are ${savings:,.0f}. {TurboRefiSessionService._recommended_gse_reason(state)}"
            f"{doc_text} {citation_text}".strip()
        )

    @staticmethod
    def _recommended_gse_reason(state: SessionState) -> str:
        packet = state.loa_output
        if packet is None:
            return "A recommendation rationale is not available until the packet is built."
        if packet.recommended_gse_reason:
            return packet.recommended_gse_reason
        if state.handoff_package is not None:
            return "This file is referred for manual review, so no automated GSE recommendation is selected."
        if packet.fnma_eligible and not packet.fhlmc_eligible:
            return "FNMA is selected because the current packet supports FNMA while FHLMC is not fully supported."
        if packet.fhlmc_eligible and not packet.fnma_eligible:
            return "FHLMC is selected because the current packet supports FHLMC while FNMA is not fully supported."
        statement_owner = (
            state.documents.mortgage_statement.gse_owner if state.documents.mortgage_statement is not None else "unknown"
        )
        if statement_owner == "fnma" and packet.fnma_eligible:
            return "FNMA is selected because the current loan already appears Fannie Mae-backed and the FNMA path is supportable."
        if statement_owner == "fhlmc" and packet.fhlmc_eligible:
            return "FHLMC is selected because the current loan already appears Freddie Mac-backed and the FHLMC path is supportable."
        if packet.fnma_eligible and packet.fhlmc_eligible and packet.recommended_gse == "fnma":
            return "Both FNMA and FHLMC are supportable on this screen, and FNMA is the current tie-break default in the automated packet builder."
        if packet.fnma_eligible and packet.fhlmc_eligible and packet.recommended_gse == "fhlmc":
            return "Both FNMA and FHLMC are supportable on this screen, and FHLMC is the current selected path."
        return f"{packet.recommended_gse.upper()} is the only currently selected path from the packet builder."

    @staticmethod
    def _packet_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
        if not rows:
            return ""
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join("---" for _ in headers) + " |"
        body_rows = ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join([header_row, separator_row, *body_rows])

    def _full_application_packet_details(self, state: SessionState) -> str:
        packet = state.loa_output
        if packet is None:
            return "The recommendation packet is being prepared."

        overview_rows = [
            ["Recommended path", packet.recommended_gse.upper()],
            ["Selection rationale", self._recommended_gse_reason(state)],
            ["FNMA support", "Supported" if packet.fnma_eligible else "Not supported"],
            ["FHLMC support", "Supported" if packet.fhlmc_eligible else "Not supported"],
            ["Qualifying monthly income", f"${packet.qualifying_monthly_income:,.0f}"],
            ["Packet LTV", f"{packet.ltv_percent:.1f}%"],
            ["Estimated monthly savings", f"${packet.monthly_savings_estimate:,.0f}"],
            ["Received documents", ", ".join(packet.documentation_status.received) or "none"],
            ["Pending items", ", ".join(packet.documentation_status.pending) or "none"],
        ]

        analysis_rows_by_gse: dict[str, list[list[str]]] = {"FNMA": [], "FHLMC": []}
        for gse, analysis in packet.gse_analysis.items():
            analysis_rows_by_gse.setdefault(gse.upper(), [])
            for finding in analysis.focus_results:
                analysis_rows_by_gse[gse.upper()].append(
                    [
                        finding.focus_label,
                        ", ".join(finding.section_ids) or "--",
                        finding.decision_description,
                    ]
                )

        sections: list[str] = [
            "### Packet Overview",
            self._packet_markdown_table(["Field", "Value"], overview_rows),
        ]

        for gse in ("FNMA", "FHLMC"):
            rows = analysis_rows_by_gse.get(gse, [])
            if not rows:
                continue
            sections.extend(
                [
                    f"### {gse} Guideline Basis",
                    self._packet_markdown_table(["Purpose", "Section", "Decision basis"], rows),
                ]
            )

        if packet.reasoning_chain:
            sections.append("### Packet Notes")
            sections.extend(f"- {step}" for step in packet.reasoning_chain)

        return "\n\n".join(section for section in sections if section)

    def _full_application_response(self, state: SessionState, intent: str) -> str:
        if intent == "proceed":
            state.full_application_intent = "proceed"
            state.current_phase = "complete"
            state.state_machine_state = "S7_DECISION"
            if state.loa_output is None:
                state.loa_output = self.get_result(state.session_id)
            return (
                "Understood. I marked this case as ready to proceed to the full application. "
                "The preliminary screen is complete, the document packet is assembled, and the recommendation details are below.\n\n"
                f"{self._full_application_packet_summary(state)}\n\n"
                f"{self._full_application_packet_details(state)}"
            )
        if intent == "decline":
            state.full_application_intent = "decline"
            state.current_phase = "complete"
            state.state_machine_state = "S7_DECISION"
            return (
                "Understood. I will leave the case at the completed preliminary-screen stage. "
                "You can return later if you want to proceed to the full application."
            )
        return (
            "I have the preliminary screen complete. Would you like to proceed to the full application?"
        )

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
            "identity": "government ID",
            "tax_bill": "property tax bill",
            "insurance": "insurance declaration",
            "pmi_statement": "PMI statement",
            "closing_disclosure": "closing disclosure",
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

    def _json_first_screening_trace(self, state: SessionState) -> list[dict[str, Any]]:
        screening_calls = [
            ToolCallRecord(
                tool="calculate_uc1_uc2_outputs",
                inputs={},
                result=state.calculated_outputs or {},
            ),
            ToolCallRecord(
                tool="evaluate_lars",
                inputs={},
                result=state.lars_result.model_dump(mode="json") if state.lars_result else {},
            ),
        ]
        state.tool_calls = screening_calls
        return [self._tool_call_entry(record) for record in screening_calls]

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
        if state.source_mode == "received_json_uc1_uc2":
            return
        self._sync_agent_session_state(self.loa_agent, state)
        self._sync_agent_session_state(self.verifier_agent, state)

    def _run_agent(self, agent, state: SessionState, message: str, *, agent_session_id: str | None = None) -> str:
        response = agent.run(
            message,
            session_id=agent_session_id or state.session_id,
            session_state=session_to_agent_state(state),
        )
        return _response_text(response)

    def _json_first_fact_highlights(self, state: SessionState, changed_fields: list[str] | None) -> list[str]:
        if not changed_fields:
            return []
        facts = state.borrower_facts
        priority = {
            "fico_range": 0,
            "fico_uncertain": 1,
            "tenure_months": 2,
            "property_type": 3,
            "single_income_source": 4,
            "pmi_type": 5,
            "purchase_price": 6,
            "down_payment_amount": 7,
            "has_second_lien": 8,
            "factual_uncertainty": 9,
        }
        highlights: list[str] = []
        for field in sorted(changed_fields, key=lambda name: priority.get(name, 99)):
            if field == "fico_range" and facts.fico_range:
                label = facts.fico_range.replace("_", " to ").replace("760_plus", "760 and above")
                highlights.append(f"I have your credit estimate in the {label} range.")
            elif field == "fico_uncertain" and facts.fico_uncertain:
                highlights.append("I noted that the credit score estimate is approximate.")
            elif field == "tenure_months" and facts.tenure_months:
                years = facts.tenure_months / 12
                highlights.append(f"I also have about {years:.0f} years with your current employer.")
            elif field == "single_income_source" and facts.single_income_source is True:
                highlights.append("I have this as your regular job being your only income source.")
            elif field == "single_income_source" and facts.single_income_source is False:
                highlights.append("I noted that there is additional income beyond the primary job.")
            elif field == "property_type" and facts.property_type:
                property_labels = {
                    "sfr": "single-family home",
                    "townhome": "townhome",
                    "condo": "condo",
                }
                highlights.append(f"I have the property as a {property_labels.get(facts.property_type, facts.property_type)}.")
            elif field == "pmi_type" and facts.pmi_type:
                if facts.pmi_type == "borrower_paid":
                    highlights.append("I noted that the PMI is borrower-paid monthly.")
                elif facts.pmi_type == "lender_paid":
                    highlights.append("I noted that the PMI appears to be lender-paid and built into the rate.")
            elif field == "purchase_price" and facts.purchase_price:
                highlights.append(f"I have the purchase price at ${facts.purchase_price:,.0f}.")
            elif field == "down_payment_amount" and facts.down_payment_amount:
                highlights.append(f"I have the down payment at about ${facts.down_payment_amount:,.0f}.")
            elif field == "has_second_lien" and facts.has_second_lien is False:
                highlights.append("I have this as a first mortgage only, with no second lien or HELOC.")
            elif field == "has_second_lien" and facts.has_second_lien is True:
                highlights.append("I noted that there is a second lien or HELOC on the property.")
            elif field == "factual_uncertainty" and facts.factual_uncertainties:
                last_uncertain = facts.factual_uncertainties[-1].replace("_", " ")
                highlights.append(f"I noted that the {last_uncertain} answer is uncertain.")
        return _unique_preserving_order(highlights)

    def _json_first_default_response(
        self,
        state: SessionState,
        *,
        event: str,
        user_message: str | None = None,
        changed_fields: list[str] | None = None,
        doc_type: str | None = None,
        decision_intent: str | None = None,
    ) -> str:
        if event == "opening":
            return opening_message(state)
        if event == "document_upload":
            if doc_type is None:
                return next_question(state)
            base = document_upload_follow_up(state, doc_type)
            if state.missing_documents:
                return base
            if is_full_application_decision_pending(state):
                return f"Thanks, I’ve added your {doc_type.replace('_', ' ')}. {automated_ready_message(state)}"
            return f"Thanks, I’ve added your {doc_type.replace('_', ' ')}. {next_question(state)}"
        if event == "full_application_decision":
            return self._full_application_response(state, decision_intent or "unclear")
        if event == "completed_follow_up":
            if state.full_application_intent == "proceed":
                if _looks_like_recommendation_why_question(user_message):
                    return (
                        f"{self._recommended_gse_reason(state)}\n\n"
                        f"{self._full_application_packet_details(state)}"
                    )
                return (
                    "We are already in the full-application-ready state for this file. "
                    "Here is the current recommendation packet and guide support.\n\n"
                    f"{self._full_application_packet_summary(state)}\n\n"
                    f"{self._full_application_packet_details(state)}"
                )
            return next_question(state)

        base = next_question(state)
        highlights = self._json_first_fact_highlights(state, changed_fields)
        if not highlights:
            return base
        opener = "Thanks, that helps. "
        return f"{opener}{' '.join(highlights[:4])} {base}".strip()

    def _json_first_prompt(
        self,
        state: SessionState,
        *,
        event: str,
        default_response: str,
        user_message: str | None = None,
        changed_fields: list[str] | None = None,
        doc_type: str | None = None,
        decision_intent: str | None = None,
    ) -> str:
        received_docs = ", ".join(state.received_documents) or "none"
        missing_docs = ", ".join(state.missing_documents) or "none"
        facts = self._json_first_fact_highlights(state, changed_fields)
        outputs = state.calculated_outputs or {}
        lars = state.lars_result
        packet = state.loa_output
        citation_lines: list[str] = []
        if packet is not None:
            for citation in packet.guideline_citations:
                gse = citation.gse.upper() if citation.gse else "GUIDE"
                citation_lines.append(f"- {gse} {citation.section}: {citation.finding}")
        packet_summary = self._full_application_packet_summary(state) if packet is not None else "not available"
        output_summary_parts = [
            f"LTV {outputs.get('ltv_percent'):.1f}%." if isinstance(outputs.get("ltv_percent"), (int, float)) else "",
            f"Gross monthly income ${outputs.get('gmi'):,.0f}." if isinstance(outputs.get("gmi"), (int, float)) else "",
            f"Monthly savings ${outputs.get('total_monthly_savings'):,.0f}."
            if isinstance(outputs.get("total_monthly_savings"), (int, float))
            else "",
        ]
        output_summary = " ".join(part for part in output_summary_parts if part) or "none"
        return (
            "Draft the next borrower-facing assistant message for TurboRefi's JSON-first UC1/UC2 screening flow.\n"
            f"Conversation event: {event}\n"
            f"Latest borrower message: {user_message or 'n/a'}\n"
            f"Uploaded document: {doc_type or 'none'}\n"
            f"Decision intent: {decision_intent or 'n/a'}\n"
            f"Use case: {state.use_case}\n"
            f"Current phase: {state.current_phase}\n"
            f"Received documents: {received_docs}\n"
            f"Missing documents: {missing_docs}\n"
            f"Important facts to acknowledge if helpful: {' '.join(facts) or 'none'}\n"
            f"LARS status: {lars.decision if lars else 'not evaluated'}"
            f"{f' at score {lars.final_score}' if lars else ''}\n"
            f"Calculated output highlights: {output_summary}\n"
            f"Recommendation packet summary: {packet_summary}\n"
            f"Guide citations:\n{chr(10).join(citation_lines) if citation_lines else '- none'}\n\n"
            "Workflow requirement: keep the factual meaning aligned with this required response shape, but rewrite it more naturally.\n"
            f"Required response shape: {default_response}\n\n"
            "If the required response shape contains markdown tables, preserve those tables exactly. "
            "Write one short paragraph in plain English before the tables when appropriate. "
            "Make it feel like a human loan officer. Do not mention tools, internal workflow, or factor codes. "
            "Do not ask more than one new question."
        )

    def _json_first_response(
        self,
        state: SessionState,
        *,
        event: str,
        user_message: str | None = None,
        changed_fields: list[str] | None = None,
        doc_type: str | None = None,
        decision_intent: str | None = None,
    ) -> str:
        started = perf_counter()
        default_response = self._json_first_default_response(
            state,
            event=event,
            user_message=user_message,
            changed_fields=changed_fields,
            doc_type=doc_type,
            decision_intent=decision_intent,
        )
        if self.json_first_conversation_agent is None:
            logger.warning(
                "[TEMP timing] json_first_response fallback session_id=%s event=%s elapsed_ms=%.1f",
                state.session_id,
                event,
                (perf_counter() - started) * 1000,
            )
            return default_response
        prompt = self._json_first_prompt(
            state,
            event=event,
            default_response=default_response,
            user_message=user_message,
            changed_fields=changed_fields,
            doc_type=doc_type,
            decision_intent=decision_intent,
        )
        try:
            response = self._run_agent(
                self.json_first_conversation_agent,
                state,
                prompt,
                agent_session_id=f"{state.session_id}:json-first-conversation",
            )
            logger.warning(
                "[TEMP timing] json_first_response agentic session_id=%s event=%s prompt_chars=%s elapsed_ms=%.1f",
                state.session_id,
                event,
                len(prompt),
                (perf_counter() - started) * 1000,
            )
            return response
        except Exception:
            logger.exception("JSON-first conversational response generation failed for session_id=%s", state.session_id)
            logger.warning(
                "[TEMP timing] json_first_response agentic_failed session_id=%s event=%s elapsed_ms=%.1f",
                state.session_id,
                event,
                (perf_counter() - started) * 1000,
            )
            return default_response

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

    def _apply_packet_if_ready(
        self,
        state: SessionState,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        started = perf_counter()
        if state.source_mode == "received_json_uc1_uc2":
            refresh_minimal_uc1_uc2_assessment(state)
            screening_trace = self._json_first_screening_trace(state)
            if state.handoff_package is None and state.missing_documents:
                state.loa_output = None
                state.retrieval_events = []
                return screening_trace
            if state.handoff_package is not None:
                state.loa_output = None
                state.retrieval_events = []
                return screening_trace
            if state.lars_result is None or state.lars_result.decision != "AUTOMATED":
                state.loa_output = None
                state.retrieval_events = []
                return screening_trace
            if state.full_application_intent != "proceed":
                state.loa_output = None
                state.retrieval_events = []
                return screening_trace
            build_result = build_json_first_recommendation_packet(
                state,
                self.retrieval_service,
                guideline_researcher=self.guideline_researcher,
                gse_analyzer=self.gse_analyzer,
                progress_callback=progress_callback,
            )
            state.loa_output = build_result.packet
            state.retrieval_events = build_result.retrieval_events
            state.tool_calls = build_result.tool_calls
            logger.warning(
                "[TEMP timing] apply_packet_if_ready json_first session_id=%s intent=%s total_ms=%.1f",
                state.session_id,
                state.full_application_intent,
                (perf_counter() - started) * 1000,
            )
            return self._visible_tool_trace(build_result.tool_calls, state, None)

        if state.intake_pending or state.missing_documents:
            state.loa_output = None
            state.verifier_output = None
            return []

        build_result = build_deterministic_loan_packet(
            state,
            self.retrieval_service,
            guideline_researcher=self.guideline_researcher,
            gse_analyzer=self.gse_analyzer,
            progress_callback=progress_callback,
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

    def create_session_from_received_json(
        self,
        payload: dict[str, Any],
        *,
        new_rate: float | None = None,
        session_name: str | None = None,
        session_id: str | None = None,
    ) -> tuple[str, str, SessionState, list[dict[str, Any]]]:
        effective_new_rate = new_rate if new_rate is not None else self.settings.screening_new_rate
        parsed = parse_received_json(payload, new_rate=effective_new_rate)
        state = SessionState(
            session_id=session_id or SessionState().session_id,
            session_name=session_name or "Received JSON",
            borrower_name="Borrower",
            borrower_id_token=parsed.borrower_id_token,
            source_mode="received_json_uc1_uc2",
            income_type="w2",
            documents=DocumentSet(mortgage_statement=parsed.mortgage_statement),
            received_mortgage=parsed.received_mortgage,
            screening_assumptions=parsed.screening_assumptions,
            source_data_warnings=parsed.warnings,
            unsupported_reason=parsed.unsupported_reason,
        )
        if parsed.received_mortgage.property_type:
            state.borrower_facts.property_type = parsed.received_mortgage.property_type
        if parsed.received_mortgage.purchase_price:
            state.borrower_facts.purchase_price = parsed.received_mortgage.purchase_price
        if parsed.received_mortgage.pmi_monthly and parsed.received_mortgage.pmi_monthly > 0:
            state.borrower_facts.pmi_type = "borrower_paid"

        from turborefi.services.use_case_router import route_uc1_uc2

        routing = route_uc1_uc2(parsed.received_mortgage, state.borrower_facts)
        state.use_case = routing.use_case
        if routing.deferred_reason:
            state.unsupported_reason = routing.deferred_reason

        state = refresh_session_state(state)
        tool_trace = self._apply_packet_if_ready(state)
        response_text = self._json_first_response(state, event="opening")
        self._append_exchange(
            state,
            user_content="Received JSON input",
            agent_content=response_text,
            tool_trace=tool_trace,
        )
        self._save_state(state)
        self._sync_all_agent_state(state)
        return state.session_id, response_text, state, tool_trace

    def upload_document_json(
        self,
        session_id: str,
        doc_type: str,
        payload: dict[str, Any],
    ) -> tuple[str, SessionState, list[dict[str, Any]]]:
        state = self.get_state(session_id)
        if doc_type == "paystub":
            document = PaystubData.model_validate(payload)
        elif doc_type == "w2":
            document = W2Data.model_validate(payload)
        elif doc_type == "schedule_c":
            document = ScheduleCData.model_validate(payload)
        elif doc_type == "identity":
            document = IdentityDocumentData.model_validate(payload).model_dump(mode="json")
        elif doc_type == "tax_bill":
            document = TaxBillData.model_validate(payload).model_dump(mode="json")
        elif doc_type == "insurance":
            document = InsuranceDeclarationData.model_validate(payload).model_dump(mode="json")
        elif doc_type == "pmi_statement":
            document = PmiStatementData.model_validate(payload).model_dump(mode="json")
        elif doc_type == "closing_disclosure":
            document = ClosingDisclosureData.model_validate(payload).model_dump(mode="json")
        else:
            document = payload
        state = add_document_to_session(state, doc_type=doc_type, document=document)
        tool_trace = self._apply_packet_if_ready(state)
        response_text = next_question(state) if state.source_mode != "received_json_uc1_uc2" else self._json_first_response(
            state,
            event="document_upload",
            doc_type=doc_type,
        )
        if state.source_mode != "received_json_uc1_uc2":
            response_text = self._workflow_response(
                state,
                event="assessment_ready" if state.loa_output is not None else "supporting_document_missing",
            )
        self._append_exchange(
            state,
            user_content=self._upload_message(doc_type),
            agent_content=response_text,
            tool_trace=tool_trace,
        )
        self._save_state(state)
        self._sync_all_agent_state(state)
        return response_text, state, tool_trace

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
        document: PaystubData | W2Data | ScheduleCData | dict[str, Any],
        *,
        filename: str | None = None,
    ) -> tuple[str, SessionState, list[dict[str, Any]]]:
        state = self.get_state(session_id)
        state = add_document_to_session(state, doc_type=doc_type, document=document)
        tool_trace = self._apply_packet_if_ready(state)
        if state.source_mode == "received_json_uc1_uc2":
            response_text = self._json_first_response(
                state,
                event="document_upload",
                doc_type=doc_type,
            )
        else:
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

    def send_message(
        self,
        session_id: str,
        message: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, SessionState, list[dict[str, Any]]]:
        started = perf_counter()
        state = self.get_state(session_id)
        logger.warning(
            "TurboRefi send_message session_id=%s source_mode=%s phase=%s full_application_intent=%s missing_documents=%s message=%r",
            session_id,
            state.source_mode,
            state.current_phase,
            state.full_application_intent,
            list(state.missing_documents),
            message,
        )
        if state.source_mode == "received_json_uc1_uc2":
            if state.full_application_intent is not None and not state.missing_documents and state.handoff_package is None:
                response_text = self._json_first_response(
                    state,
                    event="completed_follow_up",
                    user_message=message,
                )
                self._append_exchange(
                    state,
                    user_content=message,
                    agent_content=response_text,
                    tool_trace=[],
                )
                self._save_state(state)
                self._sync_all_agent_state(state)
                return response_text, state, []

            if is_full_application_decision_pending(state):
                logger.warning(
                    "TurboRefi full application decision pending session_id=%s message=%r",
                    state.session_id,
                    message,
                )
                decision_started = perf_counter()
                decision_resolution = self.full_application_resolver.resolve(state, message)
                decision_ms = (perf_counter() - decision_started) * 1000
                tool_trace = [*decision_resolution.tool_trace]
                packet_ms = 0.0
                if decision_resolution.intent == "proceed":
                    packet_started = perf_counter()
                    state.full_application_intent = "proceed"
                    tool_trace.extend(self._apply_packet_if_ready(state, progress_callback=progress_callback))
                    packet_ms = (perf_counter() - packet_started) * 1000
                response_started = perf_counter()
                response_text = self._json_first_response(
                    state,
                    event="full_application_decision",
                    user_message=message,
                    decision_intent=decision_resolution.intent,
                )
                response_ms = (perf_counter() - response_started) * 1000
                logger.warning(
                    "[TEMP timing] send_message full_application_decision session_id=%s intent=%s decision_ms=%.1f packet_ms=%.1f response_ms=%.1f total_ms=%.1f",
                    state.session_id,
                    decision_resolution.intent,
                    decision_ms,
                    packet_ms,
                    response_ms,
                    (perf_counter() - started) * 1000,
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

            intake_resolution = self.uc1_uc2_intake_resolver.resolve(state, message)
            state = refresh_session_state(intake_resolution.state)
            tool_trace = [
                *intake_resolution.tool_trace,
                *self._apply_packet_if_ready(state, progress_callback=progress_callback),
            ]
            response_text = self._json_first_response(
                state,
                event="intake_follow_up",
                user_message=message,
                changed_fields=intake_resolution.changed_fields,
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

        packet_was_ready = state.loa_output is not None
        if not packet_was_ready:
            intake_resolution = self.intake_resolver.resolve(state, message)
            state = refresh_session_state(intake_resolution.state)
            tool_trace = [
                *intake_resolution.tool_trace,
                *self._apply_packet_if_ready(state, progress_callback=progress_callback),
            ]

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
        if state.source_mode == "received_json_uc1_uc2":
            refresh_minimal_uc1_uc2_assessment(state)
            if state.handoff_package is not None:
                raise ValueError("Recommendation packet is not created for referred cases.")
            if state.full_application_intent != "proceed":
                raise ValueError(
                    "Recommendation packet is available after the borrower elects to proceed to the full application."
                )
            if state.loa_output is None:
                build_result = build_json_first_recommendation_packet(
                    state,
                    self.retrieval_service,
                    guideline_researcher=self.guideline_researcher,
                    gse_analyzer=self.gse_analyzer,
                )
                state.loa_output = build_result.packet
                state.retrieval_events = build_result.retrieval_events
                state.tool_calls = build_result.tool_calls
            self._save_state(state)
            self._sync_all_agent_state(state)
            return state.loa_output

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
