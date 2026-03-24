"""
Guide Explorer — Interactive CLI
=================================

Navigate preprocessed regulatory guide indices the same way the agent would.
Validates that the retrieval tool works correctly by letting you walk the
hierarchy, read sections, inspect cross-references, and search titles.

USAGE:
    python explore_guide.py <index_dir> [<index_dir2> ...]

    # Single guide
    python explore_guide.py ./selling_guide_index

    # Multiple guides (switch between them)
    python explore_guide.py ./selling_guide_index ./mf_guide_index

COMMANDS:
    <id>          Drill into a node or read a leaf section
    back / ..     Go up one level
    top           Return to top-level view
    read <id>     Read full text of a section (even if it has children)
    refs <id>     Show cross-references for a section
    expand <id>   Fetch section + all its references (1 hop)
    search <q>    Keyword search across section titles
    stats         Show index statistics
    switch        Switch between loaded guides (if multiple)
    help          Show this help
    quit / q      Exit
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

# Allow importing guide_tool from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from guide_tool import GuideTool


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

# Terminal width for wrapping long text
try:
    TERM_WIDTH = os.get_terminal_size().columns
except OSError:
    TERM_WIDTH = 100

SEPARATOR = "─" * min(TERM_WIDTH, 80)
THICK_SEPARATOR = "═" * min(TERM_WIDTH, 80)


def print_header(tool: GuideTool):
    s = tool.stats()
    print()
    print(THICK_SEPARATOR)
    print(f"  Guide Explorer: {s['guide']}")
    print(f"  {s['total_leaf_sections']} sections loaded | {s['total_tree_nodes']} tree nodes | Type 'help' for commands")
    print(THICK_SEPARATOR)


def print_contents(items: list[dict], current_path: str | None):
    """Display the children of the current navigation node."""
    if not items:
        print("  (no children)")
        return

    if items and "error" in items[0]:
        print(f"  {items[0]['error']}")
        return

    # Find max id width for alignment
    max_id_len = max(len(item["id"]) for item in items)

    for item in items:
        leaf_marker = " ★" if not item["has_children"] else ""
        date_str = f"  ({item['date']})" if item.get("date") else ""
        id_padded = item["id"].ljust(max_id_len)
        print(f"  [{id_padded}]  {item['title']}{date_str}  ({item['type']}){leaf_marker}")

    leaf_count = sum(1 for i in items if not i["has_children"])
    if leaf_count > 0:
        print(f"\n  (★ = leaf section — type its ID to read full text)")


def print_section(data: dict, truncate: int | None = None):
    """Display a section's full text and metadata."""
    if "error" in data:
        print(f"  {data['error']}")
        return

    print()
    print(THICK_SEPARATOR)
    sid = data.get("section_id", "(no id)")
    title = data.get("title", "(no title)")
    print(f"  {sid}: {title}")

    meta_parts = []
    if data.get("date"):
        meta_parts.append(f"Date: {data['date']}")
    meta_parts.append(f"{data.get('text_length', 0):,} chars")
    if data.get("start_page") is not None:
        start = data["start_page"]
        end = data.get("end_page", start)
        meta_parts.append(f"Pages {start}–{end}")
    if data.get("chapter"):
        meta_parts.append(f"Chapter: {data['chapter']}")
    print(f"  {' | '.join(meta_parts)}")

    refs = data.get("references", [])
    cited_by = data.get("cited_by", [])
    if refs:
        print(f"  References: {', '.join(refs)}")
    if cited_by:
        print(f"  Cited by:   {', '.join(cited_by)}")

    print(THICK_SEPARATOR)
    print()

    text = data.get("text", "(no text extracted)")
    if truncate and len(text) > truncate:
        print(text[:truncate])
        remaining = len(text) - truncate
        print(f"\n  ... [{remaining:,} more chars — type 'read {sid}' to see full text]")
    else:
        print(text)

    print()


