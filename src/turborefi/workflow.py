from __future__ import annotations

from typing import Any

from turborefi.config import Settings, load_settings
from turborefi.schemas import BorrowerCase
from turborefi.services.audit_log import write_trace
from turborefi.services.packet_builder import (
    build_deterministic_loan_packet,
    build_fixture_assessment_result,
    build_verification_result,
)
from turborefi.services.retrieval_service import RetrievalService
from turborefi.services.session_state import build_session_state
from turborefi.services.verification_service import VerificationService
from turborefi.tools.case_tools import CaseRepository


class TurboRefiWorkflow:
    def __init__(
        self,
        settings: Settings | None = None,
        retrieval_service: RetrievalService | None = None,
        case_repository: CaseRepository | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.retrieval_service = retrieval_service or RetrievalService(
            repo_root=self.settings.repo_root,
            fnma_index_dir=self.settings.fnma_index_dir,
            fhlmc_index_dir=self.settings.fhlmc_index_dir,
        )
        self.verification_service = VerificationService(self.retrieval_service)
        self.case_repository = case_repository or CaseRepository(self.settings.mock_cases_dir)

    def list_cases(self) -> list[str]:
        return self.case_repository.list_cases()

    def get_case_summary(self, case_id: str) -> dict[str, Any]:
        case = self.case_repository.load_case(case_id)
        return {
            "case_id": case.case_id,
            "borrower_name": case.borrower_name,
            "use_case": case.use_case,
            "income_type": case.income_type,
            "received_documents": case.documents.received_categories(),
            "notes": case.notes,
        }

    def run_fixture_assessment(self, case_id: str) -> dict[str, Any]:
        case = self.case_repository.load_case(case_id)
        session_state = build_session_state(case)
        try:
            build_result = build_deterministic_loan_packet(session_state, self.retrieval_service)
            packet = build_result.packet
            session_state.loa_output = packet
            session_state.retrieval_events = build_result.retrieval_events
            session_state.tool_calls = build_result.tool_calls
        except Exception as exc:
            return {
                "case_id": case.case_id,
                "session_id": session_state.session_id,
                "error": f"{type(exc).__name__}: {exc}",
                "received_documents": session_state.received_documents,
                "missing_documents": session_state.missing_documents,
            }

        trace_payload = build_fixture_assessment_result(
            borrower_case=case,
            session_state=session_state,
            loan_packet=packet,
        )
        trace_path = write_trace(
            traces_dir=self.settings.traces_dir,
            session_id=session_state.session_id,
            trace_name=f"{case.case_id}_loa_assessment",
            payload=trace_payload,
        )
        trace_payload["trace_file"] = str(trace_path)
        return trace_payload

    def run_fixture_verification(self, case_id: str) -> dict[str, Any]:
        case = self.case_repository.load_case(case_id)
        session_state = build_session_state(case)

        try:
            build_result = build_deterministic_loan_packet(session_state, self.retrieval_service)
            session_state.loa_output = build_result.packet
            session_state.retrieval_events = build_result.retrieval_events
            session_state.tool_calls = build_result.tool_calls
            report = self.verification_service.build_report(session_state, build_result.packet)
            session_state.verifier_output = report
        except Exception as exc:
            return {
                "case_id": case.case_id,
                "session_id": session_state.session_id,
                "error": f"{type(exc).__name__}: {exc}",
            }

        trace_payload = build_verification_result(
            borrower_case=case,
            session_state=session_state,
            verification_payload=report.model_dump(mode="json"),
        )
        trace_path = write_trace(
            traces_dir=self.settings.traces_dir,
            session_id=session_state.session_id,
            trace_name=f"{case.case_id}_verification",
            payload=trace_payload,
        )
        trace_payload["trace_file"] = str(trace_path)
        return trace_payload
