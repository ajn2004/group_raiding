from dataclasses import replace
import hashlib

from app.pull_coach.models import (
    AnalysisMetadata, EncounterIdentity, EvidenceReference, Finding, FindingCategory,
    PullAnalysis, PullIdentity, PullState, RaidReportIdentity,
    ProgressionStatus, Role, Severity, SourceIdentity, SummaryMetrics,
)
from app.pull_coach.progression import ProgressionComparator
from app.pull_coach.coaching import CoachingConfig, CoachingSynthesizer


def pull(number, findings=()):
    identity = PullIdentity(RaidReportIdentity(SourceIdentity("wcl", "src"), "R"),
        EncounterIdentity("boss", "Boss"), str(number), number, number * 1000,
        number * 1000 + 500, PullState.WIPE, 50)
    return PullAnalysis(identity, tuple(findings), (), SummaryMetrics(), AnalysisMetadata("a", "1"))


def failure(fid, mechanic, *, category="avoidable_damage", roles=(Role.DAMAGE,), actor="wcl:1"):
    fact = {"failure_category": category, "hit_count": 3, "repeated": True}
    if category in ("interrupt", "dispel"):
        fact["outcome"] = "failure"
    return Finding(fid, FindingCategory.MECHANIC, Severity.HIGH,
        fact,
        (EvidenceReference("e-" + fid, ("event-" + fid,)),), (actor,), roles, mechanic)


def test_grounded_fallback_is_repeatable_private_actor_free_and_progression_aware():
    a = pull(1, [failure("f-a1", "A")])
    b = pull(2)
    c = pull(3, [failure("f-b3", "B")])
    progression = ProgressionComparator().compare([a, b, c])
    synth = CoachingSynthesizer()
    result = synth.synthesize(c, progression, history=(a, b), mechanic_labels={"A": "Alpha", "B": "Beta"})
    assert "Beta" in result.rendered_text
    assert "Alpha" not in result.rendered_text
    assert "wcl:1" not in result.rendered_text
    assert result == synth.synthesize(c, progression, history=(a, b), mechanic_labels={"A": "Alpha", "B": "Beta"})
    assert not any(item.mechanic_id == "A" for item in result.public.improvements)
    assert result.public.primary_failure.mechanic_id == "B"


def test_healing_check_does_not_become_healer_action():
    pressure = failure("pressure", "H", category="healing_check", roles=(Role.HEALER,))
    current = pull(1, [pressure])
    result = CoachingSynthesizer().synthesize(current, ProgressionComparator().compare([current]))
    assert not result.public.healer_actions
    assert "Healers" not in result.rendered_text


def test_death_linked_to_mechanic_does_not_create_duplicate_public_failure():
    mechanic = failure("mechanic-f", "A")
    death = Finding("death-f", FindingCategory.DEATH, Severity.HIGH,
        {"failure_category": "avoidable_damage", "contributing_mechanic_ids": ("A",)},
        (EvidenceReference("death-e", ("death-event",)),), ("wcl:1",), (Role.DAMAGE,),
        related_finding_ids=("mechanic-f",))
    current = pull(1, [mechanic, death])
    result = CoachingSynthesizer().synthesize(current, ProgressionComparator().compare([current]))
    claims = [candidate for candidate in result.candidates if candidate.kind == "failure_candidate"
              or candidate.kind == "primary_failure"]
    assert len(claims) == 1
    assert claims[0].finding_ids == ("mechanic-f",)


def test_next_pull_priorities_deduplicate_same_canonical_mechanic():
    current = pull(1, [failure("actor-a", "A", actor="wcl:1"),
                       failure("actor-b", "A", actor="wcl:2")])
    result = CoachingSynthesizer().synthesize(current, ProgressionComparator().compare([current]))
    assert len(result.public.next_pull_priorities) == 1
    assert result.public.next_pull_priorities[0].progression_subject_ids == ("mechanic:A",)


