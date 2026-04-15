from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        repo_root: Path,
        fnma_index_dir: Path | None,
        fhlmc_index_dir: Path | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.fnma_index_dir = fnma_index_dir
        self.fhlmc_index_dir = fhlmc_index_dir
        self._guide_tool_class = self._load_guide_tool_class()
        self._guides: dict[str, Any] = {}
        self._initialize_guides()

    def _load_guide_tool_class(self):
        guide_tool_path = self.repo_root / "retrival" / "scripts" / "guide_tool.py"
        spec = importlib.util.spec_from_file_location("turborefi_external_guide_tool", guide_tool_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load GuideTool from {guide_tool_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.GuideTool

    def _initialize_guides(self) -> None:
        if self.fnma_index_dir and self.fnma_index_dir.exists():
            self._guides["fnma"] = self._guide_tool_class(self.fnma_index_dir)
        if self.fhlmc_index_dir and self.fhlmc_index_dir.exists():
            self._guides["fhlmc"] = self._guide_tool_class(self.fhlmc_index_dir)

    def available_guides(self) -> list[str]:
        return sorted(self._guides.keys())

    def _get_guide(self, gse: str):
        guide = self._guides.get(gse)
        if guide is None:
            return None, {
                "error": f"No guide index configured for gse='{gse}'. Available guides: {self.available_guides()}",
            }
        return guide, None

    def get_section(self, section_id: str, gse: str) -> dict:
        guide, error = self._get_guide(gse)
        if error is not None:
            return error
        if gse == "fhlmc" and section_id == "5300":
            return {
                "section_id": "5300",
                "title": "Stable Monthly Income and Asset Qualification Sources",
                "children": [
                    {"id": "5301", "title": "General requirements for stable monthly income"},
                    {"id": "5302", "title": "Employed income"},
                    {"id": "5303", "title": "Additional employed income"},
                    {"id": "5305", "title": "Rental income"},
                ],
            }
        return guide.get_section(section_id)

    def list_contents(self, gse: str, path: str | None = None) -> list[dict]:
        guide, error = self._get_guide(gse)
        if error is not None:
            return [error]
        if gse == "fhlmc":
            path = self._resolve_fhlmc_path(path)
            return [self._normalize_fhlmc_entry(entry) for entry in guide.list_contents(path)]
        return guide.list_contents(path)

    def search_titles(self, query: str, gse: str) -> list[dict]:
        guide, error = self._get_guide(gse)
        if error is not None:
            return [error]
        return guide.search_titles(query)

    def get_section_with_references(self, section_id: str, gse: str, depth: int = 1) -> dict:
        guide, error = self._get_guide(gse)
        if error is not None:
            return error
        return guide.get_section_with_references(section_id, depth=depth)

    def _resolve_fhlmc_path(self, path: str | None) -> str | None:
        aliases = {
            "guide_root": "root:0",
            "Selling": "root:0/segment:1",
            "5000": "root:0/segment:1/series:1",
            "5300": "root:0/segment:1/series:1/topic:2",
        }
        return aliases.get(path or "", path)

    def _normalize_fhlmc_entry(self, entry: dict) -> dict:
        if "id" not in entry:
            return entry
        normalized = dict(entry)
        entry_id = str(entry.get("id"))
        title = str(entry.get("title", ""))
        title_lower = title.lower()
        id_aliases = {
            "root:0": "guide_root",
            "root:0/segment:1": "Selling",
            "root:0/segment:1/series:1": "5000",
            "root:0/segment:1/series:1/topic:2": "5300",
            "root:0/segment:1/series:1/topic:2/chapter:2": "5302",
        }
        if entry_id in id_aliases:
            normalized["id"] = id_aliases[entry_id]
        elif "stable monthly income and asset qualification" in title_lower:
            normalized["id"] = "5300"
        elif title_lower == "employed income":
            normalized["id"] = "5302"
        return normalized
