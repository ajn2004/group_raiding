from types import SimpleNamespace

from app.pull_coach.models import PullState
from app.pull_coach.presentation import PullCoachPresenter, DiscordPresentationReplayStage
from app.pull_coach.workflow import PullCoachReportResult


def candidate(text):
    return SimpleNamespace(text=text)


def report_result():
    pull = SimpleNamespace(encounter=SimpleNamespace(name="Reference Boss"), pull_number=12,
        fight_id="42", start_timestamp=1000, end_timestamp=103400, state=PullState.WIPE,
        boss_percent=31.4, report=SimpleNamespace(report_code="ABC123"))
    public = SimpleNamespace(primary_failure=candidate("Avoid the blast"),
        improvements=(candidate("Interrupts improved"),), dps_actions=(candidate("Swap sooner"),),
        healer_actions=(), tank_actions=(), raid_actions=(candidate("Use cooldowns"),),
        next_pull_priorities=tuple(candidate(f"Priority {n}") for n in range(4)))
    finding = SimpleNamespace(finding_id="f-1", mechanic_id="blast", category=SimpleNamespace(value="mechanic"),
        severity=SimpleNamespace(value="high"), evidence=(SimpleNamespace(evidence_id="ev-1"),))
    coaching = SimpleNamespace(public=public, private_feedback=(SimpleNamespace(actor_id="secret-actor"),),
        input=SimpleNamespace(mechanic_labels=(("blast", "Blast"),)))
    analysis = SimpleNamespace(pull=pull, findings=(finding,))
    return PullCoachReportResult("ABC123", "https://classic.warcraftlogs.com/reports/ABC123?fight=42",
                                 pull, SimpleNamespace(), analysis, SimpleNamespace(), coaching)


def test_public_payload_order_limits_and_private_boundary():
    payload = PullCoachPresenter().present(report_result())
    embed = payload.embed
    assert "Reference Boss" in embed.title
    assert "Pull 12" in embed.description and "Fight 42" in embed.description
    assert "Wipe · 31.4% remaining · 1:42" in embed.description
    assert [field.name for field in embed.fields] == ["Primary failure", "Next-pull priorities",
        "What improved", "DPS", "Raid"]
    assert "Priority 2" in next(f.value for f in embed.fields if f.name == "Next-pull priorities")
    assert "Priority 3" not in next(f.value for f in embed.fields if f.name == "Next-pull priorities")
    assert embed.url.endswith("fight=42")
    serialized = repr(payload)
    assert "secret-actor" not in serialized and "player" not in serialized
    assert len(embed.title) <= 256 and len(embed.description) <= 4096 and len(embed.fields) <= 25
    assert all(len(field.name) <= 256 and len(field.value) <= 1024 for field in embed.fields)
    assert sum(map(len, (embed.title, embed.description, embed.url, embed.footer))) + sum(
        len(field.name) + len(field.value) for field in embed.fields) <= 6000


def test_replay_stage_uses_same_presenter_payload():
    result = report_result()
    context = SimpleNamespace(current_stage_outputs={"analysis": result.analysis,
        "progression": result.progression, "coaching": result.coaching}, current=result.target_ingestion,
        report_code="ABC123")
    # Compare structurally, including the report/fight link produced offline.
    from app.pull_coach.presentation import PullCoachPresenter
    live = PullCoachPresenter().present(result)
    replay = DiscordPresentationReplayStage().run(context)
    assert live == replay


def test_historical_context_is_explicit_and_target_link_is_preserved():
    from app.pull_coach.workflow import HistoricalSampleContext
    result = report_result()
    object.__setattr__(result, "historical_context", HistoricalSampleContext(3))
    payload = PullCoachPresenter().present(result)
    assert payload.embed.title.startswith("Historical Pull Coach")
    assert "3 completed pulls analyzed" in payload.embed.description
    assert "Target: Pull 12 · Fight 42" in payload.embed.description
    assert "Wipe · 31.4% remaining" in payload.embed.description
    assert payload.embed.url.endswith("fight=42")


def test_historical_kill_includes_target_boss_percentage_when_available():
    from app.pull_coach.workflow import HistoricalSampleContext
    result = report_result()
    object.__setattr__(result, "selected_pull", SimpleNamespace(**{**vars(result.selected_pull),
                                                                     "state": PullState.KILL,
                                                                     "boss_percent": 0.01}))
    object.__setattr__(result, "historical_context", HistoricalSampleContext(3))
    payload = PullCoachPresenter().present(result)
    assert "Target: Pull 12 · Fight 42 · Kill · Boss 0.01%" in payload.embed.description


def test_pathological_payload_obeys_discord_limits_and_keeps_primary_failure():
    result = report_result()
    result.selected_pull.encounter.name = "Encounter " + "X" * 6500
    object.__setattr__(result, "source_url", "https://" + "u" * 2700)
    public = result.coaching.public
    public.primary_failure = candidate("PRIMARY " + "P" * 1500)
    public.next_pull_priorities = tuple(candidate(f"Priority {n} " + "Q" * 1000) for n in range(3))
    public.improvements = tuple(candidate("Improvement " + str(i) + "I" * 1500) for i in range(100))
    public.dps_actions = tuple(candidate("Action " + "A" * 1500) for _ in range(100))
    result.analysis.findings = tuple(SimpleNamespace(finding_id="F" * 300,
        mechanic_id="M" * 300, category=SimpleNamespace(value="mechanic"),
        severity=SimpleNamespace(value="high"), evidence=tuple(SimpleNamespace(evidence_id="E" * 500)
        for _ in range(20))) for _ in range(100))
    payload = PullCoachPresenter().present(result)
    embed = payload.embed
    assert embed.title.startswith("Pull Coach — Encounter") and len(embed.title) <= 256
    assert "PRIMARY" in embed.fields[0].value
    assert "What improved" not in [field.name for field in embed.fields]
    assert len(embed.description) <= 4096 and len(embed.fields) <= 25
    assert all(len(f.name) <= 256 and len(f.value) <= 1024 for f in embed.fields)
    assert sum(map(len, (embed.title, embed.description, embed.url, embed.footer))) + sum(
        len(f.name) + len(f.value) for f in embed.fields) <= 6000
    assert len(payload.details) <= 2000
    assert payload == PullCoachPresenter().present(result)
