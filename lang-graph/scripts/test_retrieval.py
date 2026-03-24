from selling_guide_tool import SellingGuideTool

tool = SellingGuideTool("../output/selling_guide_preprocessed")

# Test 1: Navigation
print("--- Navigation Test ---")
top = tool.list_contents()
print(f"Top level IDs: {[node['id'] for node in top]}")

# Test 2: Search
print("\n--- Search Test ---")
results = tool.search_titles("cash-out refinance")
print(f"Found {len(results)} matches for 'cash-out refinance'")
for r in results[:3]:
    print(f"  [{r['id']}] {r['title']}")

# Test 3: Retrieval
print("\n--- Retrieval Test ---")
if results:
    sid = results[0]['id']
    section = tool.get_section(sid)
    print(f"Section {sid} title: {section['title']}")
    print(f"Text snippet: {section['text'][:200]}...")
