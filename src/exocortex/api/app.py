"""FastAPI application for the exocortex service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from exocortex.api.routes.graphs import router as graphs_router
from exocortex.api.routes.health import router as health_router
from exocortex.api.routes.targets import router as targets_router
from exocortex.core.checkpoint import SQLiteCheckpointStore
from exocortex.targets.service import TargetService


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Manage checkpoint store lifecycle."""
    db_path = Path.home() / ".exocortex" / "checkpoints.db"
    store = SQLiteCheckpointStore(db_path)
    app.state.checkpoint_store = store
    app.state.engines = {}
    app.state.runs = {}
    repo_root = Path(__file__).resolve().parents[3]
    app.state.target_service = TargetService(repo_root=repo_root)
    yield
    await store.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Exocortex",
        description="External cognitive system — graph execution engine",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(graphs_router, prefix="/api")
    app.include_router(targets_router)
    return app
