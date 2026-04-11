import inspect

from turborefi.agents.runner import build_runner_agent
from turborefi.api import build_api
from turborefi.config import load_settings
from turborefi.services.session_service import TurboRefiSessionService
from turborefi.workflow import TurboRefiWorkflow


settings = load_settings()
session_service = TurboRefiSessionService(settings=settings)
workflow = TurboRefiWorkflow(settings=settings, retrieval_service=session_service.retrieval_service)

runner_agent = build_runner_agent(settings=settings, workflow=workflow)
loan_officer_agent = session_service.loa_agent
verifier_agent = session_service.verifier_agent
api = build_api(session_service)


def build_playground():
    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS
    from agno.os.interfaces.agui import AGUI

    agent_os_kwargs = {
        "db": SqliteDb(db_file=str(settings.agno_storage_db)),
        "agents": [loan_officer_agent, verifier_agent, runner_agent],
        "name": "TurboRefi Local",
        "description": "TurboRefi production backend with uploads, deterministic packet building, and verifier support.",
        "base_app": api,
        "interfaces": [
            AGUI(agent=loan_officer_agent, prefix="/v1"),
            AGUI(agent=verifier_agent, prefix="/verifier"),
            AGUI(agent=runner_agent, prefix="/runner"),
        ],
    }
    agent_os_params = inspect.signature(AgentOS).parameters
    if "on_route_conflict" in agent_os_params:
        agent_os_kwargs["on_route_conflict"] = "preserve_base_app"
    return AgentOS(**agent_os_kwargs)


agent_os = build_playground()
app = agent_os.get_app()


def main() -> None:
    agent_os.serve(
        app="playground:app",
        host=settings.playground_host,
        port=settings.playground_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
