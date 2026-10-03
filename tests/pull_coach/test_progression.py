from dataclasses import replace

import pytest

from app.pull_coach.models import (
    AnalysisMetadata, EncounterIdentity, EvidenceReference, Finding, FindingCategory,
    PullAnalysis, PullIdentity, PullState, ProgressionStatus, RaidReportIdentity,
    Role, Severity, SourceIdentity, SummaryMetrics,
)
from app.pull_coach.progression import ProgressionComparator, ProgressionConfig


def analysis(number, *, mechanic=None, count=0, severity=Severity.MEDIUM,
             state=PullState.WIPE, percent=60.0, duration=30000, death=None,
             version="1", start=None, actor="a", role=Role.DAMAGE):
    start = number * 100000 if start is None else start
    pull = PullIdentity(RaidReportIdentity(SourceIdentity("wcl", "source"), "R"),
        EncounterIdentity("boss", "Boss"), str(number), number, start,
        start + duration if duration is not None else None, state, percent)
    findings = []
    if mechanic and count:
        findings.append(Finding(f"{number}-{mechanic}", FindingCategory.MECHANIC, severity,
            {"mechanic_id": mechanic, "failure_category": "avoidable_damage", "hit_count": count,
             "repeated": count > 1, "first_timestamp": start + 1},
            tuple(EvidenceReference(f"e{number}-{mechanic}-{i}", (f"ev{number}-{i}",))
                  for i in range(count)),
            (actor,), (role,), mechanic))
    if death is not None:
        findings.append(Finding(f"death-{number}", FindingCategory.DEATH, Severity.HIGH,
            {"timestamp": start + death}, (EvidenceReference(f"d{number}", (f"death{number}",)),),
            (actor,), (role,)))
    return PullAnalysis(pull, tuple(findings), (), SummaryMetrics(), AnalysisMetadata("analyzer", version))


def subject(result, subject_id):
    return next(s for s in result.subjects if s.subject_id == subject_id)


def test_resolve_then_stabilize_and_new_blocker_coexist():
    sequence = [analysis(1, mechanic="A", count=3, percent=63),
                analysis(2, percent=41),
                analysis(3, mechanic="B", count=2, severity=Severity.HIGH, percent=40.5, actor="z")]
    comparator = ProgressionComparator()
    results = comparator.compare_sequence(sequence)
    assert subject(results[1], "mechanic:A").status == ProgressionStatus.RESOLVED
    assert subject(results[2], "mechanic:A").status == ProgressionStatus.STABILIZED
    assert subject(results[2], "mechanic:B").status == ProgressionStatus.NEWLY_OBSERVED
    assert results[2].newly_exposed_blocker.subject.subject_id == "mechanic:B"
    assert next(d for d in results[1].deltas if d.metric == "boss_percent").status == ProgressionStatus.IMPROVED
    assert next(d for d in results[2].deltas if d.metric == "boss_percent").status == ProgressionStatus.STABLE


def test_reappearing_mechanic_is_regressed_not_newly_observed():
    results = ProgressionComparator().compare_sequence([
        analysis(1, mechanic="A", count=3), analysis(2), analysis(3, mechanic="A", count=2),
    ])
    returning = subject(results[2], "mechanic:A")
    assert returning.status == ProgressionStatus.REGRESSED
    delta = next(d for d in results[2].deltas if d.subject_id == "mechanic:A")
    assert (delta.previous_value, delta.current_value) == (0, 2)
    assert results[2].newly_exposed_blocker is None


def test_count_and_severity_deltas_are_classified_independently():
    values = [analysis(1, mechanic="A", count=4, severity=Severity.MEDIUM),
              analysis(2, mechanic="A", count=1, severity=Severity.HIGH)]
    result = ProgressionComparator().compare(values)
    assert next(d for d in result.deltas if d.metric == "failure_count").status == ProgressionStatus.IMPROVED
    assert next(d for d in result.deltas if d.metric == "max_severity_rank").status == ProgressionStatus.REGRESSED
    assert subject(result, "mechanic:A").status == ProgressionStatus.REGRESSED


