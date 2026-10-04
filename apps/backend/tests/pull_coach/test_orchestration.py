import pytest

from app.pull_coach.orchestration import (
    CoachingOrchestrator, CoachingSourceError, SourceMode, SourceSelection,
)
from app.pull_coach.service import PullCoachService
from app.pull_coach.sources import LazyLegacyWCLCoachingSource
from app.pull_coach.presentation.discord import PullCoachPresenter


class Source:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def coach(self, reference, fight):
        self.calls.append((reference, fight))
        if self.error:
            raise self.error
        return self.result


def test_wipefest_is_primary_and_does_not_require_local_mechanics():
    wipefest, legacy = Source("wipefest result"), Source("legacy result")
    fight = {"id": 5, "encounterID": 99999}
    result = CoachingOrchestrator(wipefest, legacy).coach("R1", fight)
    assert result == "wipefest result"
    assert wipefest.calls == [("R1", fight)]
    assert legacy.calls == []


def test_wipefest_failure_is_typed_and_fallback_is_opt_in():
    wipefest, legacy = Source(error=CoachingSourceError("provider unavailable")), Source("legacy")
    with pytest.raises(CoachingSourceError, match="provider unavailable"):
        CoachingOrchestrator(wipefest, legacy).coach("R1", {"id": 1})
    assert not legacy.calls

    result = CoachingOrchestrator(wipefest, legacy, SourceSelection(legacy_fallback=True)).coach(
        "R1", {"id": 1})
    assert result == "legacy"
    assert len(legacy.calls) == 1


def test_legacy_only_skips_wipefest_even_when_it_would_fail():
    wipefest, legacy = Source(error=RuntimeError()), Source("legacy")
    result = CoachingOrchestrator(wipefest, legacy, SourceSelection(SourceMode.LEGACY_ONLY)).coach(
        "R1", {"id": 2})
    assert result == "legacy"
    assert not wipefest.calls


def test_programmer_errors_are_not_hidden_by_fallback():
    wipefest, legacy = Source(error=AttributeError("bug")), Source("legacy")
    with pytest.raises(AttributeError, match="bug"):
        CoachingOrchestrator(wipefest, legacy, SourceSelection(legacy_fallback=True)).coach("R1", {"id": 1})
    assert not legacy.calls


def test_wipefest_service_selects_with_metadata_without_requesting_wcl_events():
    class WCL:
        def report_data(self, code):
            assert code == "R1"
            return {"fights": [{"id": 8, "encounterID": 99999, "name": "Unknown boss",
                                "endTime": 100, "startTime": 0}]}

        def ingest_fight(self, *args, **kwargs):
            pytest.fail("Wipefest primary must not request WCL events")

    result = object()
    wipefest, constructed_legacy = Source(result), []
    legacy = LazyLegacyWCLCoachingSource(lambda: constructed_legacy.append(True))
    service = PullCoachService(WCL(), CoachingOrchestrator(wipefest, legacy))
    assert service.run("R1") is result
    assert wipefest.calls[0][1]["id"] == 8
    assert constructed_legacy == []


def test_presenter_accepts_source_independent_coaching_result():
    from app.pull_coach.orchestration import CoachingRunResult

    payload = PullCoachPresenter().present(CoachingRunResult(
        "R1", "8", "99999", "Unknown boss", "https://example.test/report/R1/fight/8",
        {"recommendations": [{"text": "Spread before the pulse."}]}, 12, "wipefest"))
    assert payload.embed.title == "Pull Coach — Unknown boss"
    assert payload.embed.fields[0].value == "• Spread before the pulse."