def test_provider_untrusted_ids_are_filtered_and_fallback_remains_useful():
    class Evil:
        provider_name = "fake"
        model_name = None
        def select(self, coaching_input, prompt):
            from app.pull_coach.coaching.models import CoachingSelection
            return CoachingSelection(dps_action_ids=("invented-mechanic",), priority_ids=("unknown",))

    current = pull(1, [failure("f", "A")])
    result = CoachingSynthesizer(provider=Evil()).synthesize(
        current, ProgressionComparator().compare([current]))
    assert result.metadata.status == "fallback_invalid_provider"
    assert "A" in result.rendered_text
    assert "invented" not in result.rendered_text


def test_role_actions_require_explicit_supported_roles():
    current = pull(1, [failure("f", "Kick", category="interrupt", roles=(Role.DAMAGE,))])
    result = CoachingSynthesizer().synthesize(current, ProgressionComparator().compare([current]))
    assert result.public.dps_actions
    assert result.public.dps_actions[0].finding_ids == ("f",)


def test_limits_are_explicit_and_applied():
    findings = [failure(f"f{i}", f"M{i}") for i in range(5)]
    current = pull(1, findings)
    result = CoachingSynthesizer(config=CoachingConfig(max_priorities=1)).synthesize(
        current, ProgressionComparator().compare([current]))
    assert len(result.public.next_pull_priorities) <= 1


def test_newly_exposed_raid_blocker_outranks_role_actions_in_priorities():
    from app.pull_coach.progression.models import BlockerPriority, ProgressionBlocker

    findings = [
        failure("dps", "DPS"),
        failure("healer", "Healer", roles=(Role.HEALER,)),
        failure("tank", "Tank", roles=(Role.TANK,)),
        failure("blocker", "Blocker", roles=(Role.DAMAGE,)),
    ]
    current = pull(1, findings)
    progression = ProgressionComparator().compare([current])
    blocker = next(subject for subject in progression.subjects if subject.subject_id == "mechanic:Blocker")
    progression = replace(progression, newly_exposed_blocker=ProgressionBlocker(
        blocker, BlockerPriority(blocker.max_severity_rank, blocker.repeated,
                                 blocker.occurrence_count, blocker.death_linked)))

    result = CoachingSynthesizer(config=CoachingConfig(max_priorities=3)).synthesize(current, progression)

    assert any(candidate.progression_subject_ids == ("mechanic:Blocker",)
               for candidate in result.public.next_pull_priorities)


def test_provider_wrong_audience_and_unknown_ids_are_rejected_without_free_text():
    from app.pull_coach.coaching.models import CoachingSelection

    class Malicious:
        provider_name = "fake"
        model_name = "none"
        def select(self, coaching_input, prompt):
            assert "AVAILABLE_CANDIDATES" in prompt and "Only IDs" in prompt
            healer_id = "action:" + hashlib.sha256(b"action:healer:f").hexdigest()[:16]
            return CoachingSelection(dps_action_ids=("nonexistent", "player-name", "wcl:1", healer_id),
                                     priority_ids=("invented-mechanic",))

    current = pull(1, [failure("f", "A", roles=(Role.HEALER,))])
    result = CoachingSynthesizer(provider=Malicious()).synthesize(
        current, ProgressionComparator().compare([current]))
    assert result.validation.rejected_ids
    assert not result.public.dps_actions
    assert "player-name" not in result.rendered_text
    assert "invented-mechanic" not in result.rendered_text
    assert "A" in result.rendered_text


def test_provider_failure_and_valid_selection_use_only_grounded_candidates():
    from app.pull_coach.coaching import CoachingProviderError
    from app.pull_coach.coaching.models import CoachingSelection

    current = pull(1, [failure("f", "A")])
    progression = ProgressionComparator().compare([current])

    class Broken:
        provider_name = "broken"
        model_name = None
        def select(self, coaching_input, prompt):
            raise CoachingProviderError("unavailable")

    fallback = CoachingSynthesizer(provider=Broken()).synthesize(current, progression)
    assert fallback.metadata.status == "fallback_provider_error"
    assert fallback.public.primary_failure.finding_ids == ("f",)

    class Capturing:
        provider_name = "fake"
        model_name = "selection-only"
        def select(self, coaching_input, prompt):
            assert "SUPPORTED FINDINGS" in prompt and "PROGRESSION" in prompt
            # Selection is by the one available grounded primary ID from prompt inventory.
            import json
            available = json.loads(prompt.split("AVAILABLE_CANDIDATES: ", 1)[1].split("\n", 1)[0])
            primary = next(item["id"] for item in available if item["kind"] == "primary_failure")
            return CoachingSelection(primary_failure_id=primary)

    selected = CoachingSynthesizer(provider=Capturing()).synthesize(current, progression)
    assert selected.metadata.status == "provider_partial"
    assert selected.public.primary_failure.finding_ids == ("f",)


