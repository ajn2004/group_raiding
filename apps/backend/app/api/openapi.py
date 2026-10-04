"""Deterministic serialization for the checked-in OpenAPI contract."""

import json

from fastapi import FastAPI


def serialize_openapi(app: FastAPI) -> str:
    """Return the canonical, checked-in representation of an app's schema."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
