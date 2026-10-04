from fastapi import APIRouter

from app.api.schemas import HealthResponse

router = APIRouter(prefix="/api")


@router.get("/healthz", response_model=HealthResponse, tags=["health"], operation_id="getHealth")
def health() -> HealthResponse:
    return HealthResponse(status="ok", api_version="v1")