def test_replay_coaching_stage_is_encounter_scoped_and_prefix_stable():
    from types import SimpleNamespace
    from app.pull_coach.coaching import CoachingReplayStage

    prior = pull(1, [failure("prior", "A")])
    current = pull(2, [failure("current", "B")])
    unrelated = replace(prior, pull=replace(prior.pull,
        encounter=EncounterIdentity("other", "Other")))
    progression = ProgressionComparator().compare([prior, current])
    context = SimpleNamespace(current_stage_outputs={"analysis": current, "progression": progression},
        prior_pull_results=(SimpleNamespace(encounter_id="other", stages={"analysis": unrelated}),
                            SimpleNamespace(encounter_id="boss", stages={"analysis": prior})),
        encounter_id="boss")
    stage = CoachingReplayStage()
    first = stage.run(context)
    context.prior_pull_results = context.prior_pull_results + (
        SimpleNamespace(encounter_id="boss", stages={"analysis": pull(3, [failure("future", "C")])}),)
    second = stage.run(context)
    assert first == second
    assert all(f.finding_id != "future" for f in first.input.findings)
    assert first.rendered_text == second.rendered_text


def test_renderer_reduces_optional_sections_before_primary_to_fit_limit():
    current = pull(1, [failure(f"f{i}", f"Mechanic {i}") for i in range(5)])
    result = CoachingSynthesizer(config=CoachingConfig(max_rendered_characters=90)).synthesize(
        current, ProgressionComparator().compare([current]))
    assert result.public.primary_failure is not None
    assert len(result.rendered_text) <= 90
    assert "Primary:" in result.rendered_text


def test_candidates_aggregate_mechanic_findings_and_prioritize_action_text():
    current = pull(1, [failure("actor-a", "A", actor="wcl:1"),
                       failure("actor-b", "A", actor="wcl:2")])
    result = CoachingSynthesizer().synthesize(current, ProgressionComparator().compare([current]),
                                               mechanic_labels={"A": "Fire Wave"})
    assert result.public.primary_failure.finding_ids == ("actor-a", "actor-b")
    assert "6 times" in result.public.primary_failure.text
    assert result.public.next_pull_priorities[0].kind in ("role_action", "raid_action")
    assert "Reduce avoidable hits" in result.public.next_pull_priorities[0].text


def test_provider_can_select_an_alternate_primary_and_omissions_keep_fallback():
    from app.pull_coach.coaching.models import CoachingSelection
    current = pull(1, [failure("fa", "A"), failure("fb", "B")])
    progression = ProgressionComparator().compare([current])

    class Selector:
        provider_name = "selector"
        model_name = None
        def select(self, coaching_input, prompt):
            import json
            available = json.loads(prompt.split("AVAILABLE_CANDIDATES: ", 1)[1].split("\n", 1)[0])
            assert any(item["text"].startswith("A was hit") and item["finding_ids"] == ["fa"] for item in available)
            alternate = next(item["id"] for item in available
                             if item["kind"] == "primary_failure" and item["finding_ids"] == ["fb"])
            return CoachingSelection(primary_failure_id=alternate)

    result = CoachingSynthesizer(provider=Selector()).synthesize(current, progression)
    assert result.public.primary_failure.finding_ids == ("fb",)
    assert result.public.dps_actions  # omitted actions remain from deterministic fallback