def test_zero_threshold_equal_metric_is_stable():
    result = ProgressionComparator(ProgressionConfig(boss_percent_threshold=0)).compare(
        [analysis(1, percent=50), analysis(2, percent=50)])
    assert next(d for d in result.deltas if d.metric == "boss_percent").status == ProgressionStatus.STABLE


def test_prefix_invariance_and_order_normalization():
    values = [analysis(1, mechanic="A", count=2), analysis(2, percent=50), analysis(3, mechanic="B", count=1)]
    comparator = ProgressionComparator()
    direct = comparator.compare(values[:2])
    assert direct == comparator.compare_sequence(values)[1]
    assert comparator.compare(reversed(values[:2])) == direct
    assert comparator.compare_sequence(values) == comparator.compare_sequence(values)


def test_validation_of_encounter_and_analyzer_version():
    comparator = ProgressionComparator()
    with pytest.raises(ValueError, match="encounter_id"):
        comparator.compare([analysis(1), replace(analysis(2), pull=replace(analysis(2).pull,
            encounter=EncounterIdentity("other", "Other")))])
    with pytest.raises(ValueError, match="analyzer"):
        comparator.compare([analysis(1), analysis(2, version="2")])


def test_duration_death_and_pull_state_directions():
    comparator = ProgressionComparator()
    seq = comparator.compare_sequence([analysis(1, duration=30000, death=20000),
        analysis(2, duration=36000, death=32000), analysis(3, duration=35000, death=30000)])
    assert next(d for d in seq[1].deltas if d.metric == "duration_ms").status == ProgressionStatus.IMPROVED
    assert next(d for d in seq[1].deltas if d.metric == "first_death_offset_ms").status == ProgressionStatus.IMPROVED
    assert next(d for d in seq[2].deltas if d.metric == "first_death_offset_ms").status == ProgressionStatus.STABLE
    assert comparator.compare([analysis(1), analysis(2, state=PullState.KILL, percent=0)]).pull_result == ProgressionStatus.IMPROVED
    assert comparator.compare([analysis(1, state=PullState.KILL), analysis(2)]).pull_result == ProgressionStatus.REGRESSED


def test_failure_subject_actor_role_and_no_unknown_role_guessing():
    result = ProgressionComparator().compare_sequence([
        analysis(1, mechanic="A", count=2), analysis(2, mechanic="A", count=1),
    ])[1]
    assert subject(result, "actor:a:mechanic:A").status == ProgressionStatus.IMPROVED
    assert subject(result, "role:damage:mechanic:A").status == ProgressionStatus.IMPROVED
    unknown = ProgressionComparator().compare([analysis(1, mechanic="A", count=1, role=Role.UNKNOWN)])
    assert not any(s.subject_id.startswith("role:") for s in unknown.subjects)


def test_first_death_resolution_and_non_errors_do_not_create_player_subjects():
    clean = analysis(2)
    prior = analysis(1, death=20000)
    result = ProgressionComparator().compare([prior, clean])
    death_delta = next(d for d in result.deltas if d.metric == "first_death_offset_ms")
    assert death_delta.status == ProgressionStatus.IMPROVED and death_delta.current_value is None

    base = analysis(1)
    pressure = Finding("pressure", FindingCategory.MECHANIC, Severity.HIGH,
        {"failure_category": "healing_check", "event_count": 4},
        (EvidenceReference("pressure-e", ("pressure-event",)),), ("a",), (Role.HEALER,), "pulse")
    success = Finding("kick", FindingCategory.INTERRUPT, Severity.INFO,
        {"outcome": "success", "failure_category": "interrupt"},
        (EvidenceReference("kick-e", ("kick-event",)),), ("a",), (Role.DAMAGE,), "kick")
    with_facts = replace(base, findings=(pressure, success))
    compared = ProgressionComparator().compare([with_facts])
    ids = {s.subject_id for s in compared.subjects}
    assert "mechanic:pulse" in ids and "role:healer:mechanic:pulse" not in ids
    assert subject(compared, "mechanic:pulse").failure_category == "healing_check"
    assert "mechanic:kick" not in ids


