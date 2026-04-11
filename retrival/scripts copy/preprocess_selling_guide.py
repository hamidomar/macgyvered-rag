"""
Fannie Mae Selling Guide — Deterministic Pre-Processor
=======================================================

PURPOSE:
    Parse the Selling Guide PDF using its bookmark (outline) tree to build
    a structured index.  Every section's text is extracted by "front-assigning"
    content from one bookmark position to the next, using sub-page coordinates
    provided by pdfplumber.

OUTPUTS (written to --output-dir):
    1. hierarchy_tree.json   — full navigational tree  (Part→Subpart→Chapter→Section→Topic)
    2. structured_sections.json — leaf-level sections with extracted text
    3. extraction_report.txt — diagnostic summary (counts, warnings, sanity checks)

USAGE:
    python preprocess_selling_guide.py <path_to_pdf> [--output-dir ./output]

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
from dataclasses import dataclass, field, asdict
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
    node_type: str = ""        # part | subpart | chapter | section | topic | other
    section_id: str = ""       # e.g. "A2-1-01" (leaf-level sections only)
    date: str = ""             # e.g. "06/04/2025" parsed from title
    clean_title: str = ""      # title without the section_id and date


@dataclass
class TreeNode:
    """A node in the hierarchy tree (JSON-serialisable)."""
    node_id: str
    title: str
    node_type: str
    section_id: str = ""
    date: str = ""
    page_index: int = 0
    children: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 1 — Flatten the PDF outline
# ---------------------------------------------------------------------------

def flatten_outline(reader: pypdf.PdfReader) -> list[Bookmark]:
    """
    Walk the nested outline structure from pypdf and return a flat,
    *document-order* list of Bookmark objects with resolved page numbers.

    pypdf represents the outline as a list where:
      - dict items are bookmark entries
      - list items are children of the preceding dict entry

    We resolve each bookmark's /Page IndirectObject to a 0-based page index
    and grab the /Top y-coordinate for sub-page precision.
    """

    # --- Build a fast lookup: page-object-id → page-index ----------------
    # Two strategies because IndirectObject identity can be tricky:
    #   (a) Compare by object id() of the resolved page dict
    #   (b) Fallback: compare the idnum of the indirect reference itself

    page_obj_id_map: dict[int, int] = {}       # id(page_obj) → index
    page_idnum_map: dict[int, int] = {}         # indirect_ref.idnum → index

    for idx, page in enumerate(reader.pages):
        resolved = page.get_object()
        page_obj_id_map[id(resolved)] = idx
        # pypdf page objects carry .indirect_reference
        if hasattr(page, "indirect_reference") and page.indirect_reference:
            page_idnum_map[page.indirect_reference.idnum] = idx

    def _resolve_page(item: dict) -> Optional[int]:
        """Resolve a bookmark's /Page entry to a 0-based page index."""
        page_ref = item.get("/Page")
        if page_ref is None:
            return None

        # Strategy A: resolve and match by object identity
        resolved = page_ref.get_object() if hasattr(page_ref, "get_object") else page_ref
        if id(resolved) in page_obj_id_map:
            return page_obj_id_map[id(resolved)]

        # Strategy B: match by indirect-reference idnum
        if hasattr(page_ref, "idnum") and page_ref.idnum in page_idnum_map:
            return page_idnum_map[page_ref.idnum]

        # Strategy C: brute-force comparison (slow but last resort)
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

    # --- Recursive walk ----------------------------------------------------
    results: list[Bookmark] = []

    def _walk(items, depth: int = 0):
        for item in items:
            if isinstance(item, list):
                # Children of the preceding bookmark — increase depth
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
# Step 2 — Classify & parse each bookmark
# ---------------------------------------------------------------------------

# Regex for section IDs like A1-1-01, B3-3.1-02, E-3-26
SECTION_ID_RE = re.compile(
    r"^([A-E]\d?-\d[\d.]*-\d{2})"
)

# Date in parentheses at end of title: (MM/DD/YYYY)
DATE_RE = re.compile(r"\((\d{2}/\d{2}/\d{4})\)\s*$")

# Classification patterns (applied in order)
NODE_TYPE_PATTERNS = [
    (re.compile(r"^Part [A-E],"),    "part"),
    (re.compile(r"^Subpart [A-E]\d"), "subpart"),
    (re.compile(r"^Chapter [A-E]"),   "chapter"),
    (re.compile(r"^Section [A-E]"),   "section"),    # e.g. "Section A2-3.1, ..."
]


