import json
from argparse import Namespace
from pathlib import Path

import pytest

from app.pull_coach.demo import _stages, replay, snapshot
from app.pull_coach.coaching import CoachingProviderError, CoachingReplayStage, CoachingSynthesizer
from app.pull_coach.replay import ReplayRunner
from app.web_requests.warcraft_logs import WCLSnapshot


ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "tests/replay/pull-coach-demo.json"
MECHANICS = ROOT / "app/pull_coach/mechanics/definitions/reference_analysis.json"


def test_reference_demo_runs_full_pipeline_with_grounded_coaching_and_prefix_invariance(tmp_path):
    stages = _stages(MECHANICS, MANIFEST)
    runner = ReplayRunner(stages=stages)
    prefix = runner.run(MANIFEST, through_pull=2)
    full = runner.run(MANIFEST)
    repeated = runner.run(MANIFEST)

    assert [set(pull.stages) for pull in full.pulls] == [
        {"analysis", "progression", "coaching", "discord"}
    ] * 3
    assert full.canonical_json() == repeated.canonical_json()
    for stage in ("analysis", "progression", "coaching", "discord"):
        assert [pull.stages[stage] for pull in prefix.pulls] == [
            pull.stages[stage] for pull in full.pulls[:2]
        ]

    first, second, third = full.pulls
    coaching = first.stages["coaching"]
    assert coaching.metadata.status == "fallback_no_provider"
    assert coaching.public.primary_failure and "Avoidable Blast" in coaching.public.primary_failure.text
    assert first.stages["discord"].embed.fields
    assert second.stages["progression"].subjects
    assert any(subject.status.value in {"resolved", "improved"}
               for subject in second.stages["progression"].subjects)
    assert any(subject.status.value in {"stabilized", "stable"}
               for subject in third.stages["progression"].subjects)
    assert any(subject.status.value == "newly_observed"
               for subject in third.stages["progression"].subjects)

    for pull_index, pull in enumerate(full.pulls):
        findings = {finding.finding_id: finding for prior in full.pulls[:pull_index + 1]
                    for finding in prior.stages["analysis"].findings}
        public = pull.stages["coaching"].public
        candidates = ([public.primary_failure] if public.primary_failure else [])
        candidates += list(public.improvements + public.dps_actions + public.healer_actions +
                           public.tank_actions + public.raid_actions + public.next_pull_priorities)
        rendered = pull.stages["discord"].embed
        for candidate in candidates:
            assert candidate.finding_ids
            assert all(finding_id in findings and findings[finding_id].evidence
                       for finding_id in candidate.finding_ids)
            assert all(evidence.event_ids for finding_id in candidate.finding_ids
                       for evidence in findings[finding_id].evidence)
            assert candidate.text in rendered.description or any(
                candidate.text in field.value for field in rendered.fields)


def test_demo_cli_writes_human_or_canonical_json(tmp_path, capsys):
    human_path, json_path = tmp_path / "raid.txt", tmp_path / "raid.json"
    for fmt, path in (("human", human_path), ("json", json_path)):
        replay(Namespace(manifest=str(MANIFEST), mechanics=str(MECHANICS), speed="max",
                         through_pull=None, format=fmt, output=str(path), baseline=None,
                         update_baseline=False))
    assert "Avoidable Blast was hit" in human_path.read_text()
    data = json.loads(json_path.read_text())
    assert set(data["pulls"][0]["stages"]) == {"analysis", "progression", "coaching", "discord"}
    assert capsys.readouterr().out == ""


