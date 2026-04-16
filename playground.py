from turborefi.api import build_api
from turborefi.config import load_settings
from turborefi.services.session_service import TurboRefiSessionService


settings = load_settings()
session_service = TurboRefiSessionService(settings=settings)
app = build_api(session_service)


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=settings.playground_host,
        port=settings.playground_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
