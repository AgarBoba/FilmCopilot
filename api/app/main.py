from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .commands import CanvasCommandService
from .assets import AssetService
from .config import Settings
from .db import Database
from .domain import DomainError
from .events import EventStore
from .repositories import CanvasRepository
from .agent.config import AgentConfig
from .agent.runtime import AgentService
from .agent.store import AgentStore
from .routes import agent, assets, canvases, events


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings.data_dir.mkdir(parents=True, exist_ok=True)
    app.state.database.init_schema()
    yield
    await app.state.agent_service.close()


def create_app(settings: Settings | None = None, agent_config: AgentConfig | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_path)
    database.init_schema()
    repository = CanvasRepository(database)
    event_store = EventStore(database)
    command_service = CanvasCommandService(repository, event_store)
    asset_service = AssetService(settings, database, repository)

    app = FastAPI(title="Film Copilot", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.canvas_repository = repository
    app.state.event_store = event_store
    app.state.canvas_command_service = command_service
    app.state.asset_service = asset_service
    app.state.agent_store = AgentStore(database)
    app.state.agent_service = AgentService(
        repository, command_service, app.state.agent_store, agent_config or AgentConfig.from_env()
    )

    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, error: DomainError) -> JSONResponse:
        status_code = {
            'NOT_FOUND': 404,
            'REVISION_CONFLICT': 409,
            'UNSUPPORTED_MEDIA_TYPE': 415,
            'RUN_ACTIVE': 409,
            'ALREADY_UNDONE': 409,
            'AGENT_NOT_CONFIGURED': 503,
        }.get(error.code, 422)
        return JSONResponse(
            status_code=status_code,
            content={'error': {'code': error.code, 'message': error.message}},
        )

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(canvases.router)
    app.include_router(events.router)
    app.include_router(assets.router)
    app.include_router(agent.router)

    return app


app = create_app()
