from __future__ import annotations

from typing import Any

from turborefi.schemas import FieldComparison, LoanRecommendationPacket, SessionState, VerificationReport
from turborefi.services.compliance import compute_compliance_score
from turborefi.services.guideline_research import DeterministicGuidelineResearcher, GuidelineResearcher
from turborefi.services.packet_builder import build_deterministic_loan_packet
from turborefi.services.retrieval_service import RetrievalService


def _comparison(field: str, loa_value: Any, verifier_value: Any, guideline_section: str | None = None) -> FieldComparison:
    return FieldComparison(
        field=field,
        loa_value=loa_value,
        verifier_value=verifier_value,
        match=loa_value == verifier_value,
        guideline_section=guideline_section,
        notes="" if loa_value == verifier_value else f"Mismatch on {field}.",
    )


class VerificationService:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        guideline_researcher: GuidelineResearcher | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.guideline_researcher = guideline_researcher or DeterministicGuidelineResearcher(retrieval_service)

    def build_report(
        self,
        session_state: SessionState,
        loan_packet: LoanRecommendationPacket | None = None,
    ) -> VerificationReport:
        packet = loan_packet or session_state.loa_output
        if packet is None:
            raise ValueError("A recommendation packet must exist before verification can run.")

        rebuilt = build_deterministic_loan_packet(
            session_state,
            self.retrieval_service,
            guideline_researcher=self.guideline_researcher,
        ).packet

        comparisons = [
            _comparison("borrower_name", packet.borrower_name, rebuilt.borrower_name),
            _comparison("use_case", packet.use_case, rebuilt.use_case),
            _comparison("fnma_eligible", packet.fnma_eligible, rebuilt.fnma_eligible),
            _comparison("fhlmc_eligible", packet.fhlmc_eligible, rebuilt.fhlmc_eligible),
            _comparison("recommended_gse", packet.recommended_gse, rebuilt.recommended_gse),
            _comparison(
                "qualifying_monthly_income",
                round(packet.qualifying_monthly_income, 2),
                round(rebuilt.qualifying_monthly_income, 2),
            ),
            _comparison("ltv_percent", round(packet.ltv_percent, 1), round(rebuilt.ltv_percent, 1)),
            _comparison(
                "monthly_savings_estimate",
                round(packet.monthly_savings_estimate, 2),
                round(rebuilt.monthly_savings_estimate, 2),
            ),
            _comparison(
                "documentation_status.received",
                packet.documentation_status.received,
                rebuilt.documentation_status.received,
            ),
            _comparison(
                "documentation_status.pending",
                packet.documentation_status.pending,
                rebuilt.documentation_status.pending,
            ),
        ]

        all_match = all(comparison.match for comparison in comparisons)
        failed_count = sum(1 for comparison in comparisons if not comparison.match)
        verification_status = "PASS" if all_match else "FLAG" if failed_count <= 2 else "FAIL"
        report = VerificationReport(
            verification_status=verification_status,
            field_comparisons=comparisons,
            audit_notes=[
                "Verifier rebuilt the recommendation packet deterministically from session state.",
                "Calculator outputs, documentation rules, and guideline retrieval were re-evaluated independently.",
            ],
        )
        report.compliance_score = compute_compliance_score(report)
        return report
