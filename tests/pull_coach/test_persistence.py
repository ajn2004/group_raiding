from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.models.pull_coach import (
    CoachingOutput, PullCoachAnalysis, PullCoachEvidence, PullCoachFinding,
    PullCoachPull, PullCoachReport,
)
from app.pull_coach.models.contracts import (
    AnalysisMetadata, EncounterIdentity, EvidenceReference, Finding,
    FindingCategory, PullAnalysis, PullIdentity, PullState, RaidReportIdentity,
    Role, Severity, SourceIdentity, SummaryMetrics,
)
from app.pull_coach.persistence.repository import PullCoachRepository


def analysis(number=1, *, version="1", scope_report="R1", fight=None):
    report = RaidReportIdentity(SourceIdentity("wcl", "source"), scope_report)
    pull = PullIdentity(
        report, EncounterIdentity("boss-1", "Boss"), fight or f"fight-{number}",
        number, number * 1000, number * 1000 + 500, PullState.WIPE, 42.5,
    )
    finding = Finding(
        f"finding-{number}", FindingCategory.MECHANIC, Severity.HIGH,
        {"amount": 123, "ability": "fire"},
        (EvidenceReference(f"evidence-{number}", (f"event-{number}",), "hit"),),
        ("actor-1",), (Role.DAMAGE,), "fire-breath", (),
    )
    return PullAnalysis(pull, (finding,), (), SummaryMetrics({"deaths": number}),
                        AnalysisMetadata("analyzer", version))


def repository():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_persists_structured_analysis_and_is_idempotent_with_scope_isolation():
    engine = repository()
    with Session(engine) as session:
        repo = PullCoachRepository(session)
        one = analysis()
        pull = repo.upsert_pull(one.pull)
        assert repo.upsert_pull(one.pull) == one.pull
        assert (pull.encounter.encounter_id, pull.fight_id, pull.pull_number) == (
            "boss-1", "fight-1", 1,
        )
        assert (pull.start_timestamp, pull.end_timestamp, pull.state, pull.boss_percent) == (
            1000, 1500, "wipe", 42.5,
        )
        run = repo.save_analysis(one)
        assert repo.save_analysis(one).id == run.id
        replay = analysis(scope_report="R1")
        replay_run = repo.save_analysis(replay, scope="replay:night")
        assert repo.save_analysis(replay, scope="replay:night").id == replay_run.id
        repo.upsert_pull(analysis(scope_report="R1").pull, scope="live")
        assert session.scalar(select(func.count()).select_from(PullCoachReport)) == 2
        assert session.scalar(select(func.count()).select_from(PullCoachPull)) == 2
        assert session.scalar(select(func.count()).select_from(PullCoachAnalysis)) == 2
        finding = session.scalar(select(PullCoachFinding))
        evidence = session.scalar(select(PullCoachEvidence))
        assert finding.fact == {"amount": 123, "ability": "fire"}
        assert finding.actor_ids == ["actor-1"] and finding.roles == ["damage"]
        assert finding.related_finding_ids == []
        assert evidence.evidence_id == "evidence-1"
        assert evidence.event_ids == ["event-1"]
        assert run.summary == {"deaths": 1}
        assert (run.analyzer_name, run.analyzer_version) == ("analyzer", "1")
        queried_pull, provenance, queried_finding = repo.list_findings_for_encounter(
            "boss-1", analyzer_name="analyzer", analyzer_version="1",
            report=one.pull.report,
        )[0]
        assert queried_pull == one.pull
        assert queried_finding == one.findings[0]
        assert provenance.analyzer_name == "analyzer"
        assert provenance.analyzer_version == "1"
        assert len(provenance.result_fingerprint) == 64


def test_versions_coexist_and_encounter_query_is_chronological():
    engine = repository()
    with Session(engine) as session:
        repo = PullCoachRepository(session)
        for n in (3, 1, 2):
            item = analysis(n)
            repo.save_analysis(item)
        repo.save_analysis(analysis(1, version="2"))
        assert session.scalar(select(func.count()).select_from(PullCoachAnalysis)) == 4
        results = repo.list_findings_for_encounter(
            "boss-1", analyzer_name="analyzer", analyzer_version="2",
            report=analysis().pull.report,
        )
        assert [(pull.pull_number, provenance.analyzer_version, finding.finding_id)
                for pull, provenance, finding in results] == [(1, "2", "finding-1")]
        assert repo.list_findings_for_encounter(
            "boss-1", analyzer_name="analyzer", analyzer_version="1",
            report=analysis().pull.report,
        )[0][1].analyzer_version == "1"


