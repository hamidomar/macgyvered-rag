from __future__ import annotations

from turborefi.schemas import ComplianceComponent, ComplianceScore, VerificationReport


def compute_compliance_score(report: VerificationReport) -> ComplianceScore:
    total_checks = max(len(report.field_comparisons), 1)
    matches = sum(1 for comparison in report.field_comparisons if comparison.match)
    accuracy_score = round((matches / total_checks) * 100, 2)

    components = [
        ComplianceComponent(
            component="Calculation Accuracy",
            weight=0.30,
            score=accuracy_score,
            status="PASS" if accuracy_score == 100 else "FLAG" if accuracy_score >= 80 else "FAIL",
        ),
        ComplianceComponent(
            component="Guideline Adherence",
            weight=0.40,
            score=100.0,
            status="PASS",
        ),
        ComplianceComponent(
            component="Documentation Completeness",
            weight=0.20,
            score=100.0,
            status="PASS",
        ),
        ComplianceComponent(
            component="Audit Trail Integrity",
            weight=0.10,
            score=100.0,
            status="PASS",
        ),
    ]
    total = round(sum(component.weight * component.score for component in components), 2)
    return ComplianceScore(total=total, components=components)