def test_demo_cli_baseline_exit_status_and_human_regression_status(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    result = ReplayRunner(stages=_stages(MECHANICS, MANIFEST)).run(MANIFEST)
    baseline.write_text(result.canonical_json() + "\n")
    args = Namespace(manifest=str(MANIFEST), mechanics=str(MECHANICS), speed="max",
                     through_pull=None, format="human", output=None, baseline=str(baseline),
                     update_baseline=False)
    assert replay(args) == 0
    assert "Baseline: PASS" in capsys.readouterr().out
    baseline.write_text("{}\n")
    assert replay(args) == 1
    assert "Baseline: CHANGED" in capsys.readouterr().out


def test_full_pipeline_falls_back_when_optional_provider_fails():
    stages = _stages(MECHANICS, MANIFEST)

    class FailedProvider:
        def select(self, value, prompt):
            raise CoachingProviderError("provider unavailable")

    stages[2] = CoachingReplayStage(CoachingSynthesizer(provider=FailedProvider()),
                                    stages[2].mechanic_labels)
    result = ReplayRunner(stages=stages).run(MANIFEST, through_pull=1)
    pull = result.pulls[0]
    assert pull.stages["analysis"].findings
    assert pull.stages["progression"]
    assert pull.stages["coaching"].metadata.status == "fallback_provider_error"
    assert pull.stages["coaching"].public.primary_failure.finding_ids
    assert pull.stages["discord"].embed.fields


def test_snapshot_command_uses_snapshot_api_combines_fights_and_writes_manifest(monkeypatch, tmp_path):
    report = {"fights": [
        {"id": 2, "encounterID": 42, "startTime": 200, "endTime": 250, "inProgress": False},
        {"id": 1, "encounterID": 42, "startTime": 100, "endTime": 150, "inProgress": False},
    ]}
    calls = []

    class Client:
        def report_data(self, reference): return report
        def snapshot(self, reference, fight_id):
            calls.append((reference, fight_id))
            return WCLSnapshot(report, {fight_id: [{"data": [{"fight": fight_id}]}]})

    monkeypatch.setattr("app.pull_coach.demo.WCLClient", Client)
    output, manifest = tmp_path / "private.json", tmp_path / "run.json"
    snapshot(Namespace(reference="https://classic.warcraftlogs.com/reports/ABC", fight=[2, 1],
                       output=str(output), manifest=str(manifest)))
    saved = WCLSnapshot.load(output)
    assert calls == [("ABC", 2), ("ABC", 1)]
    assert set(saved.event_pages) == {1, 2}
    doc = json.loads(manifest.read_text())
    assert doc["encounters"] == [{"encounter_id": "42", "fight_ids": ["1", "2"]}]
    assert doc["snapshot"] == "private.json"
    assert "secret" not in output.read_text().lower()


def test_snapshot_rejects_multiple_encounters_before_event_fetch(monkeypatch, tmp_path):
    report = {"fights": [
        {"id": 1, "encounterID": 42, "startTime": 100, "endTime": 150, "inProgress": False},
        {"id": 2, "encounterID": 43, "startTime": 200, "endTime": 250, "inProgress": False},
    ]}
    calls = []
    class Client:
        def report_data(self, reference): return report
        def snapshot(self, reference, fight_id): calls.append(fight_id)
    monkeypatch.setattr("app.pull_coach.demo.WCLClient", Client)
    with pytest.raises(ValueError, match="exactly one encounter"):
        snapshot(Namespace(reference="ABC", fight=[1, 2], output=str(tmp_path / "out"), manifest=None))
    assert calls == []


def test_missing_and_invalid_mechanics_fail_clearly(tmp_path):
    manifest = json.loads(MANIFEST.read_text())
    manifest["encounters"] = [{"encounter_id": "999", "fight_ids": [12]}]
    custom_manifest = tmp_path / "manifest.json"
    manifest["snapshot"] = str(ROOT / "tests/fixtures/warcraft_logs/replay_snapshot.json")
    custom_manifest.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="No Pull Coach mechanic definitions exist for encounter"):
        _stages(MECHANICS, custom_manifest)

    malformed = tmp_path / "bad-mechanics.json"
    malformed.write_text('{"schema_version": 99}')
    with pytest.raises(ValueError, match="unsupported"):
        _stages(malformed, MANIFEST)
