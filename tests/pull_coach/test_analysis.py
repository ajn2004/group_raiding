from app.pull_coach.analysis import AnalyzerConfig, PullAnalyzer
from app.pull_coach.mechanics import registry_from_dict
from app.pull_coach.models import (
    Actor, EncounterIdentity, EventType, FindingCategory, NormalizedEvent,
    PullIdentity, PullState, RaidReportIdentity, Role, SourceIdentity,
)


def setup():
    encounter = EncounterIdentity("boss", "Boss")
    pull = PullIdentity(RaidReportIdentity(SourceIdentity("test", "r"), "r"),
                        encounter, "f", 1, 0, 10000, PullState.WIPE)
    definitions = {"schema_version": 1, "registry_version": "r7", "definitions": [
        {"mechanic_id": "blast", "name": "Blast", "encounter": {"encounter_id": "boss", "name": "Boss"},
         "event_types": ["damage"], "ability_ids": [10], "failure_category": "avoidable_damage", "avoidable": True},
        {"mechanic_id": "pulse", "name": "Pulse", "encounter": {"encounter_id": "boss", "name": "Boss"},
         "event_types": ["damage"], "ability_ids": [20], "failure_category": "healing_check", "avoidable": False},
        {"mechanic_id": "kick", "name": "Kick", "encounter": {"encounter_id": "boss", "name": "Boss"},
         "event_types": ["interrupt"], "stopped_ability_ids": [30], "stopped_ability_metadata_field": "stopped_ability_id", "failure_category": "interrupt"},
        {"mechanic_id": "cleanse", "name": "Cleanse", "encounter": {"encounter_id": "boss", "name": "Boss"},
         "event_types": ["dispel"], "stopped_ability_ids": [40], "stopped_ability_metadata_field": "stopped_ability_id", "failure_category": "dispel"},
    ]}
    actors = (Actor("a", "A", role=Role.DAMAGE), Actor("b", "B", role=Role.HEALER),
              Actor("c", "C", role=Role.TANK))
    return pull, actors, PullAnalyzer(registry_from_dict(definitions))


def ev(ts, kind, eid, ability=None, target="a", source="boss", amount=None, **metadata):
    return NormalizedEvent(ts, kind, eid, source, target, ability_id=ability,
                           amount=amount, metadata=metadata)


def test_empty_unknown_and_deterministic_observations():
    pull, actors, analyzer = setup()
    empty = analyzer.analyze(pull, actors, [])
    assert empty.findings == empty.mechanic_observations == ()
    assert empty.summary.values["mechanic_registry_version"] == "r7"
    unknown = ev(1, EventType.DAMAGE, "u", 999, amount=12)
    result = analyzer.analyze(pull, actors, [unknown])
    assert not result.mechanic_observations and not result.findings
    assert analyzer.analyze(pull, actors, [unknown]) == result


def test_damage_repetition_and_mixed_death_window_preserve_both_categories():
    pull, actors, analyzer = setup()
    events = [ev(1000, EventType.DAMAGE, "a1", 10, amount=500),
              ev(1000, EventType.DAMAGE, "a2", 10, amount=100),
              ev(2000, EventType.DAMAGE, "p1", 20, amount=700),
              ev(2100, EventType.DAMAGE, "u1", 999, amount=50),
              ev(2200, EventType.DEATH, "d", target="a", source=None)]
    result = analyzer.analyze(pull, actors, events)
    damage = next(f for f in result.findings if f.category == FindingCategory.MECHANIC and f.mechanic_id == "blast")
    assert damage.fact["hit_count"] == 2 and damage.fact["total_damage"] == 600
    assert damage.fact["repeated"] and [e.event_ids for e in damage.evidence] == [("a1",), ("a2",)]
    death = next(f for f in result.findings if f.category == FindingCategory.DEATH)
    assert death.fact["contributing_categories"] == ("avoidable_damage", "healing_check")
    assert death.fact["matched_avoidable_damage_total"] == 600
    assert death.fact["matched_unavoidable_damage_total"] == 700
    assert death.fact["unmatched_damage_total"] == 50
    assert set(death.related_finding_ids) == {
        damage.finding_id, next(f for f in result.findings if f.mechanic_id == "pulse").finding_id
    }
    assert all(f.evidence for f in result.findings)
    assert analyzer.analyze(pull, actors, events) == result


