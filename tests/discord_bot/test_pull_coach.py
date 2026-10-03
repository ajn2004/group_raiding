import os
import asyncio

# The legacy commands package imports DBController; it constructs an engine but
# these tests never connect to a database.
for key, value in {
    "SQLALCHEMY_DATABASE_USER": "test", "SQLALCHEMY_DATABASE_PASSWORD": "test",
    "SQLALCHEMY_DATABASE_HOST": "localhost", "SQLALCHEMY_DATABASE_PORT": "5432",
    "SQLALCHEMY_DATABASE_DB": "test",
}.items():
    os.environ[key] = value

from types import SimpleNamespace

import app.config as app_config
app_config.USERNAME, app_config.PASSWORD = "test", "test"
app_config.DB_SERVER, app_config.DB_NAME = "localhost:5432", "test"

from app.discord_bot.commands import pull_coach as command_module
from app.discord_bot.commands.pull_coach import PullCoach
from tests.pull_coach.test_discord_presentation import report_result
from app.pull_coach.analysis import PullAnalyzer
from app.pull_coach.coaching import CoachingSynthesizer
from app.pull_coach.mechanics.loader import load_mechanic_registry
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.workflow import PullCoachWorkflow
from app.web_requests.warcraft_logs import WCLClient


def test_slash_command_defers_then_offloads_workflow_and_sends_payload(monkeypatch):
    order = []
    result = report_result()

    class Workflow:
        def run(self, report, fight):
            order.append(("run", report, fight))
            return result

    class Followup:
        async def send(self, **kwargs):
            order.append(("send", kwargs))

    class Context:
        followup = Followup()

        async def defer(self):
            order.append(("defer",))

    async def to_thread(fn, *args):
        order.append(("offload",))
        return fn(*args)

    monkeypatch.setattr(command_module.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(command_module, "to_discord_embed", lambda payload: payload)
    cog = PullCoach(None, workflow_factory=Workflow)
    asyncio.run(PullCoach.pullcoach.callback(cog, Context(), "ABC123", "latest"))
    assert order[0] == ("defer",)
    assert order[1] == ("offload",)
    assert order[2] == ("run", "ABC123", "latest")
    assert order[3][0] == "send"
    assert order[3][1]["embed"].embed.url.endswith("fight=42")


def test_slash_command_converts_expected_failure_to_friendly_response(monkeypatch):
    class Workflow:
        def run(self, report, fight):
            raise command_module.NoCompletedPulls()

    sent = []

    class Followup:
        async def send(self, value):
            sent.append(value)

    class Context:
        followup = Followup()

        async def defer(self):
            pass

    async def to_thread(fn, *args):
        return fn(*args)

    monkeypatch.setattr(command_module.asyncio, "to_thread", to_thread)
    cog = PullCoach(None, workflow_factory=Workflow)
    asyncio.run(PullCoach.pullcoach.callback(cog, Context(), "ABC123", "latest"))
    assert sent == ["That report has no completed boss pulls to analyze."]


def test_command_boundary_maps_failures_without_leaking_exception_text(monkeypatch):
    cases = [
        (command_module.InvalidReportReference("secret-token invalid URL"), "supported Warcraft Logs"),
        (command_module.ReportUnavailable("private secret-token"), "couldn't access that report"),
        (command_module.RateLimitError("secret-token"), "rate-limiting"),
        (command_module.AuthenticationError("secret-token"), "connection is not configured"),
        (command_module.TransportError("secret-token"), "returned an error"),
        (command_module.MalformedResponse("secret-token"), "returned an error"),
        (command_module.PaginationError("secret-token"), "returned an error"),
        (command_module.PullCoachConfigurationError("secret-token"), "mechanic definitions"),
        (command_module.UnsupportedEncounter("secret-token"), "mechanic definitions"),
        (command_module.NoCompletedPulls("secret-token"), "no completed boss pulls"),
        (command_module.FightNotFound("secret-token"), "find that fight ID"),
        (command_module.FightNotCompleted("secret-token"), "still in progress"),
        (command_module.InvalidFightSelector("secret-token"), "Fight must be"),
        (RuntimeError("secret-token unexpected analyzer failure"), "couldn't analyze it"),
    ]

    for error, expected in cases:
        events = []

        class Workflow:
            def run(self, report, fight):
                raise error

        class Followup:
            async def send(self, value):
                events.append(("send", value))

        class Context:
            followup = Followup()

            async def defer(self):
                events.append(("defer",))

        async def to_thread(fn, *args):
            return fn(*args)

        monkeypatch.setattr(command_module.asyncio, "to_thread", to_thread)
        cog = PullCoach(None, workflow_factory=Workflow)
        asyncio.run(PullCoach.pullcoach.callback(cog, Context(), "ABC123", "latest"))
        assert events[0] == ("defer",)
        assert expected.lower() in events[1][1].lower()
        assert "secret-token" not in events[1][1]
        assert "unexpected analyzer failure" not in events[1][1]


def test_mocked_wcl_reaches_real_pipeline_and_command(monkeypatch):
    fights = [
        {"id": i, "encounterID": 42, "name": "Reference Boss", "startTime": i * 1000,
         "endTime": i * 1000 + 500, "kill": False, "inProgress": False, "bossPercentage": 70 - i}
        for i in (1, 2, 3)
    ]
    report = {"code": "ABC123", "fights": fights, "masterData": {
        "actors": [{"id": 1, "type": "Player", "name": "Secret Player", "subType": "Mage"},
                   {"id": 2, "type": "NPC", "name": "Reference Boss"}],
        "abilities": [{"gameID": 90, "name": "Avoidable Blast"}],
    }}

    class Transport:
        def __init__(self):
            self.event_fights = []

        def graphql(self, query, variables):
            if "fights{" in query:
                return {"data": {"reportData": {"report": report}}}
            fight_id = int(variables["fightIDs"][0])
            self.event_fights.append(fight_id)
            start = fight_id * 1000
            return {"data": {"reportData": {"report": {"events": {
                "data": [{"type": "damage", "timestamp": start + 100, "sourceID": 2,
                          "targetID": 1, "abilityGameID": 90, "amount": fight_id * 10}],
                "nextPageTimestamp": None,
            }}}}}

    transport = Transport()
    registry = load_mechanic_registry("app/pull_coach/mechanics/definitions/reference_analysis.json")
    workflow = PullCoachWorkflow(WCLClient(transport=transport), PullAnalyzer(registry),
                                 ProgressionComparator(), CoachingSynthesizer())
    sent = []

    class Followup:
        async def send(self, **kwargs):
            sent.append(kwargs)

    class Context:
        followup = Followup()

        async def defer(self):
            sent.append("deferred")

    cog = PullCoach(None, workflow_factory=lambda: workflow)
    asyncio.run(PullCoach.pullcoach.callback(cog, Context(),
        "https://classic.warcraftlogs.com/reports/ABC123", "2"))
    assert transport.event_fights == [1, 2]
    assert sent[0] == "deferred"
    embed = sent[1]["embed"]
    assert "Reference Boss" in embed.title
    assert "Pull 2" in embed.description and "Fight 2" in embed.description
    assert embed.url.endswith("fight=2")
    assert "Secret Player" not in repr(embed)


def test_reference_snapshot_live_pipeline_matches_replay_for_each_pull(tmp_path):
    import json
    from pathlib import Path
    from app.pull_coach.analysis import PullAnalyzer
    from app.pull_coach.coaching import CoachingReplayStage
    from app.pull_coach.mechanics import load_mechanic_registry
    from app.pull_coach.models import EncounterIdentity
    from app.pull_coach.presentation import DiscordPresentationReplayStage, PullCoachPresenter
    from app.pull_coach.progression import ProgressionComparator, ProgressionReplayStage
    from app.pull_coach.replay import ReplayRunner

    root = Path(__file__).parents[2]
    snapshot = json.loads((root / "tests/fixtures/warcraft_logs/replay_snapshot.json").read_text())
    report = snapshot["report"]

    class SnapshotTransport:
        def __init__(self):
            self.event_fights = []

        def graphql(self, query, variables):
            if "fights{" in query:
                return {"data": {"reportData": {"report": report}}}
            fight_id = str(variables["fightIDs"][0])
            self.event_fights.append(fight_id)
            return {"data": {"reportData": {"report": {"events": snapshot["event_pages"][fight_id][0]}}}}

    registry = load_mechanic_registry(root / "app/pull_coach/mechanics/definitions/reference_analysis.json")
    analyzer = PullAnalyzer(registry)
    transport = SnapshotTransport()
    live_client = WCLClient(transport=transport)
    live_workflow = PullCoachWorkflow(live_client, analyzer, ProgressionComparator(), CoachingSynthesizer())
    live_payloads = [PullCoachPresenter().present(live_workflow.run("REFERENCE-NIGHT", str(fight)))
                     for fight in (12, 13, 14)]

    manifest = json.loads((root / "tests/replay/example-night.json").read_text())
    manifest["snapshot"] = str(root / "tests/fixtures/warcraft_logs/replay_snapshot.json")
    manifest["baseline"] = None
    manifest_path = tmp_path / "reference-night.json"
    manifest_path.write_text(json.dumps(manifest))
    stages = [
        type("AnalysisStage", (), {"name": "analysis", "run": lambda self, ctx:
             analyzer.analyze(ctx.current.pull, ctx.current.actors, ctx.current.events)})(),
        ProgressionReplayStage(ProgressionComparator()),
        CoachingReplayStage(CoachingSynthesizer(), {m.mechanic_id: m.name for m in registry.for_encounter(
            EncounterIdentity("42", "Reference Boss"))}),
        DiscordPresentationReplayStage(),
    ]
    runner = ReplayRunner(stages=stages)
    through_two = runner.run(manifest_path, through_pull=2)
    full = runner.run(manifest_path)
    replay_payloads = [pull.stages["discord"] for pull in full.pulls]
    assert live_payloads == replay_payloads
    assert len(full.pulls) == 3
    first = live_payloads[0].embed
    second = live_payloads[1].embed
    third = live_payloads[2].embed
    assert any(field.name == "Primary failure" and "Avoidable Blast" in field.value
               for field in first.fields)
    assert any(field.name == "Next-pull priorities" and field.value.strip()
               for field in first.fields)
    assert any(field.name == "What improved" and field.value.strip()
               for field in second.fields)
    from app.pull_coach.models import ProgressionStatus
    assert any(subject.mechanic_id == "avoidable-blast" and
               subject.status == ProgressionStatus.STABILIZED
               for subject in full.pulls[2].stages["progression"].subjects)
    assert any(subject.mechanic_id == "raid-pulse" and
               subject.status == ProgressionStatus.NEWLY_OBSERVED
               for subject in full.pulls[2].stages["progression"].subjects)
    assert any(field.name == "Primary failure" and "Raid Pulse" in field.value
               for field in third.fields)
    assert through_two.pulls[1].stages["discord"] == full.pulls[1].stages["discord"]
    assert [pull.fight_id for pull in through_two.pulls] == ["12", "13"]
    # Explicit live target 13 never requests fight 14's WCL events.
    transport.event_fights.clear()
    live_workflow.run("REFERENCE-NIGHT", "13")
    assert transport.event_fights == ["12", "13"]


def test_bot_keeps_legacy_raid_and_registers_pullcoach_application_command():
    async def load_bot():
        from app.discord_bot.bot import bot
        return bot

    bot = asyncio.run(load_bot())
    assert bot.get_cog("Raid") is not None
    assert bot.get_cog("PullCoach") is not None
    assert bot.get_command("raid") is not None
    assert any(command.name == "pullcoach" for command in bot.pending_application_commands)


def test_pycord_extension_setup_uses_synchronous_add_cog():
    registered = []

    class Bot:
        def add_cog(self, cog):
            registered.append(cog)

    result = command_module.setup(Bot())
    assert result is None
    assert len(registered) == 1 and isinstance(registered[0], PullCoach)
