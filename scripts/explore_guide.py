"""
Interactive Selling Guide Explorer
==================================

A CLI for human validation of the Selling Guide retrieval tool.
"""

import argparse
import sys
import os
from pathlib import Path
from selling_guide_tool import SellingGuideTool


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_header(tool: SellingGuideTool):
    print("=" * 60)
    print("  FANNIE MAE SELLING GUIDE EXPLORER")
    print(f"  {len(tool.sections)} sections loaded | Type 'help' for commands")
    print("=" * 60)


def print_help():
    print("\nCommands:")
    print("  <path>        Drill down (e.g., 'A', 'A2', 'A2-1')")
    print("  <section_id>  Read a topic (e.g., 'A2-1-01')")
    print("  back          Go up one level")
    print("  top           Return to the Parts menu")
    print("  refs <id>     Show cross-references (forward & reverse)")
    print("  search <query> Find sections by title")
    print("  quit          Exit")


def display_contents(tool: SellingGuideTool, path: str | None):
    items = tool.list_contents(path)
    title = path or "TOP LEVEL"
    print(f"\nShowing: {title}")
    print("-" * 40)
    for item in items:
        leaf = " ★" if not item["has_children"] else ""
        print(f"  [{item['id']}]  {item['title']} ({item['type']}){leaf}")


def display_section(tool: SellingGuideTool, section_id: str):
    data = tool.get_section(section_id)
    if "error" in data:
        print(f"\nError: {data['error']}")
        return

    print("\n" + "=" * 60)
    print(f"{data['section_id']}: {data['title']}")
    print(f"Date: {data['date']} | {data['text_length']} chars | Pages {data['start_page']}–{data['end_page']}")
    print(f"References: {', '.join(data['references']) or 'none'}")
    print("-" * 60)
    print(data["text"])
    print("=" * 60)


def display_references(tool: SellingGuideTool, section_id: str):
    data = tool.get_section(section_id)
    if "error" in data:
        print(f"\nError: {data['error']}")
        return

    # Forward
    forward = data.get("references", [])
    print(f"\nCross-references FROM {section_id}:")
    for fid in forward:
        target = tool.sections.get(fid, {})
        print(f"  → {fid}  {target.get('title', 'Unknown')}")

    # Reverse
    reverse = [sid for sid, refs in tool.xrefs.items() if section_id in refs]
    print(f"\nCross-references TO {section_id} (cited by):")
    for rid in reverse:
        source = tool.sections.get(rid, {})
        print(f"  ← {rid}  {source.get('title', 'Unknown')}")


def main():
    parser = argparse.ArgumentParser(description="Explore the processed Selling Guide index.")
    parser.add_argument("index_dir", help="Path to the directory containing preprocessed JSON files.")
    args = parser.parse_args()

    tool = SellingGuideTool(args.index_dir)
    nav_stack = []
    current_path = None

    clear_screen()
    print_header(tool)
    display_contents(tool, current_path)

    try:
        while True:
            try:
                cmd = input("\n> ").strip()
            except EOFError:
                break

            if not cmd:
                continue

            if cmd.lower() in ["quit", "exit"]:
                break
            
            elif cmd.lower() == "help":
                print_help()
            
            elif cmd.lower() == "top":
                nav_stack = []
                current_path = None
                display_contents(tool, current_path)
            
            elif cmd.lower() == "back":
                if nav_stack:
                    current_path = nav_stack.pop()
                    display_contents(tool, current_path)
                else:
                    current_path = None
                    display_contents(tool, current_path)
            
            elif cmd.lower().startswith("refs "):
                target_id = cmd[5:].strip()
                display_references(tool, target_id)
            
            elif cmd.lower().startswith("search "):
                query = cmd[7:].strip()
                results = tool.search_titles(query)
                print(f"\nFound {len(results)} matches for '{query}':")
                for r in results:
                    print(f"  [{r['id']}]  {r['title']}")
            
            elif cmd in tool.sections:
                # User typed a section ID directly
                display_section(tool, cmd)
            
            else:
                # Assume it's a navigational path
                next_level = tool.list_contents(cmd)
                if next_level and "error" not in next_level[0]:
                    nav_stack.append(current_path)
                    current_path = cmd
                    display_contents(tool, current_path)
                else:
                    print(f"Command or path not recognized: {cmd}")

    except KeyboardInterrupt:
        pass
    
    print("\nGoodbye!")


if __name__ == "__main__":
    main()