def test_pure_avoidable_and_unavoidable_death_windows_and_actor_role():
    pull, actors, analyzer = setup()
    avoidable = analyzer.analyze(pull, actors, [ev(1, EventType.DAMAGE, "hit", 10, amount=9),
        ev(2, EventType.DEATH, "death", target="a", source=None)])
    death = next(f for f in avoidable.findings if f.category == FindingCategory.DEATH)
    assert death.fact["failure_category"] == "avoidable_damage"
    assert death.roles == (Role.DAMAGE,)
    unavoidable = analyzer.analyze(pull, actors, [ev(1, EventType.DAMAGE, "pulse", 20, amount=9),
        ev(2, EventType.DEATH, "death", target="a", source=None)])
    death = next(f for f in unavoidable.findings if f.category == FindingCategory.DEATH)
    assert death.fact["failure_category"] == "healing_check"
    assert not any("healer" in str(f.fact).lower() for f in unavoidable.findings)


def test_window_excludes_old_damage_and_observes_interrupt_dispel_success():
    pull, actors, analyzer = setup()
    events = [ev(1, EventType.DAMAGE, "old", 10, amount=999),
              ev(9000, EventType.INTERRUPT, "kick", 1, target=None, source="a", stopped_ability_id=30,
                 stopped_ability_name="Bolt"),
              ev(9100, EventType.DISPEL, "dispel", 2, target="b", source="a", stopped_ability_id=40,
                 stopped_ability_name="Curse"),
              ev(10000, EventType.DEATH, "death", target="a", source=None)]
    result = analyzer.analyze(pull, actors, events)
    death = next(f for f in result.findings if f.category == FindingCategory.DEATH)
    assert death.fact["pre_death_event_count"] == 0
    assert result.summary.values["interrupt_success_count"] == 1
    assert result.summary.values["dispel_success_count"] == 1
    assert next(f for f in result.findings if f.category == FindingCategory.INTERRUPT).fact["stopped_ability_name"] == "Bolt"
    assert next(f for f in result.findings if f.category == FindingCategory.DISPEL).roles == (Role.DAMAGE,)


def test_source_order_breaks_same_timestamp_ties_and_unknown_role_is_unknown():
    pull, actors, analyzer = setup()
    actors = (Actor("a", "A"),)
    first = ev(1, EventType.DAMAGE, "first", 10, amount=1)
    second = ev(1, EventType.DAMAGE, "second", 10, amount=2)
    result = analyzer.analyze(pull, actors, [first, second])
    observation = result.mechanic_observations[0]
    assert observation.evidence[0].event_ids == ("first",)
    finding = next(f for f in result.findings if f.category == FindingCategory.MECHANIC)
    assert finding.roles == (Role.UNKNOWN,)


def test_configured_death_window_boundary():
    pull, actors, analyzer = setup()
    analyzer = PullAnalyzer(analyzer.registry, AnalyzerConfig(pre_death_window_ms=100))
    result = analyzer.analyze(pull, actors, [ev(899, EventType.DAMAGE, "outside", 10, amount=3),
        ev(900, EventType.DAMAGE, "boundary", 10, amount=4),
        ev(1000, EventType.DEATH, "death", target="a", source=None)])
    death = next(f for f in result.findings if f.category == FindingCategory.DEATH)
    assert death.fact["pre_death_event_ids"] == ("boundary",)


def test_unavoidable_raid_damage_is_grouped_by_configured_gap():
    pull, actors, analyzer = setup()
    analyzer = PullAnalyzer(analyzer.registry, AnalyzerConfig(raid_window_gap_ms=100))
    result = analyzer.analyze(pull, actors, [
        ev(10, EventType.DAMAGE, "pulse-a", 20, target="a", amount=7),
        ev(110, EventType.DAMAGE, "pulse-b", 20, target="b", amount=8),
        ev(211, EventType.DAMAGE, "pulse-c", 20, target="a", amount=9),
    ])
    windows = [f for f in result.findings if f.fact.get("window")]
    assert [(f.fact["event_count"], f.fact["affected_actor_count"], f.fact["total_damage"])
            for f in windows] == [(2, 2, 15), (1, 1, 9)]
    assert windows[0].evidence[0].event_ids == ("pulse-a",)


def test_healing_check_uses_only_raid_window_and_is_not_repeated_failure():
    pull, actors, analyzer = setup()
    result = analyzer.analyze(pull, actors, [
        ev(10, EventType.DAMAGE, "pulse-a", 20, target="a", amount=7),
        ev(20, EventType.DAMAGE, "pulse-b", 20, target="a", amount=8),
    ])
    windows = [f for f in result.findings if f.fact.get("window")]
    assert len(result.findings) == 1
    assert len(windows) == 1
    assert result.summary.values["repeated_mechanic_failure_count"] == 0


