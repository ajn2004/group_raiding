from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.models.pull_coach import CoachingProfile, CoachingProfileRevision, CoachingSession, CoachingSessionMessage
from app.db.models.wipefest import WipefestFightSnapshot
from app.pull_coach.persistence.coaching_sessions import CoachingSessionRepository
from app.pull_coach.coaching.finalization import finalize_coaching_response
from app.pull_coach.coaching.insights import InsightGateConfig


@pytest.fixture
def seeded_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(CoachingProfile(purpose="raid_coach"))
        profile = CoachingProfileRevision(profile_purpose="raid_coach", revision=1,
            provider="openrouter", model_slug="vendor/model-v1", system_prompt="system v1",
            user_prompt_template="user v1", output_schema_version="selection-v1", provider_options={})
        snapshot = WipefestFightSnapshot(provider="wipefest", report_code="R1", fight_id="F1",
            group_id="G1", request_url="https://example.test", request_params={},
            fetched_at=datetime.now(timezone.utc), payload={"immutable": True}, fingerprint="a" * 64)
        db.add_all([profile, snapshot])
        db.flush()
        yield db, CoachingSessionRepository(db), snapshot.id, profile.id


def test_success_persists_request_provenance_raw_response_usage_and_ordered_turns(seeded_session):
    db, repo, snapshot_id, profile_id = seeded_session
    context = {"findings": [{"id": "f1"}], "fight_id": "F1"}
    run = repo.start(snapshot_id=snapshot_id, encounter_id="boss-1",
        audience="raid", context_schema_version="context-v3", request_context=context,
        profile_revision_id=profile_id,
        messages=({"role": "system", "content": "frozen system prompt"},
                  {"role": "user", "content": "exact request context"}))
    repo.complete(run, structured_response={"selected": ["candidate-1"]},
        raw_response={"choices": [{"text": "raw"}]}, actual_model="vendor/model-v1",
        provider_request_id="req-1", provider_response_id="resp-1", usage={"prompt_tokens": 10, "completion_tokens": 2},
        cost={"usd": 0.001}, assistant_content='{"selected":["candidate-1"]}')
    assert run.status == "completed" and run.snapshot_id == snapshot_id
    assert run.profile_revision_id == profile_id and run.request_context == context
    assert run.provider_response_id == "resp-1" and run.usage["prompt_tokens"] == 10
    assert [m.sequence for m in db.scalars(select(CoachingSessionMessage).where(
        CoachingSessionMessage.session_id == run.id).order_by(CoachingSessionMessage.sequence))] == [0, 1, 2]
    assert run.structured_response == {"selected": ["candidate-1"]}
    assert run.raw_response == {"choices": [{"text": "raw"}]}


@pytest.mark.parametrize("status", ["invalid_output", "failed"])
def test_unsuccessful_runs_are_inspectable_without_fabricated_response(seeded_session, status):
    _, repo, snapshot_id, profile_id = seeded_session
    run = repo.start(snapshot_id=snapshot_id, encounter_id="boss-1",
        audience="raid", context_schema_version="context-v1", request_context={},
        profile_revision_id=profile_id)
    repo.fail(run, status=status, error={"type": "invalid-json" if status == "invalid_output" else "timeout"},
              raw_response="provider body", provider_request_id="req-1", provider_response_id="resp-1",
              actual_model="vendor/actual", usage={"tokens": 12}, cost={"usd": 0.002})
    assert run.status == status and run.structured_response is None
    assert run.error and run.raw_response == "provider body"
    assert (run.provider_request_id, run.provider_response_id, run.actual_model) == ("req-1", "resp-1", "vendor/actual")
    assert run.usage == {"tokens": 12} and run.cost == {"usd": 0.002}


