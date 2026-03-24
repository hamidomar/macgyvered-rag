from src.app import agent_os, app

if __name__ == "__main__":
    agent_os.serve(app="playground:app", reload=True)
