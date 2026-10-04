from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.models.pull_coach import CoachingProfile, CoachingProfileRevision, CoachingSession
from app.pull_coach.persistence.coaching_profiles import CoachingProfileRepository
from app.pull_coach.sources import WipefestCoachingSource
from app.web_requests.wipefest import FightSnapshot


def test_source_reuses_exact_completed_run_and_gates_response(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    with session_factory() as session:
        profile = CoachingProfile(purpose="raid_coach")
        session.add(profile)
        session.flush()
        revision = CoachingProfileRevision(profile_purpose="raid_coach", revision=1,
            provider="openrouter", model_slug="model-a", system_prompt="system-a",
            user_prompt_template="user-a", output_schema_version="v1", provider_options={})
        session.add(revision)
        session.flush()
        profile.active_revision_id = revision.id
        session.commit()

    payload = {"info": {"boss": 1, "name": "Boss", "start_time": 1, "end_time": 2},
        "raid": {"players": []}, "insights": []}
    snapshot = FightSnapshot("R1", "1", "1", "https://example.test", {},
        datetime.now(timezone.utc), payload, "f" * 64)

    class Provider:
        def fetch_fight(self, *_):
            return snapshot

    class Inference:
        calls = 0

        def infer(self, context, revision):
            self.calls += 1
            return SimpleNamespace(response={"recommendations": [{"scope": "raid", "text": "advice",
                "source_insight_keys": [], "kind": "observation", "confidence": 0.1}],
                "candidate_source_insight_keys": []}, raw_response={}, provider_request_id=None,
                provider_response_id=None, actual_model=revision.model_slug, usage={})

    monkeypatch.setenv("PULL_COACH_INSIGHT_GATE_PROFILE", "threshold")
    monkeypatch.setenv("PULL_COACH_INSIGHT_GATE_THRESHOLD", "0.5")
    inference = Inference()
    source = WipefestCoachingSource(Provider(), session_factory, inference)
    fight = {"id": "1", "encounterID": "1", "name": "Boss"}

    first = source.coach("https://www.warcraftlogs.com/reports/R1", fight)
    again = source.coach("https://www.warcraftlogs.com/reports/R1", fight)
    assert inference.calls == 1
    assert again.session_id == first.session_id
    assert first.coaching["recommendations"] == []

    with session_factory() as session:
        profiles = CoachingProfileRepository(session)
        profiles.create_revision("raid_coach", provider="openrouter", model_slug="model-b",
            system_prompt="system-b", user_prompt_template="user-b", output_schema_version="v1",
            activate=True)
        session.commit()
    changed = source.coach("https://www.warcraftlogs.com/reports/R1", fight)
    assert inference.calls == 2
    assert changed.session_id != first.session_id
    with session_factory() as session:
        rows = list(session.scalars(select(CoachingSession).order_by(CoachingSession.id)))
        assert rows[0].insight_gate_decisions[0]["surface"] is False