def test_improved_candidate_includes_current_and_historical_evidence():
    prior = pull(1, [failure("old", "A")])
    current = pull(2, [failure("new", "A")])
    progression = ProgressionComparator().compare([prior, current])
    from app.pull_coach.models import ProgressionStatus
    progression = replace(progression, subjects=tuple(replace(subject, status=ProgressionStatus.IMPROVED)
        if subject.subject_id == "mechanic:A" else subject for subject in progression.subjects))
    result = CoachingSynthesizer().synthesize(current, progression, history=(prior,))
    improved = next(candidate for candidate in result.candidates if candidate.kind == "improvement")
    assert improved.finding_ids == ("new", "old")


def test_input_rejects_mismatched_progression_and_renderer_preserves_long_primary():
    from app.pull_coach.coaching.input import build_input
    current = pull(1, [failure("f", "A")])
    other = pull(2)
    with __import__("pytest").raises(ValueError, match="current_pull"):
        build_input(current, ProgressionComparator().compare([other]))
    result = CoachingSynthesizer(config=CoachingConfig(max_rendered_characters=10)).synthesize(
        current, ProgressionComparator().compare([current]))
    assert result.rendered_text
    assert len(result.rendered_text) <= 10


def test_primary_ranking_uses_occurrences_before_identity_and_singular_grammar():
    current = pull(1, [failure("z-many", "Z-many"), failure("a-few", "A-few")])
    # Distinct evidence event counts model unequal deterministic significance.
    many = replace(failure("z-many", "Z-many"), evidence=tuple(
        EvidenceReference(f"many-{i}", (f"many-event-{i}",)) for i in range(5)))
    few = replace(failure("a-few", "A-few"), evidence=(EvidenceReference("few", ("few-event",)),))
    current = pull(1, [many, few])
    progression = ProgressionComparator().compare([current])
    result = CoachingSynthesizer().synthesize(current, progression)
    assert result.public.primary_failure.mechanic_id == "Z-many"
    singular = pull(1, [replace(failure("one", "One"), fact={"failure_category": "avoidable_damage", "hit_count": 1})])
    assert "was hit 1 time this pull" in CoachingSynthesizer().synthesize(
        singular, ProgressionComparator().compare([singular])).public.primary_failure.text


def test_primary_ranking_death_linkage_then_repetition_precede_counts():
    base = [failure("many", "A-many"), failure("linked", "Z-linked")]
    death = Finding("death", FindingCategory.DEATH, Severity.HIGH,
        {"failure_category": "avoidable_damage"},
        (EvidenceReference("death-e", ("death-event",)),), (), (), related_finding_ids=("linked",))
    current = pull(1, [*base, death])
    progression = ProgressionComparator().compare([current])
    selected = CoachingSynthesizer().synthesize(current, progression).public.primary_failure
    assert selected.mechanic_id == "Z-linked"

    single = replace(failure("single", "Z-single"), fact={"failure_category": "avoidable_damage", "hit_count": 1})
    repeated = replace(failure("repeat", "A-repeat"), fact={"failure_category": "avoidable_damage", "hit_count": 1, "repeated": True})
    current = pull(1, [single, repeated])
    result = CoachingSynthesizer().synthesize(current, ProgressionComparator().compare([current]))
    assert result.public.primary_failure.mechanic_id == "A-repeat"


def test_category_improvement_is_suppressed_only_for_shared_mechanic_evidence():
    prior = pull(1, [failure("old-a", "A"), failure("old-b", "B")])
    current = pull(2, [failure("new-a", "A"), failure("new-b", "B")])
    progression = ProgressionComparator().compare([prior, current])
    progression = replace(progression, subjects=tuple(
        replace(subject, status=ProgressionStatus.IMPROVED)
        if subject.subject_id in ("mechanic:A", "mechanic:B", "category:avoidable_damage") else subject
        for subject in progression.subjects))
    result = CoachingSynthesizer().synthesize(current, progression, history=(prior,))
    improved = [candidate for candidate in result.candidates if candidate.kind == "improvement"]
    # Both named mechanics remain independent; overlapping category wording is omitted.
    assert {candidate.mechanic_id for candidate in improved} == {"A", "B"}


