"""Provider-independent structured coaching inference and OpenRouter adapter."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any, Protocol

import requests


class CoachingInferenceError(Exception):
    """Base class for errors safe to handle at the inference boundary."""


class ProviderRequestError(CoachingInferenceError):
    """Provider request failed after bounded retries."""


class InvalidCoachingResponse(CoachingInferenceError):
    """Provider output did not satisfy the structured response contract."""

    def __init__(self, message: str, *, raw_response: Any = None,
                 provider_request_id: str | None = None, provider_response_id: str | None = None,
                 actual_model: str | None = None, usage: dict[str, Any] | None = None):
        super().__init__(message)
        self.raw_response = raw_response
        self.provider_request_id = provider_request_id
        self.provider_response_id = provider_response_id
        self.actual_model = actual_model
        self.usage = usage


class UnsupportedOutputSchema(CoachingInferenceError):
    """The profile references a schema not implemented by this runtime."""


@dataclass(frozen=True)
class CoachingInferenceResult:
    response: dict[str, Any]
    provider: str
    requested_model: str
    actual_model: str | None
    provider_request_id: str | None
    provider_response_id: str | None
    usage: dict[str, Any] | None
    provider_metadata: dict[str, Any]
    raw_response: dict[str, Any]


class CoachingTransport(Protocol):
    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> Any: ...


class RequestsTransport:
    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> Any:
        return requests.post(url, headers=headers, json=json, timeout=timeout)


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: float = 30
    retries: int = 2
    retry_backoff_seconds: float = 0.25
    max_recommendations: int = 8
    structured_output: bool = True

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("OpenRouter API key must not be empty")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 0 and 120")
        if not 0 <= self.retries <= 3:
            raise ValueError("retries must be between 0 and 3")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        if self.max_recommendations < 0:
            raise ValueError("max_recommendations must not be negative")

    @classmethod
    def from_env(cls) -> "OpenRouterConfig":
        key = os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            raise ValueError("OPENROUTER_API_KEY is required")
        return cls(api_key=key, base_url=os.getenv("OPENROUTER_BASE_URL", cls.base_url))


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "recommendations": {"type": "array", "items": {"$ref": "#/$defs/recommendation"}},
        "candidate_source_insight_keys": {"type": "array", "items": {"type": "string"}},
    }, "required": ["recommendations"],
    "$defs": {"recommendation": {"type": "object", "additionalProperties": False,
        "properties": {"scope": {"type": "string", "enum": ["raid", "player"]},
            "text": {"type": "string"}, "source_insight_keys": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": "string", "enum": ["observation", "inference"]},
            "player_id": {"type": ["string", "null"]}},
        "required": ["scope", "text", "source_insight_keys", "kind", "player_id"]}},
}

OUTPUT_SCHEMAS = {
    "coaching-selection-v1": RESPONSE_SCHEMA,
    "player-coaching-v1": RESPONSE_SCHEMA,
}


def validate_coaching_response(value: Any, context: dict[str, Any], max_recommendations: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"recommendations", "candidate_source_insight_keys"}:
        raise InvalidCoachingResponse("response must be a coaching object")
    recommendations = value.get("recommendations")
    candidates = value.get("candidate_source_insight_keys", [])
    if not isinstance(recommendations, list) or not isinstance(candidates, list):
        raise InvalidCoachingResponse("recommendations and candidate_source_insight_keys must be arrays")
    if len(recommendations) > max_recommendations:
        raise InvalidCoachingResponse("recommendation limit exceeded")
    if any(not isinstance(key, str) for key in candidates):
        raise InvalidCoachingResponse("candidate insight keys must be strings")
    insights = context.get("insights") or []
    valid_keys = {f"{(i.get('identity') or {}).get('group')}:{(i.get('identity') or {}).get('id')}"
                  for i in insights if isinstance(i, dict)}
    players = [context.get("player")] if context.get("player") else context.get("roster", [])
    player_ids = {str(p.get("playerId")) for p in players if isinstance(p, dict) and p.get("playerId") is not None}
    normalized = []
    for item in recommendations:
        if not isinstance(item, dict) or set(item) != {"scope", "text", "source_insight_keys", "kind", "player_id"}:
            raise InvalidCoachingResponse("malformed recommendation")
        if item["scope"] not in {"raid", "player"} or item["kind"] not in {"observation", "inference"}:
            raise InvalidCoachingResponse("invalid recommendation scope or kind")
        if not isinstance(item["text"], str) or not item["text"].strip():
            raise InvalidCoachingResponse("recommendation text must not be empty")
        keys = item["source_insight_keys"]
        if not isinstance(keys, list) or not keys or any(k not in valid_keys for k in keys):
            raise InvalidCoachingResponse("recommendation cites unknown or missing source insights")
        player_id = item["player_id"]
        if player_id is not None and str(player_id) not in player_ids:
            raise InvalidCoachingResponse("recommendation references an unknown player")
        if item["scope"] == "player" and player_id is None:
            raise InvalidCoachingResponse("player recommendation must identify a player")
        normalized.append({**item, "text": item["text"].strip()})
    if any(key not in valid_keys for key in candidates):
        raise InvalidCoachingResponse("candidate insight references an unknown insight")
    return {"recommendations": normalized, "candidate_source_insight_keys": candidates}


class OpenRouterInferenceProvider:
    provider_name = "openrouter"

    def __init__(self, config: OpenRouterConfig, transport: CoachingTransport | None = None):
        self.config = config
        self.transport = transport or RequestsTransport()

    def infer(self, context: dict[str, Any], profile_revision: Any) -> CoachingInferenceResult:
        if getattr(profile_revision, "provider", None) != self.provider_name:
            raise ProviderRequestError("profile revision provider is not openrouter")
        schema = OUTPUT_SCHEMAS.get(getattr(profile_revision, "output_schema_version", None))
        if schema is None:
            raise UnsupportedOutputSchema("profile revision output schema is not supported")
        model = profile_revision.model_slug
        serialized = json.dumps(context, sort_keys=True, ensure_ascii=False, allow_nan=False)
        user_prompt = profile_revision.user_prompt_template + "\n\nCoaching context:\n" + serialized
        body: dict[str, Any] = {"model": model, "messages": [
            {"role": "system", "content": profile_revision.system_prompt},
            {"role": "user", "content": user_prompt}]}
        if profile_revision.temperature is not None:
            body["temperature"] = profile_revision.temperature
        if profile_revision.max_output_tokens is not None:
            body["max_tokens"] = profile_revision.max_output_tokens
        options = profile_revision.provider_options or {}
        if not isinstance(options, dict) or set(options) & {
            "model", "messages", "response_format", "temperature", "max_tokens", "stream"
        }:
            raise ProviderRequestError("profile provider_options contains a reserved request field")
        body.update(options)
        if self.config.structured_output:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "coaching_response", "strict": True, "schema": schema}}
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        raw = None
        for attempt in range(max(0, self.config.retries) + 1):
            try:
                result = self.transport.post(self.config.base_url.rstrip("/") + "/chat/completions",
                    headers=headers, json=body, timeout=self.config.timeout_seconds)
                result.raise_for_status()
                raw = result.json()
                break
            except Exception as exc:
                if attempt >= max(0, self.config.retries):
                    raise ProviderRequestError("OpenRouter request failed") from exc
                time.sleep(max(0, self.config.retry_backoff_seconds) * (2 ** attempt))
        try:
            content = raw["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            response = validate_coaching_response(json.loads(content), context, self.config.max_recommendations)
        except InvalidCoachingResponse as exc:
            raw_metadata = raw if isinstance(raw, dict) else {}
            raise InvalidCoachingResponse(str(exc), raw_response=raw,
                provider_request_id=result.headers.get("x-request-id"), provider_response_id=raw_metadata.get("id"),
                actual_model=raw_metadata.get("model"), usage=raw_metadata.get("usage")) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raw_metadata = raw if isinstance(raw, dict) else {}
            raise InvalidCoachingResponse("provider returned malformed structured output", raw_response=raw,
                provider_request_id=result.headers.get("x-request-id"), provider_response_id=raw_metadata.get("id"),
                actual_model=raw_metadata.get("model"), usage=raw_metadata.get("usage")) from exc
        return CoachingInferenceResult(response, self.provider_name, model, raw.get("model"),
            result.headers.get("x-request-id"), raw.get("id"), raw.get("usage"),
            {k: v for k, v in raw.items() if k not in {"choices", "usage"}}, raw)
