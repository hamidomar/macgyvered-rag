from selling_guide_tool import SellingGuideTool

tool = SellingGuideTool("../output/selling_guide_preprocessed")

# Test 1: Navigation
print("--- Navigation Test ---")
top = tool.list_contents()
print(f"Top level IDs: {[node['id'] for node in top]}")



# Test 3: Retrieval
print("\n--- Retrieval Test ---")
sid = "B3-3.1-01"
section = tool.get_section(sid)
print(f"Section {sid} title: {section['title']}")
print(f"Text snippet: {section['text'][:200]}...")
