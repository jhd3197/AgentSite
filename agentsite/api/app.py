"""FastAPI application factory for AgentSite."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import init_prompture, settings
from . import deps
from .routes import (
    agents,
    assets,
    brand,
    chat,
    components,
    design_systems,
    directions,
    discovery,
    edit,
    generate,
    memory,
    models,
    preview,
    projects,
    prompt_templates,
    providers,
    skills,
    templates,
)

logger = logging.getLogger("agentsite.api")

# Prefer the built frontend (Vite output), fall back to source frontend dir
_pkg_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
_cwd_frontend_dist = Path.cwd() / "frontend" / "dist"
_pkg_frontend = Path(__file__).resolve().parent.parent.parent / "frontend"
_cwd_frontend = Path.cwd() / "frontend"

if _pkg_frontend_dist.exists():
    FRONTEND_DIR = _pkg_frontend_dist
elif _cwd_frontend_dist.exists():
    FRONTEND_DIR = _cwd_frontend_dist
elif _pkg_frontend.exists():
    FRONTEND_DIR = _pkg_frontend
else:
    FRONTEND_DIR = _cwd_frontend


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: connect DB on startup, close on shutdown."""
    # Load .env into os.environ so provider API keys are visible everywhere
    _env_path = Path.cwd() / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
    settings.ensure_dirs()
    # Configure prompture's tracker/cache even when the ASGI app is served
    # directly (uvicorn/Docker) rather than through `agentsite serve`.
    try:
        init_prompture()
    except Exception:  # pragma: no cover - prompture config is best-effort
        logger.warning("init_prompture() failed; usage tracking disabled", exc_info=True)
    await deps.db.connect()
    deps.project_repo = deps.ProjectRepository(deps.db)
    deps.page_repo = deps.PageRepository(deps.db)
    deps.version_repo = deps.VersionRepository(deps.db)
    deps.agent_config_repo = deps.AgentConfigRepository(deps.db)
    deps.agent_run_repo = deps.AgentRunRepository(deps.db)
    deps.message_repo = deps.MessageRepository(deps.db)
    deps.memory_repo = deps.MemoryRepository(deps.db)
    deps.design_system_repo = deps.DesignSystemRepository(deps.db)
    deps.project_component_repo = deps.ProjectComponentRepository(deps.db)
    # Backfill costs for runs recorded before cost tracking was added
    try:
        updated = await deps.agent_run_repo.backfill_costs()
        if updated:
            logger.info("Backfilled costs for %d agent runs", updated)
    except Exception:
        logger.debug("Cost backfill skipped", exc_info=True)
    logger.info("AgentSite started — data dir: %s", settings.data_dir)
    yield
    await deps.db.close()
    logger.info("AgentSite shutdown")


def create_app(
    custom_lifespan=None,
    extra_routers=None,
    extra_middleware=None,
) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        custom_lifespan: Replaces the default lifespan (for custom DB init, auth setup).
        extra_routers: List of APIRouter to include after the default ones.
        extra_middleware: List of (middleware_class, kwargs) tuples to add.
    """
    app = FastAPI(
        title="AgentSite",
        description="AI-Powered Website Builder using Prompture",
        version="0.1.0",
        lifespan=custom_lifespan or lifespan,
    )

    # CORS for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Extra middleware (added before routes, after CORS)
    if extra_middleware:
        for middleware_cls, kwargs in extra_middleware:
            app.add_middleware(middleware_cls, **kwargs)

    # Lightweight health check (no external calls)
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    # API routes
    app.include_router(projects.router)
    app.include_router(generate.router)
    app.include_router(chat.router)
    app.include_router(models.router)
    app.include_router(assets.router)
    app.include_router(preview.router)
    app.include_router(providers.router)
    app.include_router(agents.router)
    app.include_router(discovery.router)
    app.include_router(directions.router)
    app.include_router(skills.router)
    app.include_router(brand.router)
    app.include_router(design_systems.router)
    app.include_router(memory.router)
    app.include_router(prompt_templates.router)
    app.include_router(edit.router)
    app.include_router(components.router)
    app.include_router(templates.router)

    # Extra routers (e.g. auth, landing page)
    if extra_routers:
        for router in extra_routers:
            app.include_router(router)

    # Serve frontend static files
    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend-static")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            """Serve static files or fall back to index.html for SPA routing."""
            if full_path.startswith(("api/", "ws/", "preview/")):
                raise HTTPException(status_code=404)

            # Try serving the exact file first
            file_path = FRONTEND_DIR / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)

            # Fall back to index.html for client-side routing
            index = FRONTEND_DIR / "index.html"
            if index.exists():
                return FileResponse(index)

            raise HTTPException(status_code=404)

    return app
