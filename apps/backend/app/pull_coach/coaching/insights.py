"""Candidate insight generation/surfacing seam; evaluators cannot rewrite claims."""
from dataclasses import asdict, dataclass, field
import math
from numbers import Real
import os
from typing import Any, Protocol


@dataclass(frozen=True)
class CandidateInsight:
    id: str
    audience: str
    text: str
    source_insight_keys: tuple[str, ...]
    kind: str
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InsightGateDecision:
    candidate_id: str
    surface: bool
    score: float | None
    reason_code: str | None
    evaluator: str
    evaluator_version: str


class InsightGate(Protocol):
    evaluator: str
    evaluator_version: str

    def evaluate(self, candidate: CandidateInsight, context: dict[str, Any]) -> InsightGateDecision: ...


@dataclass(frozen=True)
class PassThroughGate:
    evaluator: str = "pass-through"
    evaluator_version: str = "1"

    def evaluate(self, candidate: CandidateInsight, context: dict[str, Any]) -> InsightGateDecision:
        return InsightGateDecision(candidate.id, True, 1.0, "accepted", self.evaluator, self.evaluator_version)


@dataclass(frozen=True)
class ThresholdGate:
    threshold: float = 0.5
    evaluator: str = "threshold"
    evaluator_version: str = "1"

    def __post_init__(self):
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")

    def evaluate(self, candidate: CandidateInsight, context: dict[str, Any]) -> InsightGateDecision:
        score = candidate.confidence
        surface = score is not None and score >= self.threshold
        return InsightGateDecision(candidate.id, surface, score,
            "accepted" if surface else "below_threshold" if score is not None else "missing_score",
            self.evaluator, self.evaluator_version)


@dataclass(frozen=True)
class InsightPipelineResult:
    candidates: tuple[CandidateInsight, ...]
    decisions: tuple[InsightGateDecision, ...]
    displayed: tuple[CandidateInsight, ...]
    generator: str
    gate: str
    gate_version: str
    failure_policy: str


def gate_candidates(candidates, context, gate: InsightGate, *, failure_policy="fail_closed") -> InsightPipelineResult:
    """Evaluate each candidate independently; fallback is explicit and provenance-tagged."""
    if failure_policy not in {"fail_closed", "pass_through"}:
        raise ValueError("failure_policy must be fail_closed or pass_through")
    decisions = []
    failed = False
    for candidate in candidates:
        try:
            decision = gate.evaluate(candidate, context)
            if (not isinstance(decision, InsightGateDecision) or decision.candidate_id != candidate.id
                    or not isinstance(decision.surface, bool)
                    or (decision.score is not None and (
                        not isinstance(decision.score, Real) or isinstance(decision.score, bool)
                        or not math.isfinite(decision.score) or not 0 <= decision.score <= 1))
                    or not isinstance(decision.evaluator, str) or not decision.evaluator.strip()
                    or not isinstance(decision.evaluator_version, str) or not decision.evaluator_version.strip()):
                raise ValueError("gate returned a malformed or mismatched decision")
        except Exception:
            failed = True
            decision = InsightGateDecision(candidate.id, failure_policy == "pass_through", None,
                "gate_error_pass_through" if failure_policy == "pass_through" else "gate_error_fail_closed",
                getattr(gate, "evaluator", type(gate).__name__), getattr(gate, "evaluator_version", "unknown"))
        decisions.append(decision)
    return InsightPipelineResult(tuple(candidates), tuple(decisions),
        tuple(c for c, d in zip(candidates, decisions) if d.surface), "llm",
        getattr(gate, "evaluator", type(gate).__name__), getattr(gate, "evaluator_version", "unknown"),
        failure_policy + ("_used" if failed else ""))


def candidate_insights(response: dict[str, Any], context: dict[str, Any]) -> tuple[CandidateInsight, ...]:
    """Convert already-validated provider recommendations into immutable candidates."""
    results = []
    for index, item in enumerate(response["recommendations"]):
        player_id = item.get("player_id")
        results.append(CandidateInsight(str(item.get("id") or f"candidate-{index + 1}"),
            "player" if player_id is not None else item.get("scope", "raid"), item["text"],
            tuple(item["source_insight_keys"]), item["kind"], item.get("confidence"), {"player_id": player_id}))
    return tuple(results)


def serialize_pipeline(result: InsightPipelineResult) -> dict[str, Any]:
    return {"generator": result.generator, "gate": result.gate, "gate_version": result.gate_version,
            "failure_policy": result.failure_policy, "candidates": [asdict(c) for c in result.candidates],
            "decisions": [asdict(d) for d in result.decisions],
            "displayed_ids": [c.id for c in result.displayed]}


def surface_response(response: dict[str, Any], result: InsightPipelineResult) -> dict[str, Any]:
    """Return the final response using the gate allowlist without letting the gate alter claims."""
    displayed = {candidate.id for candidate in result.displayed}
    recommendations = [item for item, candidate in zip(response["recommendations"], result.candidates)
                       if candidate.id in displayed]
    return {**response, "recommendations": recommendations}


def generate_and_gate(response: dict[str, Any], context: dict[str, Any], config: "InsightGateConfig"):
    """The runtime handoff after generator validation and before any response rendering."""
    candidates = candidate_insights(response, context)
    result = gate_candidates(candidates, context, config.build(), failure_policy=config.failure_policy)
    return surface_response(response, result), result


def configured_gate(profile="pass-through", threshold=0.5):
    """Factory seam for profile configuration; future System-One/Laya adapter belongs here."""
    if profile == "pass-through":
        return PassThroughGate()
    if profile == "threshold":
        return ThresholdGate(threshold)
    raise ValueError(f"unsupported insight gate profile: {profile}")


@dataclass(frozen=True)
class InsightGateConfig:
    profile: str = "pass-through"
    threshold: float = 0.5
    failure_policy: str = "fail_closed"

    def __post_init__(self):
        if self.failure_policy not in {"fail_closed", "pass_through"}:
            raise ValueError("failure_policy must be fail_closed or pass_through")

    @classmethod
    def from_env(cls):
        return cls(os.getenv("PULL_COACH_INSIGHT_GATE_PROFILE", "pass-through"),
                   float(os.getenv("PULL_COACH_INSIGHT_GATE_THRESHOLD", "0.5")),
                   os.getenv("PULL_COACH_INSIGHT_GATE_FAILURE_POLICY", "fail_closed"))

    def build(self) -> InsightGate:
        return configured_gate(self.profile, self.threshold)
