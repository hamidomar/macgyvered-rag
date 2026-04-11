"""
Freddie Mac Single-Family Seller/Servicer Guide — Deterministic Pre-Processor
=============================================================================

PURPOSE:
    Parse the SF Guide PDF using its bookmark (outline) tree to build
    a structured index.  Every section's text is extracted by "front-assigning"
    content from one bookmark position to the next. Subsections e.g (a) are skipped
    so their text rolls into the parent section.

OUTPUTS (written to --output-dir):
    1. hierarchy_tree.json   — full navigational tree
    2. structured_sections.json — leaf-level sections with extracted text
    3. cross_references.json — mapping of cross-references
    4. extraction_report.txt — diagnostic summary
"""

from __future__ import annotations
import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pdfplumber
import pypdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

@dataclass
class Bookmark:
    title: str
    depth: int
    page_index: int
    top: Optional[float]
    node_type: str = ""
    section_id: str = ""
    date: str = ""
    clean_title: str = ""

@dataclass
class TreeNode:
    node_id: str
    title: str
    node_type: str
    section_id: str = ""
    date: str = ""
    page_index: int = 0
    children: list = field(default_factory=list)

def flatten_outline(reader: pypdf.PdfReader) -> list[Bookmark]:
    page_obj_id_map: dict[int, int] = {}
    page_idnum_map: dict[int, int] = {}
    for idx, page in enumerate(reader.pages):
        resolved = page.get_object()
        page_obj_id_map[id(resolved)] = idx
        if hasattr(page, "indirect_reference") and page.indirect_reference:
            page_idnum_map[page.indirect_reference.idnum] = idx

    def _resolve_page(item: dict) -> Optional[int]:
        page_ref = item.get("/Page")
        if not page_ref: return None
        resolved = page_ref.get_object() if hasattr(page_ref, "get_object") else page_ref
        if id(resolved) in page_obj_id_map: return page_obj_id_map[id(resolved)]
        if hasattr(page_ref, "idnum") and page_ref.idnum in page_idnum_map: return page_idnum_map[page_ref.idnum]
        return None

    def _get_top(item: dict) -> Optional[float]:
        raw = item.get("/Top")
        if raw is None or str(raw) == "NullObject": return None
        try: return float(raw)
        except (ValueError, TypeError): return None

    results: list[Bookmark] = []
    def _walk(items, depth: int = 0):
        for item in items:
            if isinstance(item, list):
                _walk(item, depth + 1)
            else:
                title = (item.get("/Title") or "").strip()
                # Option B: Ignore subsection depth and bookmarks matching "(a) xyz"
                if re.match(r"^\([a-z]\)\s", title) or depth > 5:
                    continue
                
                page_idx = _resolve_page(item)
                top = _get_top(item)
                results.append(Bookmark(
                    title=title, depth=depth,
                    page_index=page_idx if page_idx is not None else -1,
                    top=top
                ))

    _walk(reader.outline)
    log.info("Flattened %d bookmarks from outline.", len(results))
    return results

SECTION_ID_RE = re.compile(r"^(\d{4}\.\d+)")
DATE_RE = re.compile(r"\(([\d/]+)\)\s*$")
NODE_TYPE_PATTERNS = [
    (re.compile(r"^Series \d{4}"), "series"),
    (re.compile(r"^Topic \d{4}"), "topic"),
    (re.compile(r"^Chapter \d{4}"), "chapter"),
    (re.compile(r"^\d{4}\.\d+"), "section"),
    (re.compile(r"^Exhibit "), "section"),
    (re.compile(r"^Form "), "section"),
    (re.compile(r"^Glossary"), "section"),
]

def classify_bookmarks(bookmarks: list[Bookmark]) -> None:
    for bm in bookmarks:
        date_match = DATE_RE.search(bm.title)
        if date_match: bm.date = date_match.group(1)

        sid_match = SECTION_ID_RE.match(bm.title)
        if sid_match:
            bm.section_id = sid_match.group(1)
        elif bm.title.startswith("Exhibit"):
            m = re.search(r"^Exhibit ([\w]+)", bm.title)
            if m: bm.section_id = f"Exhibit_{m.group(1)}"
        elif bm.title.startswith("Form"):
            m = re.search(r"^Form ([\w]+)", bm.title)
            if m: bm.section_id = f"Form_{m.group(1)}"

        matched = False
        for pattern, ntype in NODE_TYPE_PATTERNS:
            if pattern.search(bm.title):
                bm.node_type = ntype
                matched = True
                break
        
        if not matched:
            if bm.section_id: bm.node_type = "section"
            elif bm.depth == 1: bm.node_type = "segment"
            elif bm.depth == 0: bm.node_type = "root"
            else: bm.node_type = "other"

        clean = bm.title
        if bm.date: clean = DATE_RE.sub("", clean).strip()
        if bm.section_id and sid_match:
            clean = re.sub(r"^\d{4}\.\d+:?\s*", "", clean)
        for prefix in ("Series ", "Topic ", "Chapter ", "Exhibit ", "Form "):
            if clean.startswith(prefix):
                clean = clean.split(":", 1)[-1].strip()
                clean = clean.split("-", 1)[-1].strip()
                break
        bm.clean_title = clean