def classify_bookmarks(bookmarks: list[Bookmark]) -> None:
    """Mutate each Bookmark in-place: set node_type, section_id, date, clean_title."""
    for bm in bookmarks:
        # --- Extract date ---
        date_match = DATE_RE.search(bm.title)
        if date_match:
            bm.date = date_match.group(1)

        # --- Extract section_id ---
        sid_match = SECTION_ID_RE.match(bm.title)
        if sid_match:
            bm.section_id = sid_match.group(1)

        # --- Determine node_type ---
        matched = False
        for pattern, ntype in NODE_TYPE_PATTERNS:
            if pattern.search(bm.title):
                bm.node_type = ntype
                matched = True
                break
        if not matched:
            if bm.section_id:
                bm.node_type = "topic"      # leaf-level like "A2-1-01, ..."
            else:
                bm.node_type = "other"       # cover page, TOC, Preface, etc.

        # --- Clean title: strip section_id prefix and date suffix ---
        clean = bm.title
        if bm.section_id:
            # Remove "A2-1-01, " prefix
            clean = re.sub(r"^[A-E]\d?-\d[\d.]*-\d{2},?\s*", "", clean)
        if bm.date:
            clean = DATE_RE.sub("", clean).strip()
        # Also strip leading type prefixes for non-leaf nodes
        for prefix in ("Part ", "Subpart ", "Chapter ", "Section "):
            if clean.startswith(prefix):
                # Keep the ID portion, just remove "Part " etc.
                # e.g. "Part A, Doing Business..." → "A, Doing Business..."
                clean = clean[len(prefix):]
                break
        bm.clean_title = clean.strip()


# ---------------------------------------------------------------------------
# Step 3 — Build the hierarchy tree (for navigation)
# ---------------------------------------------------------------------------

