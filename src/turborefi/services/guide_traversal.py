from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from turborefi.schemas import RetrievalEvent
from turborefi.services.retrieval_policy import RetrievalFocus, TraversalBranchHint
from turborefi.services.retrieval_service import RetrievalService


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _phrase_score(text: str, phrases: tuple[str, ...]) -> int:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return 0

    text_tokens = set(normalized_text.split())
    score = 0
    for phrase in phrases:
        normalized_phrase = _normalize_text(phrase)
        if not normalized_phrase:
            continue
        if normalized_phrase in normalized_text:
            score += max(4, len(normalized_phrase.split()) * 2)
            continue

        phrase_tokens = set(normalized_phrase.split())
        overlap = len(text_tokens & phrase_tokens)
        if overlap == len(phrase_tokens) and overlap > 0:
            score += overlap * 2
        elif overlap >= min(2, len(phrase_tokens)):
            score += overlap
    return score


def _list_summary(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No entries found."
    if len(results) == 1 and "error" in results[0]:
        return str(results[0]["error"])
    previews: list[str] = []
    for entry in results[:4]:
        entry_id = entry.get("id") or entry.get("section_id") or "unknown"
        title = entry.get("title") or "untitled"
        previews.append(f"{entry_id}: {title}")
    return "; ".join(previews)


def _search_summary(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No matches found."
    if len(results) == 1 and "error" in results[0]:
        return str(results[0]["error"])
    previews: list[str] = []
    for entry in results[:4]:
        section_id = entry.get("section_id") or entry.get("id") or "unknown"
        title = entry.get("title") or "untitled"
        previews.append(f"{section_id}: {title}")
    return "; ".join(previews)


def _section_summary(section: dict[str, Any]) -> str:
    if "error" in section:
        return str(section["error"])
    if "note" in section:
        note = section.get("note") or "non-leaf section"
        children = section.get("children") or []
        return f"{note} ({len(children)} children)"
    section_id = section.get("section_id") or "unknown"
    title = section.get("title") or "untitled"
    return f"{section_id}: {title}"


def _reference_summary(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return str(payload["error"])
    primary = payload.get("primary") or "unknown"
    sections = payload.get("sections") or []
    related = max(len(sections) - 1, 0)
    return f"{primary}: reviewed {related} related sections"


def _entry_id(entry: dict[str, Any]) -> str | None:
    value = entry.get("id") or entry.get("section_id")
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class TraversalCandidate:
    section_id: str
    title: str
    gse: str
    focus_key: str
    section: dict[str, Any]
    references_payload: dict[str, Any] | None
    branch_path: tuple[str, ...]
    selection_terms: tuple[str, ...]
    source: str
    why_selected: str


@dataclass(frozen=True)
class GuidelineEvidence:
    section_id: str
    title: str
    gse: str
    focus_key: str
    why_selected: str
    support_strength: str
    references_followed: tuple[str, ...] = ()


@dataclass
class TraversalResult:
    candidates: list[TraversalCandidate] = field(default_factory=list)
    retrieval_events: list[RetrievalEvent] = field(default_factory=list)


@dataclass
class _TraversalRun:
    retrieval_events: list[RetrievalEvent] = field(default_factory=list)
    cache: dict[tuple[Any, ...], Any] = field(default_factory=dict)


class TraversalEngine:
    def __init__(self, retrieval_service: RetrievalService) -> None:
        self.retrieval_service = retrieval_service

    def collect_candidates(self, gse: str, focus: RetrievalFocus) -> TraversalResult:
        run = _TraversalRun()
        candidates: list[TraversalCandidate] = []
        seen_sections: set[str] = set()

        for branch_hint in focus.branch_hints_by_gse.get(gse, ()):
            candidate = self._candidate_from_branch_hint(gse=gse, focus=focus, branch_hint=branch_hint, run=run)
            if candidate is None or candidate.section_id in seen_sections:
                continue
            candidates.append(candidate)
            seen_sections.add(candidate.section_id)
            if len(candidates) >= focus.max_sections_per_gse:
                return TraversalResult(candidates=candidates, retrieval_events=run.retrieval_events)

        for query in focus.fallback_queries_by_gse.get(gse, ()):
            candidate = self._candidate_from_search(gse=gse, focus=focus, query=query, run=run, seen_sections=seen_sections)
            if candidate is None or candidate.section_id in seen_sections:
                continue
            candidates.append(candidate)
            seen_sections.add(candidate.section_id)
            if len(candidates) >= focus.max_sections_per_gse:
                break

        return TraversalResult(candidates=candidates, retrieval_events=run.retrieval_events)

    def _record_event(self, run: _TraversalRun, *, gse: str, tool: str, query: str, summary: str) -> None:
        run.retrieval_events.append(
            RetrievalEvent(
                gse=gse,
                tool=tool,
                query=query,
                result_summary=summary,
            )
        )

    def _list_contents(self, *, gse: str, path: str | None, run: _TraversalRun) -> list[dict[str, Any]]:
        cache_key = ("list", gse, path or "")
        if cache_key not in run.cache:
            result = self.retrieval_service.list_contents(gse=gse, path=path)
            run.cache[cache_key] = result
            self._record_event(
                run,
                gse=gse,
                tool="list_guide_contents",
                query=path or "",
                summary=_list_summary(result),
            )
        return run.cache[cache_key]

    def _get_section(self, *, gse: str, section_id: str, run: _TraversalRun) -> dict[str, Any]:
        cache_key = ("section", gse, section_id)
        if cache_key not in run.cache:
            result = self.retrieval_service.get_section(section_id=section_id, gse=gse)
            run.cache[cache_key] = result
            self._record_event(
                run,
                gse=gse,
                tool="get_guideline_section",
                query=section_id,
                summary=_section_summary(result),
            )
        return run.cache[cache_key]

    def _search_titles(self, *, gse: str, query: str, run: _TraversalRun) -> list[dict[str, Any]]:
        cache_key = ("search", gse, query)
        if cache_key not in run.cache:
            result = self.retrieval_service.search_titles(query=query, gse=gse)
            run.cache[cache_key] = result
            self._record_event(
                run,
                gse=gse,
                tool="search_guideline_titles",
                query=query,
                summary=_search_summary(result),
            )
        return run.cache[cache_key]

    def _get_section_with_references(
        self,
        *,
        gse: str,
        section_id: str,
        run: _TraversalRun,
        depth: int = 1,
    ) -> dict[str, Any]:
        cache_key = ("refs", gse, section_id, depth)
        if cache_key not in run.cache:
            result = self.retrieval_service.get_section_with_references(section_id=section_id, gse=gse, depth=depth)
            run.cache[cache_key] = result
            self._record_event(
                run,
                gse=gse,
                tool="get_section_with_references",
                query=section_id,
                summary=_reference_summary(result),
            )
        return run.cache[cache_key]

    def _find_child(self, entries: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
        for entry in entries:
            if _entry_id(entry) == target_id:
                return entry
        return None

    def _normalize_children(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for child in children:
            child_id = _entry_id(child)
            if child_id is None:
                continue
            normalized.append(
                {
                    "id": child_id,
                    "title": child.get("title", ""),
                    "type": child.get("type", ""),
                    "has_children": bool(child.get("has_children")),
                }
            )
        return normalized

    def _score_entry(self, entry: dict[str, Any], selection_terms: tuple[str, ...]) -> int:
        title = entry.get("title") or ""
        score = _phrase_score(title, selection_terms)
        if score > 0 and not entry.get("has_children"):
            score += 1
        return score

    def _select_best_entry(
        self,
        *,
        entries: list[dict[str, Any]],
        selection_terms: tuple[str, ...],
        excluded_ids: set[str],
    ) -> dict[str, Any] | None:
        best_entry: dict[str, Any] | None = None
        best_score: int | None = None
        for entry in entries:
            entry_id = _entry_id(entry)
            if entry_id is None or entry_id in excluded_ids:
                continue
            score = self._score_entry(entry, selection_terms)
            if best_score is None or score > best_score:
                best_score = score
                best_entry = entry
                continue
            if score != best_score or best_entry is None:
                continue

            best_entry_id = _entry_id(best_entry) or ""
            best_title = best_entry.get("title") or ""
            entry_title = entry.get("title") or ""

            if bool(best_entry.get("has_children")) != bool(entry.get("has_children")):
                if not entry.get("has_children"):
                    best_entry = entry
                continue

            if len(entry_title) != len(best_title):
                if len(entry_title) < len(best_title):
                    best_entry = entry
                continue

            if entry_id < best_entry_id:
                best_entry = entry
        if best_score is None or best_score <= 0:
            return None
        return best_entry

    def _candidate_from_branch_hint(
        self,
        *,
        gse: str,
        focus: RetrievalFocus,
        branch_hint: TraversalBranchHint,
        run: _TraversalRun,
    ) -> TraversalCandidate | None:
        available = self._list_contents(gse=gse, path=None, run=run)
        if available and "error" in available[0]:
            return None

        for node_id in branch_hint.path:
            matched = self._find_child(available, node_id)
            if matched is None:
                return None
            available = self._list_contents(gse=gse, path=node_id, run=run)
            if available and "error" in available[0]:
                return None

        current_entries = available
        excluded_ids: set[str] = set()
        depth = 0
        while current_entries and depth < 6:
            best_entry = self._select_best_entry(
                entries=current_entries,
                selection_terms=branch_hint.selection_terms,
                excluded_ids=excluded_ids,
            )
            if best_entry is None:
                return None

            section_id = _entry_id(best_entry)
            if section_id is None:
                return None

            section = self._get_section(gse=gse, section_id=section_id, run=run)
            if "error" in section:
                excluded_ids.add(section_id)
                continue

            children = section.get("children")
            if children:
                current_entries = self._normalize_children(children)
                depth += 1
                continue

            refs = self._get_section_with_references(gse=gse, section_id=section_id, run=run)
            branch_string = " -> ".join(branch_hint.path)
            why_selected = (
                f"Selected from {branch_string} after matching "
                f"{', '.join(branch_hint.selection_terms[:2])} in the branch titles."
            )
            return TraversalCandidate(
                section_id=section.get("section_id") or section_id,
                title=section.get("title") or best_entry.get("title") or section_id,
                gse=gse,
                focus_key=focus.key,
                section=section,
                references_payload=refs,
                branch_path=branch_hint.path,
                selection_terms=branch_hint.selection_terms,
                source="branch",
                why_selected=why_selected,
            )

        return None

    def _candidate_from_search(
        self,
        *,
        gse: str,
        focus: RetrievalFocus,
        query: str,
        run: _TraversalRun,
        seen_sections: set[str],
    ) -> TraversalCandidate | None:
        matches = self._search_titles(gse=gse, query=query, run=run)
        if matches and "error" in matches[0]:
            return None

        for entry in matches[:6]:
            section_id = _entry_id(entry)
            if section_id is None or section_id in seen_sections:
                continue
            section = self._get_section(gse=gse, section_id=section_id, run=run)
            if "error" in section or section.get("children"):
                continue
            refs = self._get_section_with_references(gse=gse, section_id=section_id, run=run)
            return TraversalCandidate(
                section_id=section.get("section_id") or section_id,
                title=section.get("title") or entry.get("title") or section_id,
                gse=gse,
                focus_key=focus.key,
                section=section,
                references_payload=refs,
                branch_path=(),
                selection_terms=(query,),
                source="search_fallback",
                why_selected=f"Selected via fallback title search for '{query}' after hierarchy-first traversal did not yield a confident leaf.",
            )
        return None


class EvidenceValidator:
    def validate(self, candidate: TraversalCandidate, focus: RetrievalFocus) -> GuidelineEvidence | None:
        section_id = candidate.section.get("section_id") or candidate.section_id
        if not section_id:
            return None

        text = candidate.section.get("text") or ""
        if not text.strip():
            return None

        related_sections = (candidate.references_payload or {}).get("sections") or []
        reference_ids = tuple(
            str(section.get("section_id"))
            for section in related_sections
            if section.get("section_id") and section.get("section_id") != section_id
        )
        related_text = " ".join(
            f"{section.get('title', '')} {section.get('text', '')}"
            for section in related_sections
            if section.get("section_id") != section_id
        )

        title_score = _phrase_score(candidate.title, candidate.selection_terms)
        body_score = _phrase_score(text, candidate.selection_terms)
        related_score = _phrase_score(related_text, candidate.selection_terms)
        total_score = (title_score * 2) + body_score + related_score

        if total_score < 2:
            return None

        support_strength = "strong"
        if total_score < 10 and not reference_ids:
            support_strength = "moderate" if total_score >= 5 else "light"

        why_selected = candidate.why_selected
        if reference_ids:
            why_selected = f"{why_selected} Followed references: {', '.join(reference_ids[:3])}."

        return GuidelineEvidence(
            section_id=section_id,
            title=candidate.section.get("title") or candidate.title,
            gse=candidate.gse,
            focus_key=focus.key,
            why_selected=why_selected,
            support_strength=support_strength,
            references_followed=reference_ids,
        )