def build_hierarchy_tree(bookmarks: list[Bookmark]) -> list[dict]:
    root_children: list[TreeNode] = []
    stack: list[tuple[int, TreeNode]] = []

    def _compute_node_id(bm: Bookmark) -> str:
        if bm.section_id: return bm.section_id
        if bm.node_type == "root":
            return "guide_root"
        if bm.node_type == "segment":
            return bm.title.replace("Freddie Mac - ", "").strip()
        m1 = re.search(r"Series (\d{4})", bm.title)
        if m1: return m1.group(1)
        m2 = re.search(r"Topic (\d{4})", bm.title)
        if m2: return m2.group(1)
        m3 = re.search(r"Chapter (\d{4})", bm.title)
        if m3: return m3.group(1)
        return bm.clean_title[:30]

    for bm in bookmarks:
        node = TreeNode(
            node_id=_compute_node_id(bm),
            title=bm.clean_title or bm.title,
            node_type=bm.node_type,
            section_id=bm.section_id,
            date=bm.date,
            page_index=bm.page_index,
        )

        while stack and stack[-1][0] >= bm.depth:
            stack.pop()

        if stack: stack[-1][1].children.append(node)
        else: root_children.append(node)
        stack.append((bm.depth, node))

    def _to_dict(node: TreeNode) -> dict:
        d = {"id": node.node_id, "title": node.title, "node_type": node.node_type}
        if node.section_id: d["section_id"] = node.section_id
        if node.date: d["date"] = node.date
        d["page_index"] = node.page_index
        if node.children: d["children"] = [_to_dict(c) for c in node.children]
        return d

    return [_to_dict(n) for n in root_children]

def extract_sections(pdf_path: str | Path, bookmarks: list[Bookmark]) -> list[dict]:
    leaf_indices = {i for i, bm in enumerate(bookmarks) if bm.node_type == "section"}
    sections: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        page_heights: dict[int, float] = {}

        def _get_page_height(page_idx: int) -> float:
            if page_idx not in page_heights:
                page_heights[page_idx] = float(pdf.pages[page_idx].height)
            return page_heights[page_idx]

        def _extract_text_between(sp, st_pdf, ep, et_pdf) -> str:
            text_parts = []
            for pg_idx in range(sp, min(ep + 1, total_pages)):
                page = pdf.pages[pg_idx]
                height = _get_page_height(pg_idx)
                ct = 0.0
                cb = height
                if pg_idx == sp and st_pdf is not None: ct = height - st_pdf
                if pg_idx == ep and et_pdf is not None: cb = height - et_pdf
                if ct >= cb: continue
                cr = page.within_bbox((0, ct, page.width, cb))
                pt = cr.extract_text()
                if pt: text_parts.append(pt)
            return "\n".join(text_parts)

        for i, bm in enumerate(bookmarks):
            if i not in leaf_indices: continue
            sp, st = bm.page_index, bm.top
            if i + 1 < len(bookmarks):
                nb = bookmarks[i + 1]
                ep, et = nb.page_index, nb.top
            else:
                ep = total_pages - 1
                et = None

            if sp < 0 or sp >= total_pages: continue
            ep = min(ep, total_pages - 1)
            try: text = _extract_text_between(sp, st, ep, et)
            except Exception: text = ""

            chapter = ""
            if bm.section_id and "." in bm.section_id:
                chapter = bm.section_id.split(".")[0]

            sections.append({
                "section_id": bm.section_id,
                "title": bm.clean_title,
                "full_title": bm.title,
                "date": bm.date,
                "node_type": "section",
                "chapter": chapter,
                "start_page": sp,
                "end_page": ep,
                "text": text.strip(),
                "text_length": len(text.strip()),
            })

    return sections

def build_cross_references(sections: list[dict]) -> dict[str, list[str]]:
    known_ids = {s["section_id"]: s for s in sections if s["section_id"]}
    ref_sec = re.compile(r"Section\s*(\d{4}\.\d+)")
    ref_ch = re.compile(r"Chapter\s*(\d{4})")
    
    cross_refs = {}
    for s in sections:
        sid = s["section_id"]
        if not sid: continue
        
        refs = set(ref_sec.findall(s["text"]))
        valid = set()
        for r in refs:
            if r in known_ids and r != sid:
                valid.add(r)
        
        ch_refs = set(ref_ch.findall(s["text"]))
        # No strict validation for chapter refs required but we can add them
        for ch in ch_refs:
            if f"Ch.{ch}" != sid:
                valid.add(f"Ch.{ch}")

        if valid:
            cross_refs[sid] = sorted(valid)

    return cross_refs

def generate_report(bms, tree, secs, xrefs):
    lines = [
        "SF GUIDE EXTRACTION REPORT",
        f"Total bookmarks: {len(bms)}",
        f"Sections extracted: {len(secs)}",
        f"Cross-refs: {len(xrefs)}",
    ]
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument("--output-dir", default="./sf_guide_index")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("1/5: Outline...")
    reader = pypdf.PdfReader(str(pdf_path))
    bms = flatten_outline(reader)

    log.info("2/5: Classify...")
    classify_bookmarks(bms)

    log.info("3/5: Tree...")
    tree = build_hierarchy_tree(bms)
    with open(out_dir / "hierarchy_tree.json", "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)

    log.info("4/5: Extract...")
    secs = extract_sections(pdf_path, bms)
    with open(out_dir / "structured_sections.json", "w", encoding="utf-8") as f:
        json.dump(secs, f, indent=2, ensure_ascii=False)

    log.info("5/5: Cross-refs...")
    xrefs = build_cross_references(secs)
    with open(out_dir / "cross_references.json", "w", encoding="utf-8") as f:
        json.dump(xrefs, f, indent=2, ensure_ascii=False)

    rep = generate_report(bms, tree, secs, xrefs)
    with open(out_dir / "extraction_report.txt", "w", encoding="utf-8") as f:
        f.write(rep)
    log.info("Done!")

if __name__ == "__main__":
    main()
