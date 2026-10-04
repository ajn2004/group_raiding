from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import app
from app.api.openapi import serialize_openapi


def test_health_returns_typed_deterministic_payload() -> None:
    response = TestClient(app).get("/api/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": "v1"}


def test_openapi_exposes_health_response_contract() -> None:
    schema = app.openapi()

    assert schema["paths"]["/api/healthz"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/HealthResponse"
    assert schema["components"]["schemas"]["HealthResponse"]["properties"]["api_version"]["type"] == "string"


def test_checked_in_openapi_matches_application_schema() -> None:
    contract = Path(__file__).resolve().parents[4] / "apps/web/src/lib/api/generated/openapi.json"

    assert contract.read_text() == serialize_openapi(app)


def test_health_operation_id_is_stable() -> None:
    assert app.openapi()["paths"]["/api/healthz"]["get"]["operationId"] == "getHealth"
