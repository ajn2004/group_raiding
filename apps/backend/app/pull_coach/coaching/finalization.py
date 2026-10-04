"""Runtime handoff from validated inference into gated, auditable persistence."""

from typing import Any

from app.pull_coach.coaching.insights import InsightGateConfig, generate_and_gate, serialize_pipeline


def finalize_coaching_response(*, inference_result: Any, context: dict[str, Any],
                               gate_config: InsightGateConfig, session: Any, sessions: Any) -> dict[str, Any]:
    """Gate validated recommendations and complete their coaching session."""
    surfaced_response, pipeline = generate_and_gate(inference_result.response, context, gate_config)
    sessions.complete(
        session,
        structured_response=surfaced_response,
        raw_response=inference_result.raw_response,
        provider_request_id=inference_result.provider_request_id,
        provider_response_id=inference_result.provider_response_id,
        actual_model=inference_result.actual_model,
        usage=inference_result.usage,
        insight_pipeline=serialize_pipeline(pipeline),
    )
    return surfaced_response
