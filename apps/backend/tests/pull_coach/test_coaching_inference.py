import json
from types import SimpleNamespace

import pytest

from app.pull_coach.coaching.inference import (
    InvalidCoachingResponse, OpenRouterConfig, OpenRouterInferenceProvider, ProviderRequestError,
    RESPONSE_SCHEMA, response_schema_for_context,
    UnsupportedOutputSchema,
)


CONTEXT = {"insights": [{"identity": {"key": "mechanic:avoid", "group": "mechanic", "id": "avoid"}}],
           "roster": [{"playerId": 7, "name": "Player"}]}


def assert_strict_object_schema(schema):
    if schema.get("type") == "object":
        assert set(schema.get("required", [])) == set(schema.get("properties", {}))
    for value in schema.get("properties", {}).values():
        if isinstance(value, dict):
            assert_strict_object_schema(value)
    for value in schema.get("$defs", {}).values():
        if isinstance(value, dict):
            assert_strict_object_schema(value)


def test_openrouter_response_schema_is_strict_compatible():
    assert_strict_object_schema(RESPONSE_SCHEMA)


def test_context_schema_only_allows_canonical_citations_and_roster_players():
    context = {"insights": [{"identity": {"key": "1507:S"}}, {"identity": {"key": "1507:2"}}],
               "roster": [{"playerId": 7}, {"playerId": "8"}]}
    schema = response_schema_for_context(context)
    props = schema["$defs"]["recommendation"]["properties"]
    citation_enum = props["source_insight_keys"]["items"]["enum"]
    assert citation_enum == ["1507:2", "1507:S"]
    assert schema["properties"]["candidate_source_insight_keys"]["items"]["enum"] == citation_enum
    assert "title" not in citation_enum and "values.totalEvents" not in citation_enum
    assert props["player_id"]["enum"] == ["7", "8", None]
    assert_strict_object_schema(schema)


def revision(model="vendor/model-a", system="system", template="Context: {context}", **overrides):
    values = dict(provider="openrouter", model_slug=model, system_prompt=system,
        user_prompt_template=template, temperature=0.2, max_output_tokens=100, provider_options={},
        output_schema_version="coaching-selection-v1")
    values.update(overrides)
    return SimpleNamespace(**values)


def response(body):
    return {"recommendations": [{"scope": "raid", "text": "Handle mechanic", "source_insight_keys": ["mechanic:avoid"],
        "kind": "inference", "player_id": None}], "candidate_source_insight_keys": []} if body is None else body


class FakeResponse:
    headers = {"x-request-id": "req-1"}

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def test_profile_revision_drives_model_and_prompts_and_returns_provider_metadata():
    transport = FakeTransport({"id": "resp-1", "model": "actual/model", "usage": {"total_tokens": 12},
        "choices": [{"message": {"content": json.dumps(response(None))}}]})
    provider = OpenRouterInferenceProvider(OpenRouterConfig("key"), transport)
    result = provider.infer(CONTEXT, revision("vendor/model-b", "system b", "User b {context}"))
    sent = transport.calls[0][1]["json"]
    assert sent["model"] == "vendor/model-b"
    user_message = sent["messages"][1]["content"]
    assert sent["messages"][0] == {"role": "system", "content": "system b"}
    assert user_message.startswith("User b {context}\n")
    assert "exact insights[].identity.key values" in user_message
    assert "Do not cite JSON field names" in user_message
    assert json.dumps(CONTEXT, sort_keys=True) in user_message
    assert sent["response_format"]["type"] == "json_schema"
    assert (result.provider_request_id, result.provider_response_id, result.usage, result.actual_model) == (
        "req-1", "resp-1", {"total_tokens": 12}, "actual/model")


@pytest.mark.parametrize("change", [
    lambda value: value["recommendations"][0].update(source_insight_keys=["unknown"]),
    lambda value: value["recommendations"][0].update(text=" "),
    lambda value: value["recommendations"][0].update(player_id="999"),
])
def test_invalid_recommendations_are_rejected(change):
    body = response(None)
    change(body)
    provider = OpenRouterInferenceProvider(OpenRouterConfig("key"), FakeTransport(
        {"choices": [{"message": {"content": json.dumps(body)}}]}))
    with pytest.raises(InvalidCoachingResponse):
        provider.infer(CONTEXT, revision())