def print_refs(tool: GuideTool, section_id: str):
    """Display cross-references for a section."""
    data = tool.get_section(section_id)
    if "error" in data:
        print(f"  {data['error']}")
        return

    print()
    print(f"  Cross-references for: {section_id}")
    print(SEPARATOR)

    refs = data.get("references", [])
    cited_by = data.get("cited_by", [])

    if refs:
        print(f"\n  This section cites ({len(refs)}):")
        for ref_id in refs:
            ref_data = tool.sections.get(ref_id, {})
            ref_title = ref_data.get("title", "(unknown)")
            print(f"    → {ref_id}  {ref_title}")
    else:
        print("\n  This section cites: (none)")

    if cited_by:
        print(f"\n  Cited BY ({len(cited_by)}):")
        for ref_id in cited_by:
            ref_data = tool.sections.get(ref_id, {})
            ref_title = ref_data.get("title", "(unknown)")
            print(f"    ← {ref_id}  {ref_title}")
    else:
        print("\n  Cited by: (none)")

    print()


def print_expand(tool: GuideTool, section_id: str):
    """Fetch a section plus all its references and show summary."""
    result = tool.get_section_with_references(section_id, depth=1)

    if not result["sections"]:
        print(f"  No sections found for '{section_id}'")
        return

    print()
    print(f"  Expanded context for: {section_id}")
    print(SEPARATOR)
    print(f"  Total sections fetched: {len(result['sections'])}")
    print(f"  Total text: {result['total_text_length']:,} chars")
    print()

    for s in result["sections"]:
        marker = " ← primary" if s.get("section_id") == section_id else ""
        print(f"  [{s.get('section_id', '?')}]  {s.get('title', '?')}  ({s.get('text_length', 0):,} chars){marker}")

    print()


def print_search(tool: GuideTool, query: str):
    """Search titles and display results."""
    results = tool.search_titles(query)

    print()
    if not results:
        print(f"  No sections found matching '{query}'")
    else:
        print(f"  Found {len(results)} sections matching '{query}':")
        print(SEPARATOR)
        for r in results[:30]:
            ch = f"  (Ch {r['chapter']})" if r.get("chapter") else ""
            print(f"  [{r['section_id']}]  {r['title']}{ch}  — {r['text_length']:,} chars")
        if len(results) > 30:
            print(f"  ... and {len(results) - 30} more")
    print()


