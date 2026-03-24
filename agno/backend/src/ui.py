def print_ui_instructions() -> None:
    print("This project now uses Agno AgentOS + AG-UI instead of Streamlit.")
    print("Run `python playground.py` from the project root.")
    print("The Agno backend will serve on http://localhost:7777 by default.")
    print("Connect Agent UI to `http://localhost:7777/v1`.")
    print("Custom document endpoints remain available at `/session`, `/session/{session_id}/upload`, `/session/{session_id}/status`, and `/session/{session_id}/result`.")


if __name__ == "__main__":
    print_ui_instructions()
