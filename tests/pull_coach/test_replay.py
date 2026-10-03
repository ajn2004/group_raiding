import json
from pathlib import Path

import pytest

from app.pull_coach.replay import ReplayRunner, UnsupportedReplayManifestVersion
from app.pull_coach.replay.runner import ReplaySession, ReplaySpeed


ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "tests/replay/example-night.json"


def test_three_fight_prefix_is_repeatable_and_stages_only_see_prefix():
    seen = []

    class Observer:
        name = "observer"

        def run(self, context):
            seen.append([pull.pull.fight_id for pull in context.history])
            return {"history_count": len(context.history), "boss_percent": context.current.pull.boss_percent}

    runner = ReplayRunner(stages=[Observer()])
    two = runner.run(MANIFEST, through_pull=2)
    three = runner.run(MANIFEST)
    assert ReplayRunner().run(MANIFEST).baseline_status == "pass"
    assert two.pulls == three.pulls[:2]
    assert seen == [["12"], ["12", "13"], ["12"], ["12", "13"], ["12", "13", "14"]]
    assert [p.ingestion.pull.pull_number for p in three.pulls] == [1, 2, 3]


def test_replay_analyzer_stage_consumes_current_ingestion():
    from app.pull_coach.analysis import PullAnalyzer
    from app.pull_coach.mechanics import load_mechanic_registry
    from app.pull_coach.models import PullAnalysis

    class AnalyzerStage:
        name = "analysis"

        def __init__(self):
            self.analyzer = PullAnalyzer(load_mechanic_registry(
                ROOT / "app/pull_coach/mechanics/definitions/reference_analysis.json"))

        def run(self, context):
            current = context.current
            return self.analyzer.analyze(current.pull, current.actors, current.events)

    result = ReplayRunner(stages=[AnalyzerStage()]).run(MANIFEST, through_pull=1)
    analysis = result.pulls[0].stages["analysis"]
    assert isinstance(analysis, PullAnalysis)
    assert analysis.pull == result.pulls[0].ingestion.pull


def test_selected_subset_keeps_source_pull_numbers_and_replay_sequence(tmp_path):
    manifest = json.loads(MANIFEST.read_text())
    manifest["baseline"] = None
    manifest["snapshot"] = str((ROOT / "tests/fixtures/warcraft_logs/replay_snapshot.json").resolve())
    manifest["encounters"][0]["fight_ids"] = [13, 14]
    manifest["assertions"] = None
    path = tmp_path / "subset.json"
    path.write_text(json.dumps(manifest))
    result = ReplayRunner().run(path)
    assert [p.sequence_number for p in result.pulls] == [1, 2]
    assert [p.pull_number for p in result.pulls] == [2, 3]


def test_stage_baseline_reports_changed_stage_and_human_status(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(ReplayRunner().run(MANIFEST).canonical_json())

    class Analysis:
        name = "analysis"
        def run(self, context):
            return {"version": "changed"}

    result = ReplayRunner(stages=[Analysis()]).run(MANIFEST, baseline=baseline)
    assert any(item.endswith(": analysis changed") for item in result.changes)
    assert "Pull 1 / fight 12   CHANGED\n  analysis" in result.human()
    assert "Pull 2 / fight 13   CHANGED" in result.human()


def test_stage_context_outputs_are_snapshots():
    retained = []

    class First:
        name = "first"
        def run(self, context):
            retained.append(context)
            return "first-output"

    class Second:
        name = "second"
        def run(self, context):
            assert context.current_stage_outputs == {"first": "first-output"}
            return "second-output"

    ReplayRunner(stages=[First(), Second()]).run(MANIFEST)
    assert all(context.current_stage_outputs == {} for context in retained)


def test_canonical_output_repeatable():
    runner = ReplayRunner()
    assert runner.run(MANIFEST).canonical_json() == runner.run(MANIFEST).canonical_json()


def test_unsupported_manifest_version_identifies_path_and_version(tmp_path):
    data = json.loads(MANIFEST.read_text())
    data["schema_version"] = 88
    path = tmp_path / "future.json"
    path.write_text(json.dumps(data))
    with pytest.raises(UnsupportedReplayManifestVersion, match="future.json.*88.*1"):
        ReplayRunner().run(path)


def test_short_prefix_does_not_ingest_future_fight(tmp_path):
    # Fight 14 is deliberately absent from the snapshot; prefix execution is still valid.
    data = json.loads((ROOT / "tests/fixtures/warcraft_logs/replay_snapshot.json").read_text())
    del data["event_pages"]["14"]
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(data))
    manifest = json.loads(MANIFEST.read_text())
    manifest["snapshot"] = str(snapshot)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    assert len(ReplayRunner().run(manifest_path, through_pull=2).pulls) == 2
    with pytest.raises(RuntimeError, match="fight 14.*pull 3.*stage ingestion"):
        ReplayRunner().run(manifest_path)


