import os
import sys

# Add the backend directory to sys.path so we can import src correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent import get_rag_agent

def main():
    print("==================================================")
    print("         Guide Expert RAG - Terminal UI           ")
    print("==================================================")
    print("Type 'exit' or 'quit' to end the session.\n")
    
    rag_agent = get_rag_agent()
    
    # Optional greeting if desired
    # rag_agent.print_response("Hello! What guidelines would you like to search today?", stream=True)

    while True:
        try:
            user_input = input("\n[You] \n> ")
            if user_input.lower().strip() in ["exit", "quit", "q"]:
                break
            if not user_input.strip():
                continue
            
            print("\n[Guide Expert RAG]")
            rag_agent.print_response(user_input, stream=True)
        except KeyboardInterrupt:
            # Handle Ctrl+C smoothly
            break
        except Exception as e:
            print(f"\n[Error]: {e}")

if __name__ == "__main__":
    main()
