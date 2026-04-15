from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from turborefi.schemas import GuidelineCitation, RetrievalEvent, SessionState
from turborefi.services.guide_traversal import EvidenceValidator, TraversalEngine
from turborefi.services.retrieval_policy import RetrievalFocus, focus_definitions_for_state, required_focus_keys_for_state
from turborefi.services.retrieval_service import RetrievalService


GuidelineFocus = RetrievalFocus


@dataclass
class GuidelineResearchResult:
    citations: list[GuidelineCitation] = field(default_factory=list)
    retrieval_events: list[RetrievalEvent] = field(default_factory=list)
    covered_focuses: dict[str, set[str]] = field(default_factory=dict)

    def mark_covered(self, gse: str, focus_key: str) -> None:
        self.covered_focuses.setdefault(gse, set()).add(focus_key)

    def supported_gses(self, required_focus_keys: Iterable[str]) -> set[str]:
        required = set(required_focus_keys)
        if not required:
            return set(self.covered_focuses)
        return {
            gse
            for gse, covered in self.covered_focuses.items()
            if required.issubset(covered)
        }


class GuidelineResearcher(Protocol):
    def research(self, session_state: SessionState) -> GuidelineResearchResult: ...


class DeterministicGuidelineResearcher:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        traversal_engine: TraversalEngine | None = None,
        evidence_validator: EvidenceValidator | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.traversal_engine = traversal_engine or TraversalEngine(retrieval_service)
        self.evidence_validator = evidence_validator or EvidenceValidator()

    def research(self, session_state: SessionState) -> GuidelineResearchResult:
        result = GuidelineResearchResult()
        focuses = focus_definitions_for_state(session_state)

        for gse in self.retrieval_service.available_guides():
            for focus in focuses:
                traversal = self.traversal_engine.collect_candidates(gse=gse, focus=focus)
                result.retrieval_events.extend(traversal.retrieval_events)

                accepted = []
                seen_sections: set[str] = set()
                for candidate in traversal.candidates:
                    evidence = self.evidence_validator.validate(candidate, focus)
                    if evidence is None or evidence.section_id in seen_sections:
                        continue
                    accepted.append(evidence)
                    seen_sections.add(evidence.section_id)

                if not accepted:
                    continue

                result.mark_covered(gse, focus.key)
                for evidence in accepted:
                    result.citations.append(
                        GuidelineCitation(
                            section=evidence.section_id,
                            gse=gse,
                            finding=f"{evidence.title} supports {focus.label}.",
                            focus_key=focus.key,
                            focus_label=focus.label,
                            title=evidence.title,
                            why_selected=evidence.why_selected,
                        )
                    )

        return result


__all__ = [
    "DeterministicGuidelineResearcher",
    "GuidelineFocus",
    "GuidelineResearchResult",
    "GuidelineResearcher",
    "focus_definitions_for_state",
    "required_focus_keys_for_state",
]
