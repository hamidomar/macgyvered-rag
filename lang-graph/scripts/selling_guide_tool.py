"""
Selling Guide Retrieval Tool
============================

Provides an interface for agents and humans to navigate the Fannie Mae Selling Guide
hierarchy and retrieve structured section text.
"""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any


class SellingGuideTool:
    def __init__(self, index_dir: str | Path):
        self.index_dir = Path(index_dir)
        
        # Load core data
        with open(self.index_dir / "hierarchy_tree.json", "r", encoding="utf-8") as f:
            self.tree = json.load(f)
            
        with open(self.index_dir / "structured_sections.json", "r", encoding="utf-8") as f:
            raw_sections = json.load(f)
            self.sections = {s["section_id"]: s for s in raw_sections if s.get("section_id")}
            
        with open(self.index_dir / "cross_references.json", "r", encoding="utf-8") as f:
            self.xrefs = json.load(f)
            
        # Build flat index for fast O(1) navigation
        self._node_index = self._build_node_index()

    def _build_node_index(self) -> Dict[str, Dict]:
        """Walks the full tree and builds a flat dict keyed by node ID."""
        index = {}

        def _walk(nodes):
            for node in nodes:
                node_id = node.get("id")
                if node_id:
                    index[node_id] = node
                if "children" in node:
                    _walk(node["children"])

        _walk(self.tree)
        return index

    def list_contents(self, path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Shows one level of the hierarchy.
        If path is None, returns top-level Parts.
        """
        if not path:
            nodes = self.tree
        else:
            node = self._node_index.get(path)
            if not node:
                return [{"error": f"Path '{path}' not found"}]
            nodes = node.get("children", [])

        return [
            {
                "id": child["id"],
                "title": child["title"],
                "type": child["node_type"],
                "has_children": bool(child.get("children")),
            }
            for child in nodes
        ]

    def get_section(self, section_id: str) -> Dict[str, Any]:
        """Retrieve full text and metadata for a leaf section."""
        section = self.sections.get(section_id)
        if not section:
            return {"error": f"Section '{section_id}' not found"}

        result = dict(section)
        result["references"] = self.xrefs.get(section_id, [])
        return result

    def get_sections(self, section_ids: List[str]) -> List[Dict[str, Any]]:
        """Batch retrieval of multiple sections."""
        return [self.get_section(sid) for sid in section_ids]

    def get_section_with_references(self, section_id: str, depth: int = 1) -> Dict[str, Any]:
        """
        Retrieve a section and its direct (or nth-degree) references.
        Useful for expanding context.
        """
        visited = set()
        to_fetch = [section_id]
        all_sections = []

        for _ in range(depth + 1):
            next_round = []
            for sid in to_fetch:
                if sid in visited:
                    continue
                visited.add(sid)
                section = self.get_section(sid)
                if "error" not in section:
                    all_sections.append(section)
                    next_round.extend(section.get("references", []))
            to_fetch = next_round

        return {
            "primary": section_id,
            "sections": all_sections,
            "total_text_length": sum(s.get("text_length", 0) for s in all_sections),
        }

    def search_titles(self, query: str) -> List[Dict[str, Any]]:
        """
        Keyword search against all section titles.
        Returns a list of matching sections (metadata only).
        """
        query_lower = query.lower()
        terms = query_lower.split()
        results = []
        
        for sid, section in self.sections.items():
            title_lower = section["title"].lower()
            if all(term in title_lower for term in terms):
                results.append({
                    "id": sid,
                    "title": section["title"],
                    "date": section["date"],
                    "part": section["part"],
                })
        return results
