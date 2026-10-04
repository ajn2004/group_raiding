"""FastAPI application entrypoint, independent from the Discord bot."""

import logging

from fastapi import FastAPI

from app.api.routes import router
from app.api.auth import router as auth_router

app = FastAPI(
    title="Group Raiding API",
    description="Versioned HTTP boundary for the Group Raiding applications.",
    version="1.0.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)
app.include_router(router)
app.include_router(auth_router, prefix="/api")


class _RedactOAuthCallbackQuery(logging.Filter):
    """Uvicorn's access log includes scope query strings by default."""
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (isinstance(args, tuple) and len(args) == 5 and args[1] == "GET"
                and isinstance(args[2], str)
                and args[2].split("?", 1)[0] == "/api/auth/discord/callback"):
            record.args = (*args[:2], "/api/auth/discord/callback?[REDACTED]", *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactOAuthCallbackQuery())
