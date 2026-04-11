import pypdf
import pprint

reader = pypdf.PdfReader(
    r"C:\Users\omrha\Desktop\Projects\RAG_Loan_Refinance\data\pdfs\02 04 2026 Single Family Selling Guide_highlighting.pdf"
)

def iter_outline(items, depth=0):
    for item in items:
        if isinstance(item, list):
            iter_outline(item, depth + 1)
        else:
            yield depth, item.get("/Title", "").strip()

# count = 0
# for depth, title in iter_outline(reader.outline):
#     print(f"{'  ' * depth}[{depth}] {title}")
#     count += 1
#     if count >= 100:
#         break

"""
Why only 8 lines instead of 100

Because the outline tree is wider than it is deep at the top level. Your iter_outline is a generator using yield — it yields one title, then recurses into children via iter_outline(item, depth+1). But notice: the children are list items in the pypdf outline format. When it hits a list, it recurses but doesn't yield anything from that branch before moving on.
Wait — actually it does recurse correctly. The real reason is simpler: the top-level has only 8 entries and none of them have children showing up. The Parts (A, B, C, D, E) are [0] but their children (Subparts, Chapters) are stored as list items after the parent in the outline. pypdf represents children as a list that follows the parent node. Your script is hitting the 8 top-level items and then... the children are lists, which recurse, but those lists might be empty or the structure differs from expectation.

Run this to see the raw structure:
```
pythonprint(type(reader.outline[0]))   # the first item
print(type(reader.outline[1]))   # probably also a dict
print(len(reader.outline))       # how many top-level items total
for i, item in enumerate(reader.outline):
    print(i, type(item), item.get("/Title", "LIST") if not isinstance(item, list) else f"LIST len={len(item)}")

```
This will reveal whether the children are actually attached or if the outline is flatter than expected.

PDF
 ↓
Extract outline (pypdf)
 ↓
Flatten hierarchy
 ↓
Resolve page numbers
 ↓
Extract page text
 ↓
Determine section boundaries
 ↓
Build structured index
 ↓
Store for retrieval

"""

with open("outline_dump.txt", "w", encoding="utf-8") as f:
    pprint.pprint(reader.outline, stream=f)