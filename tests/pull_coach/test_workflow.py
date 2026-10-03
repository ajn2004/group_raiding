from types import SimpleNamespace

import pytest

from app.pull_coach.workflow import (
    FightNotCompleted, FightNotFound, NoCompletedPulls, PullCoachWorkflow, source_report_url,
)


class FakeWCL:
    def __init__(self, fights):
        self.fights = fights
        self.ingested = []

    def report_data(self, reference):
        return {"fights": self.fights}

    def ingest_fight(self, snapshot, code, fight_id):
        self.ingested.append(str(fight_id))
        fight = next(f for f in self.fights if str(f["id"]) == str(fight_id))
        pull = SimpleNamespace(encounter=SimpleNamespace(encounter_id="42", name="Boss"),
            fight_id=str(fight_id), pull_number=len([f for f in self.fights if f["startTime"] <= fight["startTime"]]),
            start_timestamp=fight["startTime"], end_timestamp=fight["endTime"], state="wipe", boss_percent=20,
            report=SimpleNamespace(report_code="ABC123"))
        return SimpleNamespace(pull=pull, actors=(), events=())


class Analyzer:
    registry = SimpleNamespace(for_encounter=lambda encounter: (SimpleNamespace(mechanic_id="m", name="Mechanic"),))

    def analyze(self, pull, actors, events):
        return SimpleNamespace(pull=pull, findings=(), mechanic_observations=(), summary=None,
                               analyzer=SimpleNamespace(analyzer_name="test", analyzer_version="1"))


class Comparator:
    def compare(self, analyses):
        return tuple(a.pull.fight_id for a in analyses)


class Coach:
    def synthesize(self, analysis, progression, history, mechanic_labels):
        return SimpleNamespace()


def make(fights):
    wcl = FakeWCL(fights)
    return PullCoachWorkflow(wcl, Analyzer(), Comparator(), Coach()), wcl


def fights():
    return [
        {"id": 1, "encounterID": 42, "name": "Boss", "startTime": 10, "endTime": 20},
        {"id": 2, "encounterID": 42, "name": "Boss", "startTime": 30, "endTime": 40},
        {"id": 3, "encounterID": 0, "name": "Trash", "startTime": 50, "endTime": 60},
        {"id": 4, "encounterID": 42, "name": "Boss", "startTime": 70, "endTime": None, "inProgress": True},
        {"id": 5, "encounterID": 42, "name": "Boss", "startTime": 80, "endTime": 90},
    ]


def test_latest_uses_completed_boss_and_never_fetches_future_events():
    workflow, wcl = make(fights())
    result = workflow.run("ABC123")
    assert result.selected_pull.fight_id == "5"
    assert wcl.ingested == ["1", "2", "5"]


def test_explicit_target_uses_only_same_encounter_causal_prefix():
    workflow, wcl = make(fights())
    result = workflow.run("https://www.warcraftlogs.com/reports/ABC123", "2")
    assert result.selected_pull.fight_id == "2"
    assert wcl.ingested == ["1", "2"]
    assert result.source_url.endswith("fight=2")


def test_explicit_unknown_and_in_progress_fight_errors():
    workflow, _ = make(fights())
    with pytest.raises(FightNotFound):
        workflow.run("ABC123", "99")
    with pytest.raises(FightNotCompleted):
        workflow.run("ABC123", "4")


def test_latest_without_completed_encounter_fight_errors():
    workflow, _ = make([{"id": 1, "encounterID": 0, "startTime": 1, "endTime": 2}])
    with pytest.raises(NoCompletedPulls):
        workflow.run("ABC123")


def test_source_link_is_canonical_and_does_not_copy_url_query_secrets():
    link = source_report_url("https://www.warcraftlogs.com/reports/ABC123?access_token=secret",
                             "ABC123", "7")
    assert link == "https://www.warcraftlogs.com/reports/ABC123?fight=7"
    assert "secret" not in link


@pytest.mark.parametrize(("reference", "expected"), [
    ("https://classic.warcraftlogs.com/reports/ABC123?fight=1", "classic.warcraftlogs.com"),
    ("https://sod.warcraftlogs.com/reports/ABC123?token=secret#x", "sod.warcraftlogs.com"),
    ("ABC123", "classic.warcraftlogs.com"),
])
def test_source_link_preserves_supported_product_or_uses_default(reference, expected):
    link = source_report_url(reference, "ABC123", "7")
    assert link == f"https://{expected}/reports/ABC123?fight=7"
    assert "secret" not in link and "#" not in link
