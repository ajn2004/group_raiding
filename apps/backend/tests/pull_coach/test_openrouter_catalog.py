from decimal import Decimal

import pytest

from app.pull_coach.coaching.openrouter_catalog import (
    CatalogUnavailable, OpenRouterCatalog, estimate_cost, normalize_catalog,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Transport:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, 0

    def get(self, url, *, timeout):
        self.calls += 1
        if self.error:
            raise self.error
        return Response(self.payload)


def test_normalization_preserves_decimal_prices_and_optional_values():
    models = normalize_catalog({"data": [{"id": "vendor/model", "name": "Model", "context_length": 123,
        "pricing": {"prompt": "0.00000015", "completion": "0.00000060"},
        "supported_parameters": ["response_format", "structured_outputs"]}, {"id": "vendor/free"}]})
    model = models[0]
    assert model.id == "vendor/model" and model.context_length == 123
    assert model.pricing.input_dollars_per_million_tokens == "0.15000000"
    assert model.pricing.raw_output_price == "0.00000060"
    assert model.supports_response_format is True
    assert model.supports_structured_outputs is True
    assert models[1].pricing.input_price_per_token is None
    assert models[1].supports_response_format is None
    assert models[1].supports_structured_outputs is None


def test_response_format_is_not_misrepresented_as_json_schema_support():
    model = normalize_catalog({"data": [{"id": "vendor/model",
        "supported_parameters": ["response_format"]}]})[0]
    assert model.supports_response_format is True
    assert model.supports_structured_outputs is False
    assert not hasattr(model, "supports_structured_output")


def test_cache_hit_and_expiry():
    now = [0]
    transport = Transport({"data": [{"id": "a"}]})
    client = OpenRouterCatalog(transport, ttl_seconds=5, clock=lambda: now[0])
    client.list_models()
    client.list_models()
    assert transport.calls == 1
    now[0] = 5
    client.list_models()
    assert transport.calls == 2


def test_provider_failure_is_typed_and_not_cached():
    transport = Transport(error=OSError("offline"))
    client = OpenRouterCatalog(transport)
    with pytest.raises(CatalogUnavailable):
        client.list_models()
    assert transport.calls == 1


def test_cost_estimate_uses_exact_provider_decimal_prices():
    model = normalize_catalog({"data": [{"id": "a", "pricing": {
        "prompt": "0.00000015", "completion": "0.00000060"}}]})[0]
    assert estimate_cost(1_000_000, 500_000, model.pricing) == Decimal("0.45")
    with pytest.raises(ValueError):
        estimate_cost(-1, 0, model.pricing)


@pytest.mark.parametrize("missing_price", ["input_price_per_token", "output_price_per_token"])
def test_cost_estimate_returns_none_when_a_price_is_unknown(missing_price):
    from dataclasses import replace

    model = normalize_catalog({"data": [{"id": "a", "pricing": {
        "prompt": "0", "completion": "0"}}]})[0]
    pricing = replace(model.pricing, **{missing_price: None})
    assert estimate_cost(100, 100, pricing) is None


def test_cost_estimate_preserves_genuine_zero_prices():
    model = normalize_catalog({"data": [{"id": "a", "pricing": {
        "prompt": "0", "completion": "0"}}]})[0]
    assert estimate_cost(100, 100, model.pricing) == Decimal("0")