def test_category_improvement_is_retained_when_named_mechanic_covers_only_part_of_evidence():
    prior = pull(1, [failure("old-a", "A"), failure("old-other", None)])
    current = pull(2, [failure("new-a", "A"), failure("new-other", None)])
    progression = ProgressionComparator().compare([prior, current])
    progression = replace(progression, subjects=tuple(
        replace(subject, status=ProgressionStatus.IMPROVED)
        if subject.subject_id in ("mechanic:A", "category:avoidable_damage") else subject
        for subject in progression.subjects))
    result = CoachingSynthesizer().synthesize(current, progression, history=(prior,))
    improved = [candidate for candidate in result.candidates if candidate.kind == "improvement"]
    assert {candidate.progression_subject_ids[0] for candidate in improved} == {
        "mechanic:A", "category:avoidable_damage"}


def test_primary_ranking_uses_failure_rate_when_present_and_count_otherwise():
    from app.pull_coach.models import ProgressionDelta
    many = replace(failure("many", "A-many"), evidence=tuple(
        EvidenceReference(f"many-{i}", (f"many-event-{i}",)) for i in range(4)))
    few = replace(failure("few", "Z-few"), evidence=tuple(
        EvidenceReference(f"few-{i}", (f"few-event-{i}",)) for i in range(2)))
    current = pull(1, [many, few])
    progression = ProgressionComparator().compare([current])
    subjects = tuple(replace(subject, repeated=True) for subject in progression.subjects)
    rates = (ProgressionDelta("mechanic:A-many", None, None, 1, "failure_rate", 1.0, 0.1),
             ProgressionDelta("mechanic:Z-few", None, None, 1, "failure_rate", 1.0, 0.9))
    with_rates = replace(progression, subjects=subjects, deltas=rates)
    assert CoachingSynthesizer().synthesize(current, with_rates).public.primary_failure.mechanic_id == "Z-few"
    without_rates = replace(progression, subjects=subjects, deltas=())
    assert CoachingSynthesizer().synthesize(current, without_rates).public.primary_failure.mechanic_id == "A-many"
    mixed_rates = replace(progression, deltas=(
        ProgressionDelta("mechanic:A-many", None, None, 1, "failure_rate", 1.0, 0.9),))
    # Mixed availability selects a common raw-count metric for every candidate.
    assert CoachingSynthesizer().synthesize(current, mixed_rates).public.primary_failure.mechanic_id == "A-many"


def test_exposed_clean_reappearance_on_kill_outranks_stable_repeated_failure():
    from app.pull_coach.models import ExposureState, MechanicExposure, PullState

    def scenario_pull(number, failures, opportunities=()):
        analysis = pull(number, failures)
        return replace(analysis, mechanic_exposures=tuple(
            MechanicExposure(mechanic, ExposureState.EXPOSED, count)
            for mechanic, count in opportunities))

    a1 = failure("a1", "A")
    b1 = replace(failure("b1", "B"), evidence=tuple(
        EvidenceReference(f"b1-{i}", (f"b1-event-{i}",)) for i in range(5)))
    a3 = failure("a3", "A")
    b3 = replace(failure("b3", "B"), evidence=tuple(
        EvidenceReference(f"b3-{i}", (f"b3-event-{i}",)) for i in range(5)))
    first = scenario_pull(1, [a1, b1], (("A", 1),))
    clean = scenario_pull(2, [replace(b1, finding_id="b2")], (("A", 1),))
    third = scenario_pull(3, [a3, b3], (("A", 1),))
    third = replace(third, pull=replace(third.pull, state=PullState.KILL, boss_percent=0))
    progression = ProgressionComparator().compare([first, clean, third])
    assert progression.pull_result == ProgressionStatus.IMPROVED
    assert next(subject for subject in progression.subjects if subject.subject_id == "mechanic:A").status == ProgressionStatus.REGRESSED
    assert next(subject for subject in progression.subjects if subject.subject_id == "mechanic:B").status == ProgressionStatus.STABLE
    coaching = CoachingSynthesizer().synthesize(third, progression, history=(first, clean))
    assert coaching.public.primary_failure.mechanic_id == "A"
