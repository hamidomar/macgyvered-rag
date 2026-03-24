"""
Guide Retrieval Tool
====================

A deterministic retrieval tool for navigating and fetching content from
preprocessed regulatory guide indices (Fannie Mae Selling Guide,
Freddie Mac Multifamily Guide, or any guide processed by our preprocessors).

This is the tool class the agent calls. It loads the JSON index files
produced by the preprocessors and exposes navigation + retrieval functions.

DESIGN PHILOSOPHY:
    The tool is a filing cabinet, not a search engine.
    It shows structure and returns text. The AGENT reasons about
    which path to take.

USAGE:
    from guide_tool import GuideTool

    tool = GuideTool("./selling_guide_index")
    tool.list_contents()             # top-level
    tool.list_contents("A2")         # drill into Subpart A2
    tool.get_section("A2-1-01")      # full text of a leaf section
"""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Optional


class GuideTool:
    """
    Deterministic retrieval tool for preprocessed regulatory guide indices.

    Works with any index directory containing:
        - hierarchy_tree.json
        - structured_sections.json
        - cross_references.json
    """

    def __init__(self, index_dir: str | Path):
        index_dir = Path(index_dir)

        with open(index_dir / "hierarchy_tree.json", encoding="utf-8") as f:
            self.tree: list[dict] = json.load(f)

        with open(index_dir / "structured_sections.json", encoding="utf-8") as f:
            raw_sections = json.load(f)
        # Key by section_id; sections without IDs get keyed by title
        self.sections: dict[str, dict] = {}
        for s in raw_sections:
            key = s.get("section_id") or s.get("title", "")
            if key:
                self.sections[key] = s

        with open(index_dir / "cross_references.json", encoding="utf-8") as f:
            self.xrefs: dict[str, list[str]] = json.load(f)

        # Build reverse cross-reference index (who cites this section?)
        self._reverse_xrefs: dict[str, list[str]] = {}
        for src, targets in self.xrefs.items():
            for tgt in targets:
                self._reverse_xrefs.setdefault(tgt, []).append(src)

        # Build flat node index for O(1) navigation lookups
        self._node_index: dict[str, dict] = {}
        self._build_node_index()

        # Stats
        self.total_sections = len(self.sections)
        self.total_tree_nodes = len(self._node_index)
        self._guide_name = index_dir.name

    # ------------------------------------------------------------------
    # Node ID derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _node_id(node: dict) -> str:
        """
        Derive a short, navigable ID from a tree node.

        Handles both Fannie Mae and Freddie Mac naming conventions:

        Fannie Mae:
            Part A, Doing Business...           → "A"
            Subpart A2, Lender Contract         → "A2"
            Chapter A2-3, Lender Breach...      → "A2-3"
            Section A2-3.1, ...                 → "A2-3.1"
            (topic with section_id)             → section_id directly

        Freddie Mac:
            Group: "Freddie Mac and Seller..."  → "grp:0" (index-based)
            Chapter: title="Introduction"       → "ch:01"
            Section: section_id="1.3"           → "1.3"
            Sub-section: section_id="1.3.a"     → "1.3.a"

        If a section_id is present, we always prefer it.
        """
        # If the node has an explicit section_id, use it
        sid = node.get("section_id", "")
        if sid:
            return sid

        title = node.get("title", "")
        node_type = node.get("node_type", "")

        # --- Fannie Mae patterns ---
        # "A, Doing Business with Fannie Mae" → "A"
        fm_part = re.match(r"^([A-E]),\s", title)
        if fm_part:
            return fm_part.group(1)

        # "A2, Lender Contract" → "A2"
        fm_subpart = re.match(r"^([A-E]\d),\s", title)
        if fm_subpart:
            return fm_subpart.group(1)

        # "A2-3, Lender Breach..." → "A2-3"
        fm_chapter = re.match(r"^([A-E]\d-\d[\d.]*),\s", title)
        if fm_chapter:
            return fm_chapter.group(1)

        # --- Freddie Mac patterns ---
        # Chapters don't have section_ids but we can look for chapter_num
        # in the node (if the preprocessor stored it). Otherwise, fall back
        # to the title itself.

        # Generic fallback: use the title as the ID (lowercased, truncated)
        return title

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def _build_node_index(self) -> None:
        """
        Walk the full tree and index every node by its derived ID.
        This enables O(1) lookups for list_contents(path).

        Also assigns a stable 'nav_id' field to each node in-place,
        handling duplicates by appending a disambiguator.
        """
        seen: dict[str, int] = {}

        def _walk(nodes: list[dict], parent_prefix: str = ""):
            for i, node in enumerate(nodes):
                raw_id = self._node_id(node)

                # Handle nodes without meaningful IDs (groups, cover pages)
                if not raw_id or raw_id == node.get("title", ""):
                    node_type = node.get("node_type", "node")
                    raw_id = f"{node_type}:{i}"
                    if parent_prefix:
                        raw_id = f"{parent_prefix}/{raw_id}"

                # Deduplicate: if we've seen this ID, append a counter
                if raw_id in seen:
                    seen[raw_id] += 1
                    nav_id = f"{raw_id}#{seen[raw_id]}"
                else:
                    seen[raw_id] = 0
                    nav_id = raw_id

                node["nav_id"] = nav_id
                self._node_index[nav_id] = node

                # Also index by section_id if present (for direct access)
                sid = node.get("section_id", "")
                if sid and sid != nav_id:
                    self._node_index[sid] = node

                # Recurse into children
                children = node.get("children", [])
                if children:
                    _walk(children, nav_id)

        _walk(self.tree)

    # ------------------------------------------------------------------
    # Tool Functions (what the agent calls)
    # ------------------------------------------------------------------

    def list_contents(self, path: str | None = None) -> list[dict]:
        """
        Show one level of the hierarchy.

        Args:
            path: None for top-level, or a nav_id / section_id to drill into.

        Returns:
            List of dicts with: id, title, type, has_children, date (if present)
        """
        if path is None:
            nodes = self.tree
        else:
            node = self._node_index.get(path)
            if node is None:
                # Try case-insensitive fuzzy match
                node = self._fuzzy_find(path)
            if node is None:
                return [{"error": f"Path '{path}' not found. Use list_contents() to see available paths."}]
            nodes = node.get("children", [])

        results = []
        for child in nodes:
            entry = {
                "id": child.get("nav_id", self._node_id(child)),
                "title": child.get("title", ""),
                "type": child.get("node_type", ""),
                "has_children": bool(child.get("children")),
            }
            date = child.get("date", "")
            if date:
                entry["date"] = date
            results.append(entry)

        return results

    def get_section(self, section_id: str) -> dict:
        """
        Retrieve the full text and metadata of a leaf section.

        Args:
            section_id: The section identifier (e.g., "A2-1-01" or "1.3.a")

        Returns:
            Dict with section data + cross-references, or error dict.
        """
        section = self.sections.get(section_id)
        if section is None:
            # Try fuzzy
            candidates = [k for k in self.sections if section_id.lower() in k.lower()]
            if candidates:
                suggestion = ", ".join(candidates[:5])
                return {"error": f"Section '{section_id}' not found. Did you mean: {suggestion}?"}
            return {"error": f"Section '{section_id}' not found."}

        result = {**section}
        result["references"] = self.xrefs.get(section_id, [])
        result["cited_by"] = self._reverse_xrefs.get(section_id, [])
        return result

    def get_sections(self, section_ids: list[str]) -> list[dict]:
        """
        Batch retrieval of multiple sections.

        Args:
            section_ids: List of section identifiers.

        Returns:
            List of section dicts (including any error dicts for missing ones).
        """
        return [self.get_section(sid) for sid in section_ids]

    def get_section_with_references(
        self, section_id: str, depth: int = 1
    ) -> dict:
        """
        Retrieve a section AND all sections it references, up to `depth` hops.

        Args:
            section_id: The starting section.
            depth: How many hops of cross-references to follow (default 1).

        Returns:
            Dict with 'primary', 'sections' list, and 'total_text_length'.
        """
        visited: set[str] = set()
        to_fetch = [section_id]
        all_sections: list[dict] = []

        for _ in range(depth + 1):
            next_round: list[str] = []
            for sid in to_fetch:
                if sid in visited:
                    continue
                visited.add(sid)
                section = self.get_section(sid)
                if "error" not in section:
                    all_sections.append(section)
                    # Only follow section-level refs, not chapter-level "Ch.17" refs
                    refs = [r for r in section.get("references", []) if not r.startswith("Ch.")]
                    next_round.extend(refs)
            to_fetch = next_round

        return {
            "primary": section_id,
            "sections": all_sections,
            "total_text_length": sum(s.get("text_length", 0) for s in all_sections),
        }

    def search_titles(self, query: str) -> list[dict]:
        """
        Deterministic keyword search across all section titles.
        Like Ctrl+F on the table of contents — no embeddings, no ranking.

        Args:
            query: Space-separated keywords. ALL must match (AND logic).

        Returns:
            List of matching sections (id, title, date, chapter).
        """
        terms = query.lower().split()
        if not terms:
            return []

        results = []
        for sid, section in self.sections.items():
            title_lower = section.get("title", "").lower()
            full_title_lower = section.get("full_title", "").lower()
            # Match against both clean title and full title
            searchable = f"{title_lower} {full_title_lower}"
            if all(term in searchable for term in terms):
                results.append({
                    "section_id": sid,
                    "title": section.get("title", ""),
                    "date": section.get("date", ""),
                    "chapter": section.get("chapter", ""),
                    "node_type": section.get("node_type", ""),
                    "text_length": section.get("text_length", 0),
                })

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fuzzy_find(self, path: str) -> Optional[dict]:
        """Case-insensitive and partial match fallback for _find_node."""
        path_lower = path.lower().strip()
        # Exact match (case-insensitive)
        for key, node in self._node_index.items():
            if key.lower() == path_lower:
                return node
        # Prefix match
        for key, node in self._node_index.items():
            if key.lower().startswith(path_lower):
                return node
        return None

    def stats(self) -> dict:
        """Return summary statistics about the loaded index."""
        return {
            "guide": self._guide_name,
            "total_tree_nodes": self.total_tree_nodes,
            "total_leaf_sections": self.total_sections,
            "total_cross_references": sum(len(v) for v in self.xrefs.values()),
            "top_level_count": len(self.tree),
        }