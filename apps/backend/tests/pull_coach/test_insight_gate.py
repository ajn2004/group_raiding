import pytest

from app.pull_coach.coaching.insights import (
    CandidateInsight, PassThroughGate, ThresholdGate, candidate_insights,
    gate_candidates, serialize_pipeline, surface_response,
    InsightGateDecision,
)


def test_candidates_are_evaluated_independently_and_only_accepted_are_displayed():
    context = {"insights": [{"identity": {"group": "g", "id": "one"}}]}
    candidates = candidate_insights({"recommendations": [
        {"scope": "raid", "text": "Claim one", "source_insight_keys": ["g:one"], "kind": "observation", "confidence": .9},
        {"scope": "raid", "text": "Claim two", "source_insight_keys": ["g:one"], "kind": "inference", "confidence": .2},
    ]}, context)
    result = gate_candidates(candidates, context, ThresholdGate(.5))
    assert [d.surface for d in result.decisions] == [True, False]
    assert result.displayed == candidates[:1]
    assert result.displayed[0].source_insight_keys == ("g:one",)
    assert len(serialize_pipeline(result)["candidates"]) == 2
    response = {"recommendations": [{"text": candidate.text} for candidate in candidates]}
    assert surface_response(response, result)["recommendations"] == [{"text": "Claim one"}]


@pytest.mark.parametrize(("policy", "expected"), [("fail_closed", False), ("pass_through", True)])
def test_gate_failure_obeys_configured_policy(policy, expected):
    class BrokenGate:
        evaluator, evaluator_version = "broken", "9"
        def evaluate(self, candidate, context):
            raise RuntimeError("offline")

    candidate = CandidateInsight("one", "raid", "Claim", ("g:one",), "observation")
    result = gate_candidates((candidate,), {}, BrokenGate(), failure_policy=policy)
    assert result.decisions[0].surface is expected
    assert result.decisions[0].reason_code == f"gate_error_{policy}"
    assert result.failure_policy == policy + "_used"


def test_pass_through_gate_is_deterministic():
    candidate = CandidateInsight("one", "raid", "Claim", ("g:one",), "observation")
    assert gate_candidates((candidate,), {}, PassThroughGate()).displayed == (candidate,)


def test_malformed_gate_decision_follows_failure_policy():
    class MalformedGate:
        evaluator, evaluator_version = "malformed", "1"
        def evaluate(self, candidate, context):
            return InsightGateDecision(candidate.id, "yes", 14.7, None, "malformed", "1")

    candidate = CandidateInsight("one", "raid", "Claim", ("g:one",), "observation")
    result = gate_candidates((candidate,), {}, MalformedGate(), failure_policy="fail_closed")
    assert result.decisions[0].surface is False
    assert result.decisions[0].reason_code == "gate_error_fail_closed"
    assert result.failure_policy == "fail_closed_used"
