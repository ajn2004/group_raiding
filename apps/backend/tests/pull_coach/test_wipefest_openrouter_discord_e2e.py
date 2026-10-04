"""Fixture-backed vertical slice for Wipefest coaching (no WCL event ingestion)."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json as jsonlib
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.models.pull_coach import CoachingSession, CoachingSessionMessage
from app.db.models.wipefest import WipefestFightSnapshot
from app.pull_coach.coaching.inference import OpenRouterConfig, OpenRouterInferenceProvider
from app.pull_coach.orchestration import CoachingOrchestrator
from app.pull_coach.persistence.coaching_profiles import CoachingProfileRepository
from app.pull_coach.presentation import PullCoachPresenter
from app.pull_coach.service import PullCoachService
from app.pull_coach.sources import LazyLegacyWCLCoachingSource, WipefestCoachingSource
from app.web_requests.wipefest import FightSnapshot


FIXTURE = Path(__file__).parents[1] / "fixtures/wipefest/reference_fight.json"
REPORT = "j8wDLpCTaqhB7M1x"
FIGHT = {"id": "10", "encounterID": "1507", "name": "Imperial Vizier Zor'lok"}


class FixtureWipefest:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def fetch_fight(self, report, fight, group):
        self.calls.append((report, fight, group))
        canonical = jsonlib.dumps(self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return FightSnapshot(report, fight, group, f"https://api.wipefest.gg/report/{report}/fight/{fight}",
            {"markupFormat": "Markup", "group": group, "insightsOnly": "false"},
            datetime.now(timezone.utc), self.payload, hashlib.sha256(canonical.encode()).hexdigest(), 200)


class FakeOpenRouterTransport:
    """Return deterministic structured JSON through the production OpenRouter adapter."""
    def __init__(self):
        self.requests = []

    def post(self, url, *, headers, json: dict, timeout):
        self.requests.append(json)
        context_text = json["messages"][1]["content"]
        context = jsonlib.loads(re.search(r"Coaching context:\n(.*)", context_text, re.S).group(1))
        key = "1507:S" if any(i["identity"]["id"] == "S" for i in context["insights"]) else "1507:2"
        if context.get("player"):
            text = f"{context['player']['name']}: review the Zor'lok mechanic evidence."
            scope, player_id = "player", str(context["player"]["playerId"])
        else:
            text, scope, player_id = "Prioritize the high-impact Song of the Empress response.", "raid", None
        body = {"id": f"fake-response-{len(self.requests)}", "model": json["model"],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            "choices": [{"message": {"content": jsonlib.dumps({"recommendations": [
                {"scope": scope, "text": text, "source_insight_keys": [key], "kind": "observation",
                "player_id": player_id, "confidence": 0.9}], "candidate_source_insight_keys": [key]})}}]}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body,
            headers={"x-request-id": f"fake-request-{len(self.requests)}"})


def test_wipefest_openrouter_discord_vertical_slice_without_wcl_events(monkeypatch):
    payload = jsonlib.loads(FIXTURE.read_text())
    # Contract regression sentinels from the captured, complete response.
    assert payload["report"]["id"] == REPORT
    assert payload["info"]["id"] == 10 and payload["info"]["boss"] == 1507
    assert payload["percentile"] == 35.0
    assert any(i.get("weight", 0) > 90 for i in payload["insights"])
    assert payload["playerValues"] and payload["playerValues"][0]["values"]
    assert payload["raid"]["players"]

    class FakeWCL:
        def report_data(self, code):
            assert code == REPORT
            return {"fights": [{"id": 10, "encounterID": 1507, "name": FIGHT["name"],
                "startTime": 0, "endTime": 1, "inProgress": False}]}

        def ingest_fight(self, *args, **kwargs):
            raise AssertionError("WCL combat-event ingestion must not occur")

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    with session_factory() as db:
        profiles = CoachingProfileRepository(db)
        raid_revision = profiles.create_revision("raid_coach", provider="openrouter", model_slug="fake/model",
            system_prompt="Coach the raid from cited evidence.", user_prompt_template="Return structured advice.",
            output_schema_version="coaching-selection-v1", activate=True)
        player_revision = profiles.create_revision("player_coach", provider="openrouter", model_slug="fake/model",
            system_prompt="Coach the player from cited evidence.", user_prompt_template="Return structured advice.",
            output_schema_version="player-coaching-v1", activate=True)
        expected_revision_ids = {raid_revision.id, player_revision.id}
        db.commit()

    wipefest = FixtureWipefest(payload)
    transport = FakeOpenRouterTransport()
    inference = OpenRouterInferenceProvider(OpenRouterConfig(api_key="fixture-only", retries=0), transport)
    source = WipefestCoachingSource(wipefest, session_factory, inference)
    legacy = LazyLegacyWCLCoachingSource(lambda: (_ for _ in ()).throw(
        AssertionError("legacy mechanics path must not be constructed")))
    service = PullCoachService(FakeWCL(), CoachingOrchestrator(source, legacy))
    raid = service.run(REPORT, "10")
    player = service.run_player(REPORT, "10", "10")
    same_raid = service.run(REPORT, "10")

    assert wipefest.calls == [(REPORT, "10", "1507")] * 3
    assert len(transport.requests) == 2  # the repeated persisted raid session is a cache hit
    assert same_raid.session_id == raid.session_id
    assert raid.source == player.source == "wipefest"
    assert raid.coaching["recommendations"] and player.coaching["recommendations"]

    raid_message = PullCoachPresenter().present(raid)
    raid_message_again = PullCoachPresenter().present(same_raid)
    player_message = PullCoachPresenter().present(player)
    assert raid_message == raid_message_again
    assert "high-impact Song" in raid_message.embed.fields[0].value
    assert player.coaching["recommendations"][0]["text"] in player_message.embed.fields[0].value
    assert "Aleannora" in player_message.embed.fields[0].value

    with session_factory() as db:
        snapshot = db.scalar(select(WipefestFightSnapshot))
        runs = list(db.scalars(select(CoachingSession).order_by(CoachingSession.id)))
        assert len(runs) == 2 and all(run.status == "completed" for run in runs)
        assert {run.audience for run in runs} == {"raid", "player"}
        assert {run.snapshot_id for run in runs} == {snapshot.id}
        assert snapshot.report_code == REPORT and snapshot.fight_id == "10" and snapshot.group_id == "1507"
        assert snapshot.payload == payload  # complete provider response persisted without reshaping
        assert {run.profile_revision_id for run in runs} == expected_revision_ids
        for run in runs:
            assert run.request_context["source"] == {"provider": "wipefest", "snapshotId": snapshot.id,
                "reportCode": REPORT, "fightId": "10", "groupId": "1507"}
            assert run.request_context["fight"]["reportId"] == REPORT
            assert run.insight_provenance["generator"] == "llm"
            assert run.provider == "openrouter" and run.requested_model == "fake/model"
            assert run.profile_revision_id in expected_revision_ids
            assert run.structured_response["recommendations"][0]["source_insight_keys"]
            if run.audience == "raid":
                high_impact = next(i for i in run.request_context["insights"]
                    if i["identity"]["group"] == "1507" and i["identity"]["id"] == "S")
                assert high_impact["weight"] > 90
                assert "1507:S" in run.structured_response["recommendations"][0]["source_insight_keys"]
            messages = list(db.scalars(select(CoachingSessionMessage).where(
                CoachingSessionMessage.session_id == run.id).order_by(CoachingSessionMessage.sequence)))
            assert [message.role for message in messages] == ["system", "user", "assistant"]
            assert messages[-1].content == jsonlib.dumps(run.structured_response, sort_keys=True, ensure_ascii=False)
            request_messages = transport.requests[0 if run.audience == "raid" else 1]["messages"]
            assert [message.content for message in messages[:2]] == [m["content"] for m in request_messages]
            if run.audience == "player":
                assert run.request_context["playerValues"]
                assert run.request_context["evaluation"]
                assert run.request_context["player"]["name"] == "Aleannora"