def build_hierarchy_tree(bookmarks: list[Bookmark]) -> list[dict]:
    """
    Build a nested tree from the flat, depth-annotated bookmark list.

    Uses a stack: each entry on the stack is (depth, TreeNode).
    When we encounter a bookmark at depth d, we pop everything deeper,
    then attach as a child of the current top-of-stack.

    Returns the tree as a JSON-serialisable list of dicts.
    """
    root_children: list[TreeNode] = []
    stack: list[tuple[int, TreeNode]] = []  # (depth, node)

    def _compute_node_id(bm: Bookmark) -> str:
        if bm.section_id:
            return bm.section_id
        
        # Regex to pull IDs from titles like "Part A, ..." or "Section A2-3.1, ..."
        title = bm.title
        if bm.node_type == "part":
            m = re.search(r"Part ([A-E])", title)
            if m: return m.group(1)
        elif bm.node_type == "subpart":
            m = re.search(r"Subpart ([A-E]\d)", title)
            if m: return m.group(1)
        elif bm.node_type == "chapter":
            m = re.search(r"Chapter ([A-E]\d?-\d[\d.]*)", title)
            if m: return m.group(1)
        elif bm.node_type == "section":
            m = re.search(r"Section ([A-E]\d?-\d[\d.]*)", title)
            if m: return m.group(1)
        return ""

    for bm in bookmarks:
        node = TreeNode(
            node_id=_compute_node_id(bm),
            title=bm.clean_title or bm.title,
            node_type=bm.node_type,
            section_id=bm.section_id,
            date=bm.date,
            page_index=bm.page_index,
        )

        # Pop nodes that are at the same depth or deeper
        while stack and stack[-1][0] >= bm.depth:
            stack.pop()

        if stack:
            stack[-1][1].children.append(node)
        else:
            root_children.append(node)

        stack.append((bm.depth, node))

    def _to_dict(node: TreeNode) -> dict:
        d = {
            "id": node.node_id,
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
    For each *leaf* bookmark (node_type == "topic"), extract the text from
    its (page, top) position to the next bookmark's (page, top) position.

    Uses pdfplumber which gives us word-level bounding boxes, so we can
    filter words by y-coordinate for precise splitting within a page.

    PDF coordinate system reminder:
        - Origin is bottom-left of the page.
        - /Top from bookmarks is distance from bottom.
        - pdfplumber uses top-left origin (y=0 at top of page).
        - Conversion: pdfplumber_y = page_height - pdf_top
    """

    # Identify leaf bookmarks and their boundaries
    # Boundary for bookmark[i] = from bookmark[i] position to bookmark[i+1] position
    # (regardless of whether i+1 is also a leaf — the next bookmark of ANY type
    #  marks the end of the current bookmark's content)

    # We need ALL bookmarks in order to compute boundaries, not just leaves
    all_bms = bookmarks

    # Pre-filter: only extract text for leaves
    leaf_indices = {i for i, bm in enumerate(all_bms) if bm.node_type == "topic"}
    log.info("Found %d leaf (topic) bookmarks to extract text for.", len(leaf_indices))

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
            start_top_pdf: Optional[float],   # PDF coords (from bottom)
            end_page: int,
            end_top_pdf: Optional[float],      # PDF coords (from bottom)
        ) -> str:
            """
            Extract all text from (start_page, start_top) to (end_page, end_top).

            pdfplumber y-axis: 0 = top of page, increases downward.
            PDF /Top y-axis: 0 = bottom of page, increases upward.

            Conversion: plumber_y = page_height - pdf_top

            "Front-assign" means we want text BELOW the start bookmark
            (higher plumber_y) and ABOVE the end bookmark (lower plumber_y).
            """
            text_parts: list[str] = []

            for pg_idx in range(start_page, min(end_page + 1, total_pages)):
                page = pdf.pages[pg_idx]
                height = _get_page_height(pg_idx)

                # Determine the y-window on this page (in pdfplumber coords)
                # Default: full page
                crop_top = 0.0       # pdfplumber: top of page
                crop_bottom = height  # pdfplumber: bottom of page

                if pg_idx == start_page and start_top_pdf is not None:
                    # Start below the bookmark position
                    crop_top = height - start_top_pdf

                if pg_idx == end_page and end_top_pdf is not None:
                    # End above the next bookmark position
                    crop_bottom = height - end_top_pdf

                # Safety: ensure crop_top < crop_bottom
                if crop_top >= crop_bottom:
                    continue

                # Crop the page to our region and extract
                cropped = page.within_bbox((0, crop_top, page.width, crop_bottom))
                page_text = cropped.extract_text()

                if page_text:
                    text_parts.append(page_text)

            return "\n".join(text_parts)

        # --- Iterate over all bookmarks, extract text for leaves -----------
        for i, bm in enumerate(all_bms):
            if i not in leaf_indices:
                continue

            # Start position: this bookmark
            start_page = bm.page_index
            start_top = bm.top

            # End position: next bookmark (any type), or end of document
            if i + 1 < len(all_bms):
                next_bm = all_bms[i + 1]
                end_page = next_bm.page_index
                end_top = next_bm.top
            else:
                # Last bookmark — read to end of document
                end_page = total_pages - 1
                end_top = None  # means: to the bottom of the last page

            # Validate page indices
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

            # --- Parse hierarchy from section_id -------------------------
            # e.g. "A2-3.1-02" → part=A, subpart=A2, chapter=A2-3, section=A2-3.1
            part = subpart = chapter = section = ""
            sid = bm.section_id
            if sid:
                part_match = re.match(r"^([A-E])", sid)
                if part_match:
                    part = part_match.group(1)
                subpart_match = re.match(r"^([A-E]\d)", sid)
                if subpart_match:
                    subpart = subpart_match.group(1)
                # Chapter: everything up to the last hyphen-digits
                # A2-3.1-02 → chapter = A2-3, section = A2-3.1
                # A2-1-01   → chapter = A2-1
                parts = sid.rsplit("-", 1)
                if len(parts) == 2:
                    prefix = parts[0]  # e.g. "A2-3.1" or "A2-1"
                    # Check if there's a dotted section level
                    dot_parts = prefix.rsplit(".", 1)
                    if len(dot_parts) == 2 and dot_parts[1].isdigit():
                        section = prefix          # e.g. "A2-3.1"
                        chapter = dot_parts[0]    # e.g. "A2-3"
                    else:
                        chapter = prefix          # e.g. "A2-1"

            sections.append({
                "section_id": bm.section_id,
                "title": bm.clean_title,
                "full_title": bm.title,
                "date": bm.date,
                "part": part,
                "subpart": subpart,
                "chapter": chapter,
                "section": section,
                "start_page": bm.page_index,
                "end_page": end_page,
                "text": text.strip(),
                "text_length": len(text.strip()),
            })

        log.info("Extracted text for %d leaf sections.", len(sections))

    return sections


# ---------------------------------------------------------------------------
# Step 5 — Build a cross-reference index
# ---------------------------------------------------------------------------

def build_cross_references(sections: list[dict]) -> dict[str, list[str]]:
    """
    Scan each section's text for references to other section IDs.
    Returns a dict mapping each section_id to a list of referenced section_ids.

    This is the "citation index" from the architecture doc — it lets the agent
    expand context by pulling in related sections.
    """
    # Pattern matches things like A2-1-01, B3-3.2-05, E-3-26
    ref_pattern = re.compile(r"[A-E]\d?-\d[\d.]*-\d{2}")

    # Collect all known section IDs for validation
    known_ids = {s["section_id"] for s in sections if s["section_id"]}

    cross_refs: dict[str, list[str]] = {}

    for s in sections:
        sid = s["section_id"]
        if not sid:
            continue

        found_refs = set(ref_pattern.findall(s["text"]))
        # Remove self-references and references to unknown sections
        found_refs.discard(sid)
        valid_refs = sorted(found_refs & known_ids)

        if valid_refs:
            cross_refs[sid] = valid_refs

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
        "SELLING GUIDE PRE-PROCESSING REPORT",
        "=" * 70,
        "",
        f"Total bookmarks in outline:      {len(bookmarks)}",
        f"  Parts:      {sum(1 for b in bookmarks if b.node_type == 'part')}",
        f"  Subparts:   {sum(1 for b in bookmarks if b.node_type == 'subpart')}",
        f"  Chapters:   {sum(1 for b in bookmarks if b.node_type == 'chapter')}",
        f"  Sections:   {sum(1 for b in bookmarks if b.node_type == 'section')}",
        f"  Topics:     {sum(1 for b in bookmarks if b.node_type == 'topic')}",
        f"  Other:      {sum(1 for b in bookmarks if b.node_type == 'other')}",
        "",
        f"Leaf sections extracted:         {len(sections)}",
        f"Cross-referenced sections:       {len(cross_refs)}",
        "",
    ]

    # Sanity checks
    empty_text = [s for s in sections if not s["text"]]
    if empty_text:
        lines.append(f"WARNING: {len(empty_text)} sections have empty text:")
        for s in empty_text[:10]:
            lines.append(f"  - {s['section_id']}: {s['title']}")
        if len(empty_text) > 10:
            lines.append(f"  ... and {len(empty_text) - 10} more")
        lines.append("")

    very_short = [s for s in sections if 0 < s["text_length"] < 50]
    if very_short:
        lines.append(f"NOTE: {len(very_short)} sections have very short text (<50 chars):")
        for s in very_short[:10]:
            lines.append(f"  - {s['section_id']}: {s['text_length']} chars — {s['title']}")
        lines.append("")

    unresolved = [b for b in bookmarks if b.page_index < 0]
    if unresolved:
        lines.append(f"WARNING: {len(unresolved)} bookmarks had unresolved page numbers:")
        for b in unresolved[:10]:
            lines.append(f"  - {b.title}")
        lines.append("")

    no_top = [b for b in bookmarks if b.top is None and b.node_type == "topic"]
    if no_top:
        lines.append(f"NOTE: {len(no_top)} topic bookmarks have no /Top coordinate (full-page extraction used):")
        for b in no_top[:10]:
            lines.append(f"  - {b.section_id}: {b.title}")
        lines.append("")

    # Text length statistics
    lengths = [s["text_length"] for s in sections if s["text_length"] > 0]
    if lengths:
        lines.append("Text length statistics (chars):")
        lines.append(f"  Min:    {min(lengths)}")
        lines.append(f"  Max:    {max(lengths)}")
        lines.append(f"  Mean:   {sum(lengths) / len(lengths):.0f}")
        lines.append(f"  Median: {sorted(lengths)[len(lengths)//2]}")
        lines.append(f"  Total:  {sum(lengths):,}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pre-process the Fannie Mae Selling Guide PDF into a structured index."
    )
    parser.add_argument(
        "pdf_path",
        help="Path to the Selling Guide PDF file.",
    )
    parser.add_argument(
        "--output-dir",
        default="./selling_guide_index",
        help="Directory to write output files (default: ./selling_guide_index).",
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