def test_large_evidence_ids_are_compact_and_role_alignment_is_preserved():
    pull, actors, analyzer = setup()
    many_hits = [ev(i, EventType.DAMAGE, f"event-{i}", 10, amount=1) for i in range(400)]
    result = analyzer.analyze(pull, actors, many_hits)
    finding = next(f for f in result.findings if f.mechanic_id == "blast")
    assert len(finding.finding_id) <= 255
    assert len(finding.evidence) == 400

    missing_actor = ev(500, EventType.DAMAGE, "missing-actor", 10, target="missing", amount=1)
    finding = next(f for f in analyzer.analyze(pull, actors, [missing_actor]).findings
                   if f.category == FindingCategory.MECHANIC)
    assert finding.actor_ids == ("missing",)
    assert finding.roles == (Role.UNKNOWN,)


def test_overlapping_mechanics_count_damage_once_per_classification():
    pull, actors, _ = setup()
    registry = registry_from_dict({"schema_version": 1, "definitions": [
        {"mechanic_id": "general", "name": "General", "encounter": {"encounter_id": "boss", "name": "Boss"},
         "event_types": ["damage"], "ability_ids": [10], "failure_category": "avoidable_damage", "avoidable": True},
        {"mechanic_id": "phase", "name": "Phase", "encounter": {"encounter_id": "boss", "name": "Boss"},
         "event_types": ["damage"], "ability_ids": [10], "failure_category": "avoidable_damage", "avoidable": True,
         "metadata_predicates": {"phase": "phase-one"}},
    ]})
    # Set event phase metadata so both deliberately overlapping rules match.
    damage = NormalizedEvent(1, EventType.DAMAGE, "overlap", "boss", "a", ability_id=10,
                             amount=500, metadata={"phase": "phase-one"})
    death = ev(2, EventType.DEATH, "death", target="a", source=None)
    result = PullAnalyzer(registry).analyze(pull, actors, [damage, death])
    fact = next(f.fact for f in result.findings if f.category == FindingCategory.DEATH)
    assert fact["matched_avoidable_damage_total"] == 500


def test_explicit_cast_failure_configuration_does_not_infer_missing_interrupts():
    pull, actors, analyzer = setup()
    registry = registry_from_dict({"schema_version": 1, "definitions": [{
        "mechanic_id": "failed-kick", "name": "Failed Kick", "encounter": {"encounter_id": "boss", "name": "Boss"},
        "event_types": ["cast"], "ability_ids": [50], "failure_category": "interrupt",
        "metadata": {"outcome": "failure", "subject_actor": "source"},
    }]})
    analyzer = PullAnalyzer(registry)
    no_evidence = analyzer.analyze(pull, actors, [])
    assert not no_evidence.findings
    result = analyzer.analyze(pull, actors, [ev(1, EventType.CAST, "failed-cast", 50, source="a", target=None)])
    finding = result.findings[0]
    assert finding.category == FindingCategory.INTERRUPT
    assert finding.fact["outcome"] == "failure"
    assert finding.actor_ids == ("a",) and finding.roles == (Role.DAMAGE,)
    assert finding.evidence[0].event_ids == ("failed-cast",)


def test_offline_wcl_snapshot_ingests_through_registry_into_analysis():
    from pathlib import Path
    from app.pull_coach.mechanics import load_mechanic_registry
    from app.web_requests.warcraft_logs import WCLClient, WCLSnapshot

    root = Path(__file__).parents[2]
    snapshot = WCLSnapshot.load(root / "tests/fixtures/warcraft_logs/analyzer_reference_snapshot.json")
    ingestion = WCLClient().ingest_fight(snapshot, "ANALYSIS01", 7)
    registry = load_mechanic_registry(root / "app/pull_coach/mechanics/definitions/reference_analysis.json")
    result = PullAnalyzer(registry).analyze(ingestion.pull, ingestion.actors, ingestion.events)
    again = PullAnalyzer(registry).analyze(ingestion.pull, ingestion.actors, ingestion.events)
    assert result == again
    assert result.summary.values["avoidable_damage_total"] == 900
    deaths = [f for f in result.findings if f.category == FindingCategory.DEATH]
    assert deaths[0].fact["failure_category"] == "avoidable_damage"
    assert deaths[1].fact["contributing_categories"] == ("avoidable_damage", "healing_check")
    assert deaths[1].fact["matched_unavoidable_damage_total"] == 700
    assert deaths[1].fact["unmatched_damage_total"] == 50
    assert result.summary.values["interrupt_success_count"] == result.summary.values["dispel_success_count"] == 1
    assert all(f.evidence for f in result.findings)
    assert all(actor.role is None for actor in ingestion.actors if actor.player_name)
    assert all(role == Role.UNKNOWN for f in result.findings for role in f.roles)
