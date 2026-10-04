from types import SimpleNamespace

import pytest

from app.pull_coach.coaching import CoachingProviderError, CoachingSynthesizer
from app.pull_coach.models import (
    AnalysisMetadata, EncounterIdentity, EvidenceReference, ExposureState, Finding,
    FindingCategory, MechanicExposure, PullAnalysis, PullIdentity, PullState,
    RaidReportIdentity, Role, Severity, SourceIdentity, SummaryMetrics,
)
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.workflow import PullCoachWorkflow


class HistoricalWCL:
    def __init__(self, states):
        self.fights = [{"id": i, "encounterID": 42, "name": "Boss", "startTime": i * 1000,
                        "endTime": i * 1000 + 500, "kill": state == PullState.KILL}
                       for i, state in enumerate(states, 1)]
        self.ingested = []

    def report_data(self, code):
        return {"fights": self.fights}

    def ingest_fight(self, snapshot, code, fight_id):
        self.ingested.append(str(fight_id))
        fight = next(f for f in self.fights if str(f["id"]) == str(fight_id))
        pull = PullIdentity(RaidReportIdentity(SourceIdentity("wcl", code), code),
            EncounterIdentity("42", "Boss"), str(fight_id), int(fight_id), fight["startTime"],
            fight["endTime"], PullState.KILL if fight["kill"] else PullState.WIPE,
            0 if fight["kill"] else 20)
        return SimpleNamespace(pull=pull, actors=(), events=())


def make_analysis(pull, failure_count, exposed=True):
    findings = ()
    if failure_count:
        findings = (Finding(f"A-{pull.pull_number}", FindingCategory.MECHANIC, Severity.HIGH,
            {"mechanic_id": "A", "failure_category": "avoidable_damage", "hit_count": failure_count,
             "repeated": failure_count > 1},
            (EvidenceReference(f"ev-A-{pull.pull_number}", (f"event-A-{pull.pull_number}",)),),
            ("wcl:player",), (Role.DAMAGE,), "A"),)
    exposures = (MechanicExposure("A", ExposureState.EXPOSED, 3),) if exposed else ()
    return PullAnalysis(pull, findings, (), SummaryMetrics(), AnalysisMetadata("test-analyzer", "1"), exposures,
                        ("wcl:player",))


class HistoricalAnalyzer:
    registry = SimpleNamespace(for_encounter=lambda encounter: (SimpleNamespace(mechanic_id="A", name="Alpha"),))

    def __init__(self, failures):
        self.failures = failures

    def analyze(self, pull, actors, events):
        number = pull.pull_number
        failure_count, exposed = self.failures[number - 1]
        return make_analysis(pull, failure_count, exposed)


def run_sample(states, failures, synthesizer=None):
    client = HistoricalWCL(states)
    workflow = PullCoachWorkflow(client, HistoricalAnalyzer(failures), ProgressionComparator(),
                                 synthesizer or CoachingSynthesizer())
    return workflow.run_encounter_sample("REPORT", "042"), client


@pytest.mark.parametrize("states", [
    [PullState.WIPE, PullState.WIPE, PullState.WIPE],
    [PullState.WIPE, PullState.WIPE, PullState.KILL],
])
def test_historical_real_progression_consumes_full_causal_sequence(states):
    result, client = run_sample(states, [(2, True), (0, True), (0, True)])
    assert client.ingested == ["1", "2", "3"]
    assert result.selected_pull.fight_id == "3"
    assert result.progression.compared_pull_numbers == (1, 2, 3)
    if states[-1] == PullState.KILL:
        from app.pull_coach.models import ProgressionStatus
        assert result.progression.pull_result == ProgressionStatus.IMPROVED


def test_kill_retains_exposed_clean_to_regression_failure_as_primary_coaching():
    from app.pull_coach.models import ProgressionStatus
    result, _ = run_sample([PullState.WIPE, PullState.WIPE, PullState.KILL],
                           [(3, True), (0, True), (2, True)])
    subject = next(item for item in result.progression.subjects if item.subject_id == "mechanic:A")
    assert subject.status == ProgressionStatus.REGRESSED
    assert result.coaching.public.primary_failure is not None
    assert "Alpha" in result.coaching.public.primary_failure.text


def test_historical_provider_outage_uses_deterministic_grounded_fallback():
    class BrokenProvider:
        def select(self, value, prompt):
            raise CoachingProviderError("private provider failure")
    result, _ = run_sample([PullState.WIPE, PullState.KILL], [(2, True), (1, True)],
                           CoachingSynthesizer(provider=BrokenProvider()))
    assert result.coaching.metadata.status == "fallback_provider_error"
    assert result.coaching.public.primary_failure is not None
    assert result.coaching.public.primary_failure.finding_ids