def print_help():
    print("""
  NAVIGATION:
    <id>              Drill into a node or read a leaf section
    back  / ..        Go up one level
    top               Return to top-level view

  READING:
    read <id>         Read full text of any section
    refs <id>         Show cross-references (forward + reverse)
    expand <id>       Fetch section + all sections it references

  SEARCH:
    search <query>    Keyword search across all section titles
                      (e.g., 'search refinance cash-out')

  OTHER:
    stats             Show index statistics
    switch            Switch between loaded guides (if multiple)
    help              Show this help
    quit / q          Exit
    """)


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python explore_guide.py <index_dir> [<index_dir2> ...]")
        print("  e.g., python explore_guide.py ./selling_guide_index ./mf_guide_index")
        sys.exit(1)

    # Load all specified guides
    guides: list[tuple[str, GuideTool]] = []
    for path_str in sys.argv[1:]:
        index_path = Path(path_str)
        if not index_path.exists():
            print(f"Warning: '{index_path}' not found, skipping.")
            continue
        try:
            tool = GuideTool(index_path)
            guides.append((index_path.name, tool))
            print(f"Loaded: {index_path.name} ({tool.total_sections} sections)")
        except Exception as e:
            print(f"Error loading '{index_path}': {e}")

    if not guides:
        print("No guides loaded. Exiting.")
        sys.exit(1)

    # Start with the first guide
    current_guide_idx = 0
    tool = guides[current_guide_idx][1]

    print_header(tool)

    # Navigation state
    nav_stack: list[str | None] = []  # stack of paths for 'back'
    current_path: str | None = None

    # Show top level
    print(f"\n  Showing: TOP LEVEL")
    print(f"  {SEPARATOR}")
    print_contents(tool.list_contents(None), None)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        # --- Exit ---
        if cmd in ("quit", "q", "exit"):
            print("Bye!")
            break

        # --- Help ---
        elif cmd == "help":
            print_help()

        # --- Stats ---
        elif cmd == "stats":
            s = tool.stats()
            print(f"\n  Guide:             {s['guide']}")
            print(f"  Tree nodes:        {s['total_tree_nodes']}")
            print(f"  Leaf sections:     {s['total_leaf_sections']}")
            print(f"  Cross-references:  {s['total_cross_references']}")

        # --- Switch guide ---
        elif cmd == "switch":
            if len(guides) < 2:
                print("  Only one guide loaded. Nothing to switch to.")
            else:
                print("\n  Available guides:")
                for i, (name, g) in enumerate(guides):
                    marker = " ← current" if i == current_guide_idx else ""
                    print(f"    [{i}] {name} ({g.total_sections} sections){marker}")
                try:
                    choice = input("  Enter number: ").strip()
                    idx = int(choice)
                    if 0 <= idx < len(guides):
                        current_guide_idx = idx
                        tool = guides[current_guide_idx][1]
                        nav_stack.clear()
                        current_path = None
                        print_header(tool)
                        print(f"\n  Showing: TOP LEVEL")
                        print(f"  {SEPARATOR}")
                        print_contents(tool.list_contents(None), None)
                    else:
                        print("  Invalid choice.")
                except (ValueError, EOFError):
                    print("  Cancelled.")

        # --- Top ---
        elif cmd == "top":
            nav_stack.clear()
            current_path = None
            print(f"\n  Showing: TOP LEVEL")
            print(f"  {SEPARATOR}")
            print_contents(tool.list_contents(None), None)

        # --- Back ---
        elif cmd in ("back", ".."):
            if nav_stack:
                current_path = nav_stack.pop()
            else:
                current_path = None
            label = current_path or "TOP LEVEL"
            print(f"\n  Showing: {label}")
            print(f"  {SEPARATOR}")
            print_contents(tool.list_contents(current_path), current_path)

        # --- Read section ---
        elif cmd.startswith("read "):
            section_id = user_input[5:].strip()
            data = tool.get_section(section_id)
            print_section(data)

        # --- Refs ---
        elif cmd.startswith("refs "):
            section_id = user_input[5:].strip()
            print_refs(tool, section_id)

        # --- Expand ---
        elif cmd.startswith("expand "):
            section_id = user_input[7:].strip()
            print_expand(tool, section_id)

        # --- Search ---
        elif cmd.startswith("search "):
            query = user_input[7:].strip()
            if query:
                print_search(tool, query)
            else:
                print("  Usage: search <keywords>")

        # --- Navigate or read ---
        else:
            # The user typed something — could be a nav path or a section_id.
            # Strategy: try to navigate first. If the node has no children
            # (it's a leaf), show its text instead.

            target = user_input.strip()

            # Check if it's a known section (leaf) in structured_sections
            if target in tool.sections:
                # It's a leaf — check if it also has children in the tree
                tree_node = tool._node_index.get(target)
                if tree_node and tree_node.get("children"):
                    # It has children — show the contents (drill down)
                    nav_stack.append(current_path)
                    current_path = target
                    label = f"{tree_node.get('nav_id', target)} — {tree_node.get('title', '')}"
                    print(f"\n  Showing: {label}")
                    print(f"  {SEPARATOR}")
                    print_contents(tool.list_contents(target), target)
                else:
                    # Pure leaf — show truncated text
                    data = tool.get_section(target)
                    print_section(data, truncate=3000)
            elif target in tool._node_index:
                # It's a tree node — drill down
                nav_stack.append(current_path)
                current_path = target
                node = tool._node_index[target]
                label = f"{node.get('nav_id', target)} — {node.get('title', '')}"
                print(f"\n  Showing: {label}")
                print(f"  {SEPARATOR}")
                print_contents(tool.list_contents(target), target)
            else:
                # Try fuzzy match
                fuzzy = tool._fuzzy_find(target)
                if fuzzy:
                    nav_id = fuzzy.get("nav_id", target)
                    print(f"  (matched: {nav_id})")
                    nav_stack.append(current_path)
                    current_path = nav_id
                    label = f"{nav_id} — {fuzzy.get('title', '')}"
                    print(f"\n  Showing: {label}")
                    print(f"  {SEPARATOR}")
                    print_contents(tool.list_contents(nav_id), nav_id)
                else:
                    print(f"  '{target}' not found. Try 'search {target}' or 'help'.")


if __name__ == "__main__":
    main()