def test_malformed_json_and_response_limit_fail_closed():
    malformed = OpenRouterInferenceProvider(OpenRouterConfig("key"), FakeTransport(
        {"choices": [{"message": {"content": "not json"}}]}))
    with pytest.raises(InvalidCoachingResponse):
        malformed.infer(CONTEXT, revision())
    too_many = response(None)
    too_many["recommendations"] *= 2
    limited = OpenRouterInferenceProvider(OpenRouterConfig("key", max_recommendations=1), FakeTransport(
        {"choices": [{"message": {"content": json.dumps(too_many)}}]}))
    with pytest.raises(InvalidCoachingResponse):
        limited.infer(CONTEXT, revision())


@pytest.mark.parametrize("raw", [[], None, "unexpected"])
def test_non_object_provider_json_fails_as_typed_invalid_output(raw):
    provider = OpenRouterInferenceProvider(OpenRouterConfig("key"), FakeTransport(raw))
    with pytest.raises(InvalidCoachingResponse) as caught:
        provider.infer(CONTEXT, revision())
    assert caught.value.raw_response is raw


def test_player_recommendation_requires_a_context_player():
    body = response(None)
    body["recommendations"][0].update(scope="player", player_id=None)
    provider = OpenRouterInferenceProvider(OpenRouterConfig("key"), FakeTransport(
        {"choices": [{"message": {"content": json.dumps(body)}}]}))
    with pytest.raises(InvalidCoachingResponse):
        provider.infer(CONTEXT, revision())


def test_seeded_style_prompt_always_includes_context_and_temperature_is_optional():
    transport = FakeTransport({"choices": [{"message": {"content": json.dumps(response(None))}}]})
    provider = OpenRouterInferenceProvider(OpenRouterConfig("key"), transport)
    profile = revision(template="Use supplied coaching input.", temperature=None)
    provider.infer(CONTEXT, profile)
    body = transport.calls[0][1]["json"]
    assert json.dumps(CONTEXT, sort_keys=True) in body["messages"][1]["content"]
    assert "temperature" not in body


def test_output_schema_version_selects_supported_schema_and_rejects_unknown():
    transport = FakeTransport({"choices": [{"message": {"content": json.dumps(response(None))}}]})
    OpenRouterInferenceProvider(OpenRouterConfig("key"), transport).infer(
        CONTEXT, revision(output_schema_version="player-coaching-v1"))
    assert transport.calls[0][1]["json"]["response_format"]["json_schema"]["schema"]
    with pytest.raises(UnsupportedOutputSchema):
        OpenRouterInferenceProvider(OpenRouterConfig("key"), FakeTransport({})).infer(
            CONTEXT, revision(output_schema_version="candidate-insight-gate-v1"))


def test_provider_options_cannot_override_profile_request_fields():
    provider = OpenRouterInferenceProvider(OpenRouterConfig("key"), FakeTransport({}))
    for reserved in ("temperature", "max_tokens", "stream"):
        with pytest.raises(ProviderRequestError, match="reserved request field"):
            provider.infer(CONTEXT, revision(provider_options={reserved: True}))


def test_invalid_output_preserves_provider_metadata():
    raw = {"id": "resp-invalid", "model": "actual/model", "usage": {"total_tokens": 17},
        "choices": [{"message": {"content": json.dumps({"recommendations": [{
            "scope": "raid", "text": "Bad", "source_insight_keys": ["unknown"],
            "kind": "inference", "player_id": None}]})}}]}
    provider = OpenRouterInferenceProvider(OpenRouterConfig("key"), FakeTransport(raw))
    with pytest.raises(InvalidCoachingResponse) as caught:
        provider.infer(CONTEXT, revision())
    error = caught.value
    assert (error.raw_response, error.provider_request_id, error.provider_response_id,
            error.actual_model, error.usage) == (raw, "req-1", "resp-invalid", "actual/model", {"total_tokens": 17})


def test_transport_retries_twice_then_succeeds():
    class FlakyTransport(FakeTransport):
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if len(self.calls) < 3:
                raise OSError("temporary")
            return FakeResponse({"choices": [{"message": {"content": json.dumps(response(None))}}]})

    transport = FlakyTransport({})
    result = OpenRouterInferenceProvider(OpenRouterConfig("key", retries=2, retry_backoff_seconds=0),
                                         transport).infer(CONTEXT, revision())
    assert len(transport.calls) == 3
    assert result.response["recommendations"]
