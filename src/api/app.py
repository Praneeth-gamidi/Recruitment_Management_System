from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.router import api_router
from src.core.config import Settings, get_settings
from src.core.exceptions import register_exception_handlers
from src.core.logging import configure_logging
from src.database.session import engine


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logger = configure_logging(app_settings.log_level)
        logger.info(
            "Application starting",
            extra={"application": app_settings.app_name, "environment": app_settings.environment},
        )
        try:
            yield
        finally:
            logger.info("Application shutting down")
            engine.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="Recruiter dashboard and recruitment workflow MVP.",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Accept", "Content-Type"],
    )
    register_exception_handlers(application)
    application.include_router(api_router)
    application.mount(
        "/ui",
        StaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="recruitment-ui",
    )

    @application.get("/careers", include_in_schema=False)
    def careers_portal() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "careers.html")

    return application


app = create_app()
