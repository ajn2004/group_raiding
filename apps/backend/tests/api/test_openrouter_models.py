from fastapi.testclient import TestClient

from app.api.main import app
from app.api.dependencies import get_db_session
from app.api.routes import router
from app.pull_coach.coaching.openrouter_catalog import CatalogUnavailable, normalize_catalog


def _override_catalog_capability():
    route = next(route for route in router.routes
                 if getattr(route, "operation_id", None) == "listOpenRouterModels")
    dependency = route.dependant.dependencies[0].call
    app.dependency_overrides[dependency] = lambda: None
    return dependency


def test_openrouter_models_requires_authorization():
    def db_override():
        yield object()
    app.dependency_overrides[get_db_session] = db_override
    try:
        response = TestClient(app).get("/api/coaching/openrouter/models")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
    assert response.status_code == 401


def test_openrouter_models_available_response(monkeypatch):
    dependency = _override_catalog_capability()
    monkeypatch.setattr("app.api.routes.catalog_service", lambda: type("Service", (), {
        "list_models": lambda self: normalize_catalog({"data": [{"id": "vendor/model",
            "supported_parameters": ["response_format", "structured_outputs"],
            "pricing": {"prompt": "0.000001"}}]})
    })())
    try:
        response = TestClient(app).get("/api/coaching/openrouter/models")
    finally:
        app.dependency_overrides.pop(dependency, None)
    assert response.status_code == 200
    assert response.json()["status"] == "available"
    assert response.json()["models"][0]["supports_response_format"] is True
    assert response.json()["models"][0]["supports_structured_outputs"] is True


def test_openrouter_models_degraded_response(monkeypatch):
    dependency = _override_catalog_capability()
    def unavailable():
        raise CatalogUnavailable
    monkeypatch.setattr("app.api.routes.catalog_service", lambda: type("Service", (), {
        "list_models": lambda self: unavailable()
    })())
    try:
        response = TestClient(app).get("/api/coaching/openrouter/models")
    finally:
        app.dependency_overrides.pop(dependency, None)
    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "models": [], "error": "catalog_unavailable"}
