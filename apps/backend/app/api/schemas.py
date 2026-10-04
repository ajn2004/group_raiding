"""Public API response contracts."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    api_version: str
