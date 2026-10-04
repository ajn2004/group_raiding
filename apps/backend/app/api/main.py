"""FastAPI application entrypoint, independent from the Discord bot."""

from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(
    title="Group Raiding API",
    description="Versioned HTTP boundary for the Group Raiding applications.",
    version="1.0.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)
app.include_router(router)
