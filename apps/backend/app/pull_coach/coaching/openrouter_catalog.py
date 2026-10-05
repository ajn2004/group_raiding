"""OpenRouter model catalog ingestion and provider-independent cost estimates."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
import time
from typing import Any, Protocol

import requests


class CatalogTransport(Protocol):
    def get(self, url: str, *, timeout: float) -> Any: ...


class RequestsCatalogTransport:
    def get(self, url: str, *, timeout: float) -> Any:
        return requests.get(url, timeout=timeout)


class CatalogUnavailable(Exception):
    """Provider catalog could not be fetched or parsed."""


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class ModelPricing:
    input_price_per_token: str | None
    output_price_per_token: str | None
    input_dollars_per_million_tokens: str | None
    output_dollars_per_million_tokens: str | None
    raw_input_price: str | None
    raw_output_price: str | None
    price_unit: str = "USD per token"


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str
    context_length: int | None
    pricing: ModelPricing
    supports_response_format: bool | None
    supports_structured_outputs: bool | None


def normalize_catalog(payload: Any) -> tuple[CatalogModel, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise CatalogUnavailable("OpenRouter catalog response is malformed")
    models = []
    for item in payload["data"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        raw = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        prompt, completion = _decimal(raw.get("prompt")), _decimal(raw.get("completion"))
        def text(value):
            return str(value) if value is not None else None
        def million(value):
            return format(value * 1_000_000, "f") if value is not None else None
        response_format = item.get("supports_response_format")
        parameters = item.get("supported_parameters")
        if not isinstance(response_format, bool):
            response_format = "response_format" in parameters if isinstance(parameters, list) else None
        structured_outputs = (
            "structured_outputs" in parameters if isinstance(parameters, list) else None
        )
        length = item.get("context_length")
        models.append(CatalogModel(item["id"], str(item.get("name") or item["id"]),
            length if isinstance(length, int) and not isinstance(length, bool) else None,
            ModelPricing(text(prompt), text(completion), million(prompt), million(completion),
                          text(raw.get("prompt")), text(raw.get("completion"))), response_format,
            structured_outputs))
    return tuple(models)


def estimate_cost(prompt_tokens: int, completion_tokens: int, pricing: ModelPricing) -> Decimal | None:
    """Estimate USD cost exactly, or return None when either price is unknown."""
    if prompt_tokens < 0 or completion_tokens < 0:
        raise ValueError("token counts must not be negative")
    prompt = _decimal(pricing.input_price_per_token)
    completion = _decimal(pricing.output_price_per_token)
    if prompt is None or completion is None:
        return None
    return prompt * prompt_tokens + completion * completion_tokens


class OpenRouterCatalog:
    def __init__(self, transport: CatalogTransport | None = None, *, ttl_seconds: float = 300,
                 clock=time.monotonic, base_url: str = "https://openrouter.ai/api/v1"):
        self.transport = transport or RequestsCatalogTransport()
        self.ttl_seconds = max(0, ttl_seconds)
        self.clock = clock
        self.base_url = base_url.rstrip("/")
        self._cached: tuple[CatalogModel, ...] | None = None
        self._expires = 0.0

    def list_models(self) -> tuple[CatalogModel, ...]:
        now = self.clock()
        if self._cached is not None and now < self._expires:
            return self._cached
        try:
            response = self.transport.get(self.base_url + "/models", timeout=10)
            response.raise_for_status()
            result = normalize_catalog(response.json())
        except Exception as exc:
            raise CatalogUnavailable("OpenRouter model catalog is unavailable") from exc
        self._cached, self._expires = result, now + self.ttl_seconds
        return result


def catalog_service() -> OpenRouterCatalog:
    # This endpoint is public; credentials are neither needed nor exposed.
    return _default_catalog


_default_catalog = OpenRouterCatalog(ttl_seconds=float(os.getenv("OPENROUTER_CATALOG_TTL_SECONDS", "300")))