def test_player_session_is_scoped_and_raid_requires_no_target(seeded_session):
    _, repo, snapshot_id, profile_id = seeded_session
    run = repo.start(snapshot_id=snapshot_id, encounter_id="boss-1",
        audience="player", target_player_id="actor-7", target_player_name="Player",
        context_schema_version="context-v1", request_context={"actor": "actor-7"},
        profile_revision_id=profile_id)
    assert run.audience == "player" and run.target_player_id == "actor-7"
    with pytest.raises(ValueError, match="target_player_id"):
        repo.start(snapshot_id=snapshot_id, encounter_id="boss-1",
            audience="player", context_schema_version="context-v1", request_context={},
            profile_revision_id=profile_id)


def test_append_after_single_message_uses_next_sequence(seeded_session):
    _, repo, snapshot_id, profile_id = seeded_session
    run = repo.start(snapshot_id=snapshot_id, encounter_id="boss-1", audience="raid",
        context_schema_version="context-v1", request_context={}, profile_revision_id=profile_id,
        messages=({"role": "user", "content": "first"},))
    message = repo.append_message(run, role="assistant", content="second")
    assert message.sequence == 1


def test_old_session_remains_pinned_to_its_profile_revision(seeded_session):
    db, repo, snapshot_id, profile_id = seeded_session
    run = repo.start(snapshot_id=snapshot_id, encounter_id="boss-1", audience="raid",
        context_schema_version="context-v1", request_context={}, profile_revision_id=profile_id)
    profile = db.get(CoachingProfile, "raid_coach")
    profile.active_revision_id = profile_id
    revision2 = CoachingProfileRevision(profile_purpose="raid_coach", revision=2,
        provider="another-provider", model_slug="vendor/model-v2", system_prompt="system v2",
        user_prompt_template="user v2", output_schema_version="selection-v2", provider_options={})
    db.add(revision2)
    db.flush()
    profile.active_revision_id = revision2.id
    db.flush()
    db.expire_all()
    reloaded = db.get(CoachingSession, run.id)
    old_revision = db.get(CoachingProfileRevision, profile_id)
    assert reloaded.profile_revision_id == profile_id
    assert (reloaded.provider, reloaded.requested_model) == ("openrouter", "vendor/model-v1")
    assert old_revision.system_prompt == "system v1" and old_revision.model_slug == "vendor/model-v1"


def test_start_rejects_missing_profile_revision(seeded_session):
    _, repo, snapshot_id, _ = seeded_session
    with pytest.raises(LookupError, match="profile revision"):
        repo.start(snapshot_id=snapshot_id, encounter_id="boss-1", audience="raid",
            context_schema_version="context-v1", request_context={}, profile_revision_id=999)


def test_finalization_persists_rejected_candidate_but_does_not_surface_it(seeded_session):
    db, repo, snapshot_id, profile_id = seeded_session
    context = {"insights": [{"identity": {"group": "g", "id": "one"}}]}
    run = repo.start(snapshot_id=snapshot_id, encounter_id="boss-1", audience="raid",
        context_schema_version="context-v1", request_context=context, profile_revision_id=profile_id)
    response = {"recommendations": [{"scope": "raid", "text": "Unaccepted advice",
        "source_insight_keys": ["g:one"], "kind": "observation", "confidence": 0.1}],
        "candidate_source_insight_keys": []}
    inference = SimpleNamespace(response=response, raw_response={"provider": "raw"},
        provider_request_id="request-1", provider_response_id="response-1",
        actual_model="vendor/model-actual", usage={"tokens": 3})

    surfaced = finalize_coaching_response(inference_result=inference, context=context,
        gate_config=InsightGateConfig(profile="threshold", threshold=0.5), session=run, sessions=repo)
    db.flush()
    inspected = repo.inspect(run.id)
    assert len(run.candidate_insights) == 1
    assert run.insight_gate_decisions[0]["surface"] is False
    assert run.structured_response["recommendations"] == []
    assert run.displayed_insight_ids == []
    assert surfaced["recommendations"] == []
    assert inspected["generator"] == {"profile_revision_id": profile_id, "provider": "openrouter",
        "requested_model": "vendor/model-v1", "actual_model": "vendor/model-actual"}
    assert inspected["gate"] == {"evaluator": "threshold", "version": "1"}