def test_optional_stage_and_baseline_behavior(tmp_path):
    runner = ReplayRunner()
    baseline = tmp_path / "expected.json"
    first = runner.run(MANIFEST)
    baseline.write_text(first.canonical_json() + "\n")
    assert runner.run(MANIFEST, baseline=baseline).baseline_status == "pass"
    before = baseline.read_text()
    assert runner.run(MANIFEST, baseline=baseline).baseline_status == "pass"
    assert baseline.read_text() == before
    assert all(not pull.stages for pull in first.pulls)

    class ChangedStage:
        name = "changed"

        def run(self, context):
            return {"pull": context.current.pull.pull_number}

    changed_runner = ReplayRunner(stages=[ChangedStage()])
    changed = changed_runner.run(MANIFEST, baseline=baseline)
    assert changed.baseline_status == "changed"
    assert baseline.read_text() == before
    changed_runner.run(MANIFEST, baseline=baseline, update_baseline=True)
    assert baseline.read_text() != before


def test_timing_modes_and_programmatic_step_are_lazy():
    delays = []
    runner = ReplayRunner(sleeper=delays.append)
    result = runner.run(MANIFEST, speed=ReplaySpeed.MAX)
    assert len(result.pulls) == 3
    assert delays == []
    runner.run(MANIFEST, speed=ReplaySpeed.NO_SLEEP)
    assert delays == []
    runner.run(MANIFEST, speed=ReplaySpeed.ORIGINAL)
    assert delays == [5.0, 5.0]
    original_ingest = runner.client.ingest_fight
    session = ReplaySession(runner, MANIFEST, through_pull=2)
    calls = []
    session.runner.client.ingest_fight = lambda *args: calls.append(args[-1]) or original_ingest(*args)
    # Preparation is lazy: no fight has been ingested before next().
    assert calls == []
    assert session.next().pull_number == 1
    assert calls == ["12"]
    assert session.next().pull_number == 2
    with pytest.raises(StopIteration):
        session.next()


def test_stages_receive_causal_outputs_and_encounter_scoped_history():
    observations = []

    class A:
        name = "analysis"
        def run(self, context):
            return context.sequence_number

    class B:
        name = "progression"
        def run(self, context):
            observations.append((context.sequence_number, dict(context.current_stage_outputs),
                                len(context.prior_pull_results), len(context.history)))
            return context.current_stage_outputs["analysis"]

    ReplayRunner(stages=[A(), B()]).run(MANIFEST)
    assert observations == [(1, {"analysis": 1}, 0, 1), (2, {"analysis": 2}, 1, 2),
                            (3, {"analysis": 3}, 2, 3)]


def test_stage_failure_has_replay_fight_pull_and_stage_context():
    class BrokenStage:
        name = "test-stage"

        def run(self, context):
            raise ValueError("fixture failure")

    with pytest.raises(RuntimeError, match="reference-example-night.*fight 12.*pull 1.*stage test-stage"):
        ReplayRunner(stages=[BrokenStage()]).run(MANIFEST)


def test_malformed_manifest_fails_with_manifest_context(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version": 1, "replay_id": "broken"}')
    with pytest.raises(ValueError, match="bad.json.*malformed replay manifest"):
        ReplayRunner().run(path)
