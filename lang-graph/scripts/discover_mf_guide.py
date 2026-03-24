r"""
Freddie Mac Multifamily Guide — Discovery Script
==================================================

Run from: C:\Users\omrha\Desktop\Projects\RAG_Loan_Refinance\scripts
Reads:     ..\data\pdfs\mf_guide_full.pdf

Outputs (to ..\output\mf_discovery\):
    - mf_outline_dump.txt         (raw pprint of reader.outline)
    - mf_outline_flat.txt         (flattened: depth, page, top, title)
    - mf_discovery_summary.txt    (stats and sample text)
"""

import pypdf
import pdfplumber
import pprint
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
PDF_PATH = SCRIPT_DIR / ".." / "data" / "pdfs" / "mf_guide_full.pdf"
OUTPUT_DIR = SCRIPT_DIR / ".." / "output" / "mf_discovery"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Basic stats
# ---------------------------------------------------------------------------
print(f"Reading: {PDF_PATH.resolve()}")
reader = pypdf.PdfReader(str(PDF_PATH))
print(f"Total pages: {len(reader.pages)}")
print(f"Outline top-level items: {len(reader.outline)}")

# Page dimensions
dims = set()
for page in reader.pages[:20]:
    mb = page.mediabox
    dims.add((round(float(mb.width), 2), round(float(mb.height), 2)))
print(f"Page dimensions (first 20): {dims}")

# ---------------------------------------------------------------------------
# 2. Raw outline dump
# ---------------------------------------------------------------------------
raw_dump_path = OUTPUT_DIR / "mf_outline_dump.txt"
with open(raw_dump_path, "w", encoding="utf-8") as f:
    pprint.pprint(reader.outline, stream=f)
print(f"\nRaw outline dump → {raw_dump_path}")

# ---------------------------------------------------------------------------
# 3. Flatten outline with resolved page numbers
# ---------------------------------------------------------------------------

# Build page-object lookup
page_obj_id_map = {}
page_idnum_map = {}
for idx, page in enumerate(reader.pages):
    resolved = page.get_object()
    page_obj_id_map[id(resolved)] = idx
    if hasattr(page, "indirect_reference") and page.indirect_reference:
        page_idnum_map[page.indirect_reference.idnum] = idx


def resolve_page(item):
    page_ref = item.get("/Page")
    if page_ref is None:
        return None
    resolved = page_ref.get_object() if hasattr(page_ref, "get_object") else page_ref
    if id(resolved) in page_obj_id_map:
        return page_obj_id_map[id(resolved)]
    if hasattr(page_ref, "idnum") and page_ref.idnum in page_idnum_map:
        return page_idnum_map[page_ref.idnum]
    for i, pg in enumerate(reader.pages):
        if pg.get_object() is resolved:
            return i
    return None


def get_top(item):
    raw = item.get("/Top")
    if raw is None or str(raw) == "NullObject":
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


flat_bookmarks = []

def walk_outline(items, depth=0):
    for item in items:
        if isinstance(item, list):
            walk_outline(item, depth + 1)
        else:
            title = (item.get("/Title") or "").strip()
            page_idx = resolve_page(item)
            top = get_top(item)
            flat_bookmarks.append({
                "depth": depth,
                "page": page_idx,
                "top": top,
                "title": title,
            })


if reader.outline:
    walk_outline(reader.outline)
    print(f"Total bookmarks flattened: {len(flat_bookmarks)}")

    # Depth distribution
    depth_dist = {}
    for bm in flat_bookmarks:
        d = bm["depth"]
        depth_dist[d] = depth_dist.get(d, 0) + 1
    print(f"Depth distribution: {depth_dist}")

    # Unresolved pages
    unresolved = sum(1 for bm in flat_bookmarks if bm["page"] is None)
    print(f"Bookmarks with unresolved pages: {unresolved}")

    # No /Top coordinate
    no_top = sum(1 for bm in flat_bookmarks if bm["top"] is None)
    print(f"Bookmarks with no /Top: {no_top}")

    # Write flat dump
    flat_dump_path = OUTPUT_DIR / "mf_outline_flat.txt"
    with open(flat_dump_path, "w", encoding="utf-8") as f:
        for bm in flat_bookmarks:
            indent = "  " * bm["depth"]
            pg = str(bm["page"]) if bm["page"] is not None else "???"
            top = f"{bm['top']:.1f}" if bm["top"] is not None else "???"
            f.write(f"{indent}[d={bm['depth']}] page={pg:>5}  top={top:>8}  {bm['title']}\n")

    print(f"Flat outline → {flat_dump_path}")

    # Print first 30 and last 10 for quick inspection
    print("\n--- First 30 bookmarks ---")
    for bm in flat_bookmarks[:30]:
        indent = "  " * bm["depth"]
        pg = str(bm["page"]) if bm["page"] is not None else "???"
        top = f"{bm['top']:.1f}" if bm["top"] is not None else "???"
        print(f"  {indent}[d={bm['depth']}] page={pg:>5}  top={top:>8}  {bm['title'][:80]}")

    print(f"\n--- Last 10 bookmarks ---")
    for bm in flat_bookmarks[-10:]:
        indent = "  " * bm["depth"]
        pg = str(bm["page"]) if bm["page"] is not None else "???"
        top = f"{bm['top']:.1f}" if bm["top"] is not None else "???"
        print(f"  {indent}[d={bm['depth']}] page={pg:>5}  top={top:>8}  {bm['title'][:80]}")

else:
    print("\n⚠  NO OUTLINE FOUND in this PDF.")
    print("   The hyperlinks may be stored as page annotations instead.")
    print("   Checking first few pages for link annotations...\n")

    for pg_idx in range(min(5, len(reader.pages))):
        page = reader.pages[pg_idx]
        annots = page.get("/Annots")
        if annots:
            resolved = annots.get_object() if hasattr(annots, "get_object") else annots
            count = len(resolved) if isinstance(resolved, list) else "unknown"
            print(f"  Page {pg_idx}: {count} annotations")
        else:
            print(f"  Page {pg_idx}: no annotations")

# ---------------------------------------------------------------------------
# 4. Sample text from a few pages (using pdfplumber for quality check)
# ---------------------------------------------------------------------------
summary_path = OUTPUT_DIR / "mf_discovery_summary.txt"
with open(summary_path, "w", encoding="utf-8") as f:
    f.write(f"PDF: {PDF_PATH.resolve()}\n")
    f.write(f"Pages: {len(reader.pages)}\n")
    f.write(f"Bookmarks: {len(flat_bookmarks)}\n")
    f.write(f"Dimensions: {dims}\n\n")

    with pdfplumber.open(str(PDF_PATH)) as pdf:
        sample_pages = [0, 1, 2, 5, 10, 50, 100, len(pdf.pages) - 1]
        sample_pages = [p for p in sample_pages if p < len(pdf.pages)]

        for pg_idx in sample_pages:
            page = pdf.pages[pg_idx]
            text = page.extract_text() or "(no text)"
            f.write(f"{'='*60}\n")
            f.write(f"PAGE {pg_idx} (of {len(pdf.pages)})\n")
            f.write(f"{'='*60}\n")
            f.write(text[:2000])
            f.write("\n\n")

    print(f"\nSample text → {summary_path}")

print("\n✓ Discovery complete. Check output in:", OUTPUT_DIR.resolve())