def test_structured_actor_id_and_category_mechanic_identity():
    base = analysis(1)
    findings = tuple(Finding(f"f-{mechanic}", FindingCategory.MECHANIC, Severity.MEDIUM,
        {"failure_category": "avoidable_damage", "hit_count": 1},
        (EvidenceReference(f"e-{mechanic}", (f"event-{mechanic}",)),), ("wcl:1",),
        (Role.DAMAGE,), mechanic) for mechanic in ("A", "B"))
    result = ProgressionComparator().compare([replace(base, findings=findings)])
    assert subject(result, "actor:wcl:1:mechanic:A").actor_id == "wcl:1"
    category = subject(result, "category:avoidable_damage")
    assert category.mechanic_id is None


def test_repeated_is_derived_from_aggregated_occurrence_count():
    base = analysis(1)
    failures = tuple(Finding(f"kick-{index}", FindingCategory.INTERRUPT, Severity.HIGH,
        {"outcome": "failure", "failure_category": "interrupt", "hit_count": 1},
        (EvidenceReference(f"kick-e-{index}", (f"kick-event-{index}",)),),
        ("a",), (Role.DAMAGE,), "interrupt") for index in (1, 2))

    result = ProgressionComparator().compare([replace(base, findings=failures)])

    mechanic = subject(result, "mechanic:interrupt")
    assert mechanic.occurrence_count == 2
    assert mechanic.repeated is True


def test_blocker_ranking_has_deterministic_tie_break():
    sequence = [analysis(1, mechanic="old", count=2), analysis(2),
                analysis(3, mechanic="Z", count=2, severity=Severity.HIGH),
                analysis(3, mechanic="A", count=2, severity=Severity.HIGH)]
    # Use a single pull containing both candidate findings.
    both = replace(sequence[-1], findings=sequence[-1].findings + (replace(
        sequence[-2].findings[0], finding_id="candidate-Z", mechanic_id="Z",
        fact={**sequence[-2].findings[0].fact, "mechanic_id": "Z"}),))
    result = ProgressionComparator().compare([sequence[0], sequence[1], both])
    assert result.newly_exposed_blocker.subject.subject_id == "mechanic:A"


def test_replay_stage_uses_only_prior_results_and_serializes_deterministically():
    from pathlib import Path
    from app.pull_coach.progression import ProgressionReplayStage
    from app.pull_coach.replay import ReplayRunner

    root = Path(__file__).parents[2]

    class AnalysisStage:
        name = "analysis"
        def run(self, context):
            source = context.current.pull
            value = analysis(source.pull_number, mechanic="A" if source.pull_number == 1 else None,
                             count=2 if source.pull_number == 1 else 0,
                             percent=source.boss_percent)
            return replace(value, pull=source)

    runner = ReplayRunner(stages=[AnalysisStage(), ProgressionReplayStage()])
    manifest = root / "tests/replay/example-night.json"
    two = runner.run(manifest, through_pull=2)
    three = runner.run(manifest)
    assert two.pulls[1].stages["progression"] == three.pulls[1].stages["progression"]
    assert runner.run(manifest).canonical_json() == runner.run(manifest).canonical_json()


def test_replay_adapter_filters_night_wide_history_by_encounter():
    from types import SimpleNamespace
    from app.pull_coach.progression import ProgressionReplayStage

    boss_a = analysis(1)
    boss_b_pull = replace(analysis(1), pull=replace(analysis(1).pull,
        encounter=EncounterIdentity("boss-b", "Boss B")))
    current = replace(analysis(2), pull=replace(analysis(2).pull,
        encounter=EncounterIdentity("boss-b", "Boss B")))
    prior = (SimpleNamespace(encounter_id="boss-a", stages={"analysis": analysis(1)}),
             SimpleNamespace(encounter_id="boss-b", stages={"analysis": boss_b_pull}))
    context = SimpleNamespace(current_stage_outputs={"analysis": current},
        prior_pull_results=prior, encounter_id="boss-b")
    result = ProgressionReplayStage().run(context)
    assert result.compared_pull_numbers == (1, 2)
