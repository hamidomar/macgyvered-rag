"""
Freddie Mac Multifamily Seller/Servicer Guide — Deterministic Pre-Processor
============================================================================

PURPOSE:
    Parse the Multifamily Guide PDF using its bookmark (outline) tree to build
    a structured index.  Same approach as the Fannie Mae preprocessor:
    flatten bookmarks → resolve pages → front-assign text via coordinates.

    Key differences from the Fannie Mae version:
      - Hierarchy: Group → Chapter → Section → Sub-section → (rare) Sub-sub-section
      - Section IDs: numeric (1.3, 17.2) instead of alphanumeric (A2-1-01)
      - Sub-sections: lettered (a., b., c.) instead of numeric topic IDs
      - Chapter titles in bookmarks: "01 - Introduction GB-02-27-25"
      - Leaf level: sections (depth 2) without children, OR sub-sections (depth 3)
      - Cross-refs: "Section 60.4", "Chapter 17", "Section 1.5(b)" patterns

OUTPUTS (written to --output-dir):
    1. hierarchy_tree.json        — full navigational tree
    2. structured_sections.json   — leaf-level sections with extracted text
    3. cross_references.json      — section_id → [referenced section_ids]
    4. extraction_report.txt      — diagnostic summary

USAGE:
    python preprocess_mf_guide.py <path_to_pdf> [--output-dir ./mf_guide_index]

REQUIREMENTS:
    pip install pypdf pdfplumber
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

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Bookmark:
    """A single flattened bookmark extracted from the PDF outline."""
    title: str
    depth: int                 # nesting depth in the outline tree
    page_index: int            # 0-based page index in the PDF
    top: Optional[float]       # y-coordinate on the page (PDF coords: 0=bottom)
    node_type: str = ""        # group | chapter | section | subsection | subsubsection | other
    section_id: str = ""       # e.g. "1.3", "17.2", "1.3.a", "19.3.c"
    chapter_num: str = ""      # e.g. "1", "06SBL", "17A"
    date: str = ""             # e.g. "10/07/02" parsed from title
    clean_title: str = ""      # title without section_id and date
    is_leaf: bool = False      # True if this bookmark has no children


@dataclass
class TreeNode:
    """A node in the hierarchy tree (JSON-serialisable)."""
    title: str
    node_type: str
    section_id: str = ""
    date: str = ""
    page_index: int = 0
    children: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 1 — Flatten the PDF outline (IDENTICAL to Fannie Mae version)
# ---------------------------------------------------------------------------

def flatten_outline(reader: pypdf.PdfReader) -> list[Bookmark]:
    """
    Walk the nested outline structure from pypdf and return a flat,
    document-order list of Bookmark objects with resolved page numbers.
    """
    page_obj_id_map: dict[int, int] = {}
    page_idnum_map: dict[int, int] = {}

    for idx, page in enumerate(reader.pages):
        resolved = page.get_object()
        page_obj_id_map[id(resolved)] = idx
        if hasattr(page, "indirect_reference") and page.indirect_reference:
            page_idnum_map[page.indirect_reference.idnum] = idx

    def _resolve_page(item: dict) -> Optional[int]:
        page_ref = item.get("/Page")
        if page_ref is None:
            return None
        resolved = page_ref.get_object() if hasattr(page_ref, "get_object") else page_ref
        if id(resolved) in page_obj_id_map:
            return page_obj_id_map[id(resolved)]
        if hasattr(page_ref, "idnum") and page_ref.idnum in page_idnum_map:
            return page_idnum_map[page_ref.idnum]
        for idx, page in enumerate(reader.pages):
            if page.get_object() is resolved:
                return idx
        return None

    def _get_top(item: dict) -> Optional[float]:
        raw = item.get("/Top")
        if raw is None or str(raw) == "NullObject":
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    results: list[Bookmark] = []

    def _walk(items, depth: int = 0):
        for item in items:
            if isinstance(item, list):
                _walk(item, depth + 1)
            else:
                page_idx = _resolve_page(item)
                top = _get_top(item)
                title = (item.get("/Title") or "").strip()
                results.append(Bookmark(
                    title=title,
                    depth=depth,
                    page_index=page_idx if page_idx is not None else -1,
                    top=top,
                ))

    _walk(reader.outline)
    log.info("Flattened %d bookmarks from outline.", len(results))
    return results


# ---------------------------------------------------------------------------
# Step 2 — Classify & parse each bookmark (FREDDIE MAC SPECIFIC)
# ---------------------------------------------------------------------------

# Date in parentheses at end of title: (MM/DD/YY) or (MM/DD/YYYY)
DATE_RE = re.compile(r"\((\d{2}/\d{2}/\d{2,4})\)\s*$")

# Chapter bookmark patterns. Two variants:
#   With GB suffix: "01 - Introduction GB-02-27-25", "18SBL - Originating SBL Mortgages GB -12-16-25"
#   Without GB suffix: "12-16SBL - Reserved", "56-59 - Reserved"
CHAPTER_BM_WITH_GB = re.compile(
    r"^(\d+[A-Z]?(?:SBL)?(?:-\d+[A-Z]?(?:SBL)?)?)\s+-\s+(.+?)\s+GB[\s-][\d-]+$"
)
CHAPTER_BM_NO_GB = re.compile(
    r"^(\d+[A-Z]?(?:SBL)?(?:-\d+[A-Z]?(?:SBL)?)?)\s+-\s+(.+)$"
)

# Section bookmark pattern: "1.3 Legal effect of the... (02/27/25)"
# Matches: 1.1, 1.12, 17.2, 31.13
SECTION_BM_RE = re.compile(
    r"^(\d+\.\d+)\s+(.+)"
)

# Sub-section bookmark pattern: "a. Capitalized terms; Glossary (12/05/03)"
SUBSECTION_BM_RE = re.compile(
    r"^([a-z])\.\s+(.+)"
)

# Depth-4 entries: numbered items like "1. Property and Borrower Principal"
# or free text like "All Preferred Equity is subject to..."
SUBSUBSECTION_BM_RE = re.compile(
    r"^(\d+)\.\s+(.+)"
)

# Group-level (depth 0) patterns
GROUP_BM_RE = re.compile(
    r"(?:Chs?\s+[\d\w,-]+|Cover Page|Directory|Glossary|Reserved)"
)


def classify_bookmarks(bookmarks: list[Bookmark]) -> None:
    """
    Mutate each Bookmark in-place: set node_type, section_id,
    chapter_num, date, clean_title, is_leaf.
    """

    # --- First pass: classify node_type and parse fields ---
    for bm in bookmarks:

        # --- Extract date from title ---
        date_match = DATE_RE.search(bm.title)
        if date_match:
            bm.date = date_match.group(1)

        # --- Classify by depth + title pattern ---

        if bm.depth == 0:
            # Top-level groupings
            bm.node_type = "group"
            bm.clean_title = bm.title
            # Try to strip "GB-..." suffix if present
            bm.clean_title = re.sub(r"\s+GB-[\d-]+$", "", bm.clean_title).strip()
            continue

        if bm.depth == 1:
            # Chapters: "01 - Introduction GB-02-27-25" or "12-16SBL - Reserved"
            # Also: "Directory (10/21/25)", "Glossary and List of... (02/24/26)"
            bm.node_type = "chapter"
            # Try with GB suffix first (more specific), then without
            ch_match = CHAPTER_BM_WITH_GB.match(bm.title) or CHAPTER_BM_NO_GB.match(bm.title)
            if ch_match:
                bm.chapter_num = ch_match.group(1)
                bm.clean_title = ch_match.group(2).strip()
            else:
                # Non-standard chapter (Directory, Glossary, Reserved)
                clean = bm.title
                if bm.date:
                    clean = DATE_RE.sub("", clean).strip()
                clean = re.sub(r"\s+GB-[\d-]+$", "", clean).strip()
                bm.clean_title = clean
            continue

        if bm.depth == 2:
            # Sections: "1.3 Legal effect..." or glossary terms
            sec_match = SECTION_BM_RE.match(bm.title)
            if sec_match:
                bm.node_type = "section"
                bm.section_id = sec_match.group(1)
                clean = sec_match.group(2)
                if bm.date:
                    clean = DATE_RE.sub("", clean).strip()
                bm.clean_title = clean
            else:
                # Glossary terms or other depth-2 entries without section numbers
                bm.node_type = "section"
                clean = bm.title
                if bm.date:
                    clean = DATE_RE.sub("", clean).strip()
                bm.clean_title = clean
                # Use the title itself as a pseudo-ID for glossary terms
                # (they don't have numeric IDs)
            continue

        if bm.depth == 3:
            # Sub-sections: "a. Capitalized terms; Glossary (12/05/03)"
            bm.node_type = "subsection"
            sub_match = SUBSECTION_BM_RE.match(bm.title)
            if sub_match:
                letter = sub_match.group(1)
                clean = sub_match.group(2)
                if bm.date:
                    clean = DATE_RE.sub("", clean).strip()
                bm.clean_title = clean
                # section_id will be set in second pass (needs parent context)
                # Store the letter temporarily
                bm.section_id = letter  # placeholder, will become "1.3.a"
            else:
                clean = bm.title
                if bm.date:
                    clean = DATE_RE.sub("", clean).strip()
                bm.clean_title = clean
            continue

        if bm.depth == 4:
            # Sub-sub-sections: rare, numbered items or free text
            bm.node_type = "subsubsection"
            subsub_match = SUBSUBSECTION_BM_RE.match(bm.title)
            if subsub_match:
                bm.clean_title = subsub_match.group(2).strip()
                bm.section_id = subsub_match.group(1)  # placeholder
            else:
                bm.clean_title = bm.title
            continue

        # Fallback for unexpected depths
        bm.node_type = "other"
        bm.clean_title = bm.title

    # --- Second pass: build composite section_ids for sub-sections ---
    # Sub-sections need their parent section's ID to form "1.3.a"
    # Sub-sub-sections need parent sub-section to form "1.3.a.1"
    #
    # Walk forward, tracking the current parent at each level.

    current_chapter = ""       # e.g. "1", "17A"
    current_section_id = ""    # e.g. "1.3", "17.2"
    current_subsection_id = "" # e.g. "1.3.a"

    for bm in bookmarks:
        if bm.node_type == "chapter":
            current_chapter = bm.chapter_num
            current_section_id = ""
            current_subsection_id = ""

        elif bm.node_type == "section":
            if bm.section_id:
                current_section_id = bm.section_id
            else:
                # Glossary terms etc — use chapter + clean title slug
                current_section_id = ""
            current_subsection_id = ""

        elif bm.node_type == "subsection":
            if current_section_id and len(bm.section_id) == 1:
                # Single letter placeholder → build composite ID
                letter = bm.section_id
                bm.section_id = f"{current_section_id}.{letter}"
                current_subsection_id = bm.section_id
            elif not current_section_id:
                # No parent section (e.g. under glossary) — leave as-is
                current_subsection_id = bm.section_id

        elif bm.node_type == "subsubsection":
            if current_subsection_id and bm.section_id.isdigit():
                # Numbered sub-sub-section → "1.3.a.1"
                bm.section_id = f"{current_subsection_id}.{bm.section_id}"
            elif current_section_id and bm.section_id.isdigit():
                # Directly under a section → "19.3.1"
                bm.section_id = f"{current_section_id}.{bm.section_id}"

        # Also assign chapter_num to all descendants
        if bm.node_type in ("section", "subsection", "subsubsection") and not bm.chapter_num:
            bm.chapter_num = current_chapter

    # --- Third pass: mark leaves ---
    # A bookmark is a leaf if no subsequent bookmark has a greater depth
    # (i.e., it has no children in the outline)
    for i, bm in enumerate(bookmarks):
        if i + 1 < len(bookmarks):
            bm.is_leaf = bookmarks[i + 1].depth <= bm.depth
        else:
            bm.is_leaf = True  # last bookmark is always a leaf

    leaf_count = sum(1 for bm in bookmarks if bm.is_leaf)
    log.info(
        "Classified bookmarks: %d groups, %d chapters, %d sections, "
        "%d subsections, %d subsubsections, %d other. %d are leaves.",
        sum(1 for b in bookmarks if b.node_type == "group"),
        sum(1 for b in bookmarks if b.node_type == "chapter"),
        sum(1 for b in bookmarks if b.node_type == "section"),
        sum(1 for b in bookmarks if b.node_type == "subsection"),
        sum(1 for b in bookmarks if b.node_type == "subsubsection"),
        sum(1 for b in bookmarks if b.node_type == "other"),
        leaf_count,
    )


# ---------------------------------------------------------------------------
# Step 3 — Build the hierarchy tree (for navigation)
# ---------------------------------------------------------------------------

def build_hierarchy_tree(bookmarks: list[Bookmark]) -> list[dict]:
    """
    Build a nested tree from the flat, depth-annotated bookmark list.
    Same stack-based algorithm as the Fannie Mae version.
    """
    root_children: list[TreeNode] = []
    stack: list[tuple[int, TreeNode]] = []

    for bm in bookmarks:
        node = TreeNode(
            title=bm.clean_title or bm.title,
            node_type=bm.node_type,
            section_id=bm.section_id,
            date=bm.date,
            page_index=bm.page_index,
        )

        while stack and stack[-1][0] >= bm.depth:
            stack.pop()

        if stack:
            stack[-1][1].children.append(node)
        else:
            root_children.append(node)

        stack.append((bm.depth, node))

    def _to_dict(node: TreeNode) -> dict:
        d = {
            "title": node.title,
            "node_type": node.node_type,
        }
        if node.section_id:
            d["section_id"] = node.section_id
        if node.date:
            d["date"] = node.date
        d["page_index"] = node.page_index
        if node.children:
            d["children"] = [_to_dict(c) for c in node.children]
        return d

    return [_to_dict(n) for n in root_children]


# ---------------------------------------------------------------------------
# Step 4 — Extract text by coordinate-based front-assignment
# ---------------------------------------------------------------------------

def extract_sections(
    pdf_path: str | Path,
    bookmarks: list[Bookmark],
) -> list[dict]:
    """
    For each *leaf* bookmark, extract the text from its (page, top)
    position to the next bookmark's (page, top) position.

    Leaf detection: uses the is_leaf flag set during classification.
    This means:
      - Sections WITHOUT sub-sections → leaf (extract text)
      - Sections WITH sub-sections   → NOT leaf (their sub-sections are leaves)
      - Sub-sections                  → leaf (extract text)
      - Sub-sub-sections              → leaf (extract text)

    Uses pdfplumber with within_bbox for sub-page coordinate precision.
    """
    all_bms = bookmarks
    leaf_indices = {i for i, bm in enumerate(all_bms) if bm.is_leaf}
    log.info("Found %d leaf bookmarks to extract text for.", len(leaf_indices))

    sections: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        page_heights: dict[int, float] = {}

        def _get_page_height(page_idx: int) -> float:
            if page_idx not in page_heights:
                page_heights[page_idx] = float(pdf.pages[page_idx].height)
            return page_heights[page_idx]

        def _extract_text_between(
            start_page: int,
            start_top_pdf: Optional[float],
            end_page: int,
            end_top_pdf: Optional[float],
        ) -> str:
            """
            Extract text from (start_page, start_top) to (end_page, end_top).

            Coordinate conversion:
                pdfplumber y = 0 at top, increases downward
                PDF /Top    = 0 at bottom, increases upward
                pdfplumber_y = page_height - pdf_top
            """
            text_parts: list[str] = []

            for pg_idx in range(start_page, min(end_page + 1, total_pages)):
                page = pdf.pages[pg_idx]
                height = _get_page_height(pg_idx)

                crop_top = 0.0
                crop_bottom = height

                if pg_idx == start_page and start_top_pdf is not None:
                    crop_top = height - start_top_pdf

                if pg_idx == end_page and end_top_pdf is not None:
                    crop_bottom = height - end_top_pdf

                if crop_top >= crop_bottom:
                    continue

                try:
                    cropped = page.within_bbox((0, crop_top, page.width, crop_bottom))
                    page_text = cropped.extract_text()
                except Exception:
                    # Fallback: if bbox fails, try full page
                    page_text = page.extract_text()

                if page_text:
                    text_parts.append(page_text)

            return "\n".join(text_parts)

        # --- Iterate over all bookmarks, extract text for leaves ---
        for i, bm in enumerate(all_bms):
            if i not in leaf_indices:
                continue

            start_page = bm.page_index
            start_top = bm.top

            # End position: next bookmark (any type), or end of document
            if i + 1 < len(all_bms):
                next_bm = all_bms[i + 1]
                end_page = next_bm.page_index
                end_top = next_bm.top
            else:
                end_page = total_pages - 1
                end_top = None

            if start_page < 0 or start_page >= total_pages:
                log.warning(
                    "Skipping '%s': start_page=%d out of range (total=%d)",
                    bm.section_id or bm.title, start_page, total_pages,
                )
                continue

            end_page = min(end_page, total_pages - 1)

            try:
                text = _extract_text_between(start_page, start_top, end_page, end_top)
            except Exception as exc:
                log.error(
                    "Error extracting text for '%s' (pages %d–%d): %s",
                    bm.section_id or bm.title, start_page, end_page, exc,
                )
                text = ""

            sections.append({
                "section_id": bm.section_id,
                "title": bm.clean_title,
                "full_title": bm.title,
                "date": bm.date,
                "node_type": bm.node_type,
                "chapter": bm.chapter_num,
                "start_page": bm.page_index,
                "end_page": end_page,
                "text": text.strip(),
                "text_length": len(text.strip()),
            })

        log.info("Extracted text for %d leaf sections.", len(sections))

    return sections


# ---------------------------------------------------------------------------
# Step 5 — Build a cross-reference index (FREDDIE MAC SPECIFIC)
# ---------------------------------------------------------------------------

def build_cross_references(sections: list[dict]) -> dict[str, list[str]]:
    """
    Scan each section's text for references to other sections.

    Freddie Mac style references:
      - "Section 60.4"
      - "Chapter 17"
      - "Section 1.5(b)"  → we map this to section_id "1.5.b"
      - "Section 2.14(d)" → maps to "2.14.d"

    Returns a dict: section_id → [referenced section_ids]
    """
    # Pattern 1: "Section NN.NN(x)" → "NN.NN.x"
    ref_section_with_sub = re.compile(
        r"Section\s+(\d+\.\d+)\(([a-z])\)"
    )
    # Pattern 2: "Section NN.NN" → "NN.NN"
    ref_section = re.compile(
        r"Section\s+(\d+\.\d+)"
    )
    # Pattern 3: "Chapter NN" → chapter-level ref
    ref_chapter = re.compile(
        r"Chapter\s+(\d+[A-Z]?(?:SBL)?)"
    )

    # Build known ID sets
    known_section_ids = {s["section_id"] for s in sections if s["section_id"]}
    known_chapter_nums = {s["chapter"] for s in sections if s["chapter"]}

    cross_refs: dict[str, list[str]] = {}

    for s in sections:
        sid = s["section_id"]
        if not sid:
            continue

        text = s["text"]
        found_refs: set[str] = set()

        # Find "Section 1.5(b)" → "1.5.b"
        for match in ref_section_with_sub.finditer(text):
            ref_id = f"{match.group(1)}.{match.group(2)}"
            if ref_id in known_section_ids:
                found_refs.add(ref_id)

        # Find "Section 60.4" → "60.4"
        for match in ref_section.finditer(text):
            ref_id = match.group(1)
            if ref_id in known_section_ids:
                found_refs.add(ref_id)

        # Find "Chapter 17" → find all sections in that chapter
        for match in ref_chapter.finditer(text):
            ch_num = match.group(1)
            if ch_num in known_chapter_nums:
                # Don't expand to all sections — just note the chapter ref
                # The agent can use list_contents() to drill in
                found_refs.add(f"Ch.{ch_num}")

        # Remove self-references
        found_refs.discard(sid)

        if found_refs:
            cross_refs[sid] = sorted(found_refs)

    log.info(
        "Built cross-reference index: %d sections reference other sections.",
        len(cross_refs),
    )
    return cross_refs


# ---------------------------------------------------------------------------
# Step 6 — Diagnostics / extraction report
# ---------------------------------------------------------------------------

def generate_report(
    bookmarks: list[Bookmark],
    tree: list[dict],
    sections: list[dict],
    cross_refs: dict[str, list[str]],
) -> str:
    """Generate a human-readable diagnostic report."""
    lines = [
        "=" * 70,
        "FREDDIE MAC MULTIFAMILY GUIDE PRE-PROCESSING REPORT",
        "=" * 70,
        "",
        f"Total bookmarks in outline:       {len(bookmarks)}",
        f"  Groups:          {sum(1 for b in bookmarks if b.node_type == 'group')}",
        f"  Chapters:        {sum(1 for b in bookmarks if b.node_type == 'chapter')}",
        f"  Sections:        {sum(1 for b in bookmarks if b.node_type == 'section')}",
        f"  Sub-sections:    {sum(1 for b in bookmarks if b.node_type == 'subsection')}",
        f"  Sub-sub-sections:{sum(1 for b in bookmarks if b.node_type == 'subsubsection')}",
        f"  Other:           {sum(1 for b in bookmarks if b.node_type == 'other')}",
        "",
        f"Leaf bookmarks (text extracted):  {sum(1 for b in bookmarks if b.is_leaf)}",
        f"Leaf sections in output:          {len(sections)}",
        f"Cross-referenced sections:        {len(cross_refs)}",
        "",
    ]

    # Sanity checks
    empty_text = [s for s in sections if not s["text"]]
    if empty_text:
        lines.append(f"WARNING: {len(empty_text)} sections have empty text:")
        for s in empty_text[:15]:
            lines.append(f"  - {s['section_id'] or '(no id)'}: {s['title'][:60]}")
        if len(empty_text) > 15:
            lines.append(f"  ... and {len(empty_text) - 15} more")
        lines.append("")

    very_short = [s for s in sections if 0 < s["text_length"] < 50]
    if very_short:
        lines.append(f"NOTE: {len(very_short)} sections have very short text (<50 chars):")
        for s in very_short[:15]:
            lines.append(f"  - {s['section_id'] or '(no id)'}: {s['text_length']} chars — {s['title'][:50]}")
        if len(very_short) > 15:
            lines.append(f"  ... and {len(very_short) - 15} more")
        lines.append("")

    unresolved = [b for b in bookmarks if b.page_index < 0]
    if unresolved:
        lines.append(f"WARNING: {len(unresolved)} bookmarks had unresolved page numbers:")
        for b in unresolved[:10]:
            lines.append(f"  - {b.title[:60]}")
        lines.append("")

    no_top = [b for b in bookmarks if b.top is None and b.is_leaf]
    if no_top:
        lines.append(f"NOTE: {len(no_top)} leaf bookmarks have no /Top coordinate:")
        for b in no_top[:10]:
            lines.append(f"  - {b.section_id or '(no id)'}: {b.title[:60]}")
        lines.append("")

    # Text length statistics
    lengths = [s["text_length"] for s in sections if s["text_length"] > 0]
    if lengths:
        lines.append("Text length statistics (chars):")
        lines.append(f"  Min:    {min(lengths)}")
        lines.append(f"  Max:    {max(lengths)}")
        lines.append(f"  Mean:   {sum(lengths) / len(lengths):.0f}")
        lines.append(f"  Median: {sorted(lengths)[len(lengths) // 2]}")
        lines.append(f"  Total:  {sum(lengths):,}")
        lines.append("")

    # Per-chapter summary
    chapter_counts: dict[str, int] = {}
    for s in sections:
        ch = s.get("chapter", "unknown")
        chapter_counts[ch] = chapter_counts.get(ch, 0) + 1
    lines.append(f"Sections per chapter ({len(chapter_counts)} chapters):")
    for ch in sorted(chapter_counts.keys(), key=lambda x: (x.replace("SBL", "~"), x)):
        lines.append(f"  Ch {ch:>8s}: {chapter_counts[ch]} sections")
    lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pre-process the Freddie Mac Multifamily Guide PDF into a structured index."
    )
    parser.add_argument(
        "pdf_path",
        help="Path to the Multifamily Guide PDF file.",
    )
    parser.add_argument(
        "--output-dir",
        default="./mf_guide_index",
        help="Directory to write output files (default: ./mf_guide_index).",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    output_dir = Path(args.output_dir)

    if not pdf_path.exists():
        log.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # ------------------------------------------------------------------
    # Step 1: Flatten bookmarks from outline
    # ------------------------------------------------------------------
    log.info("Step 1/5: Reading PDF outline...")
    reader = pypdf.PdfReader(str(pdf_path))
    bookmarks = flatten_outline(reader)

    if not bookmarks:
        log.error("No bookmarks found in PDF. Is this the right file?")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Classify each bookmark
    # ------------------------------------------------------------------
    log.info("Step 2/5: Classifying bookmarks...")
    classify_bookmarks(bookmarks)

    # ------------------------------------------------------------------
    # Step 3: Build navigation tree
    # ------------------------------------------------------------------
    log.info("Step 3/5: Building hierarchy tree...")
    tree = build_hierarchy_tree(bookmarks)

    tree_path = output_dir / "hierarchy_tree.json"
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)
    log.info("  → Wrote %s", tree_path)

    # ------------------------------------------------------------------
    # Step 4: Extract leaf-level section text
    # ------------------------------------------------------------------
    log.info("Step 4/5: Extracting section text (this may take a few minutes)...")
    sections = extract_sections(pdf_path, bookmarks)

    sections_path = output_dir / "structured_sections.json"
    with open(sections_path, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=2, ensure_ascii=False)
    log.info("  → Wrote %s", sections_path)

    # ------------------------------------------------------------------
    # Step 5: Build cross-reference index
    # ------------------------------------------------------------------
    log.info("Step 5/5: Building cross-reference index...")
    cross_refs = build_cross_references(sections)

    xref_path = output_dir / "cross_references.json"
    with open(xref_path, "w", encoding="utf-8") as f:
        json.dump(cross_refs, f, indent=2, ensure_ascii=False)
    log.info("  → Wrote %s", xref_path)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    report = generate_report(bookmarks, tree, sections, cross_refs)
    report_path = output_dir / "extraction_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    log.info("  → Wrote %s", report_path)

    elapsed = time.time() - t0
    log.info("Done in %.1f seconds.", elapsed)
    print()
    print(report)


if __name__ == "__main__":
    main()