def test_prefix_persistence_does_not_create_future_pulls():
    engine = repository()
    with Session(engine) as session:
        repo = PullCoachRepository(session)
        repo.upsert_pull(analysis(1).pull, scope="replay:night")
        repo.upsert_pull(analysis(2).pull, scope="replay:night")
        identity = analysis().pull.report
        assert [p.pull_number for p in repo.list_pulls(identity, scope="replay:night")] == [1, 2]
        first = repo.list_pulls(identity, scope="replay:night")[0]
        assert first == analysis(1).pull
        repo.upsert_pull(analysis(3).pull, scope="replay:night")
        assert first.pull_number == 1
        assert [p.pull_number for p in repo.list_pulls(identity, scope="replay:night")] == [1, 2, 3]


def test_report_queries_keep_provider_identity_qualified():
    engine = repository()
    with Session(engine) as session:
        repo = PullCoachRepository(session)
        wcl = analysis().pull
        other_report = RaidReportIdentity(SourceIdentity("other-provider", "source"), "R1")
        other_pull = replace(wcl, report=other_report, fight_id="other-fight")
        repo.upsert_pull(wcl)
        repo.upsert_pull(other_pull)
        assert repo.list_pulls(wcl.report) == [wcl]
        assert repo.list_pulls(other_report) == [other_pull]


def test_pull_upsert_allows_completion_but_rejects_identity_rewrites():
    engine = repository()
    with Session(engine) as session:
        repo = PullCoachRepository(session)
        original = analysis().pull
        repo.upsert_pull(original)
        completed = replace(original, encounter=EncounterIdentity("boss-1", "Renamed"),
                            end_timestamp=1800, state=PullState.KILL, boss_percent=0.0)
        assert repo.upsert_pull(completed) == completed
        with pytest.raises(ValueError, match="start_timestamp"):
            repo.upsert_pull(replace(completed, start_timestamp=999))
        with pytest.raises(ValueError, match="encounter_id"):
            repo.upsert_pull(replace(completed, encounter=EncounterIdentity("boss-2", "Other")))


def test_coaching_metadata_can_be_written_without_generator_dependency():
    engine = repository()
    with Session(engine) as session:
        run = PullCoachRepository(session).save_analysis(analysis())
        output = CoachingOutput(
            analysis_id=run.id, generator="provider", model="model-x",
            template_version="template-1", status="complete",
            metadata_json={"locale": "en"}, rendered_output="summary",
        )
        session.add(output)
        session.flush()
        assert session.get(CoachingOutput, output.id).metadata_json == {"locale": "en"}


def test_legacy_metadata_is_registered():
    assert {"players", "characters", "roles", "schedule"}.issubset(Base.metadata.tables)


def test_analyzer_healing_window_persists_without_duplicate_finding_ids():
    from app.pull_coach.analysis import PullAnalyzer
    from app.pull_coach.mechanics import registry_from_dict
    from app.pull_coach.models import Actor, EventType, NormalizedEvent

    pull = analysis().pull
    actors = (Actor("actor-1", "Actor", role=Role.DAMAGE),)
    registry = registry_from_dict({"schema_version": 1, "definitions": [{
        "mechanic_id": "pulse", "name": "Pulse",
        "encounter": {"encounter_id": "boss-1", "name": "Boss"},
        "event_types": ["damage"], "ability_ids": [20],
        "failure_category": "healing_check", "avoidable": False,
    }]})
    events = [NormalizedEvent(i, EventType.DAMAGE, f"pulse-{i}", "boss", "a",
                              ability_id=20, amount=10) for i in range(20)]
    result = PullAnalyzer(registry).analyze(pull, actors, events)
    assert len({finding.finding_id for finding in result.findings}) == len(result.findings)
    engine = repository()
    with Session(engine) as session:
        repo = PullCoachRepository(session)
        repo.save_analysis(result)
        assert session.scalar(select(func.count()).select_from(PullCoachFinding)) == len(result.findings)
