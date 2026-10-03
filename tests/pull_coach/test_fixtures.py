import json
import ast
from pathlib import Path

import pytest

from app.pull_coach.fixtures import (
    FixtureSchemaError, UnsupportedFixtureVersion, load_pull_fixture,
    load_raid_night, load_raid_night_prefix,
)
from app.pull_coach.models import (
    EventType, EvidenceReference, Finding, MechanicObservation, NormalizedEvent,
)

FIXTURES = Path(__file__).parents[2] / "app/pull_coach/fixtures/example"


def test_representative_fixture_loads_typed_domain_objects():
    pull = load_pull_fixture(FIXTURES / "pull-1.json")
    assert pull.pull.report.report_code == "EXAMPLE"
    assert pull.actors[0].name == "Sampleplayer"
    assert pull.events[0].event_type is EventType.DAMAGE
    assert pull.observations[0].mechanic_id == "example-blast"
    assert pull.findings[0].evidence[0].event_ids == ("event-1",)


def test_manifest_preserves_chronological_order():
    night = load_raid_night(FIXTURES / "raid-night.json")
    assert [pull.pull.pull_number for pull in night.pulls] == [1, 2]


def test_prefix_does_not_read_later_pull_payload(tmp_path):
    source = FIXTURES / "raid-night.json"
    manifest = json.loads(source.read_text())
    for entry in manifest["pulls"]:
        (tmp_path / entry["fixture"]).write_text((source.parent / entry["fixture"]).read_text())
    (tmp_path / "pull-2.json").write_text("not json")
    (tmp_path / "raid-night.json").write_text(json.dumps(manifest))
    prefix = load_raid_night_prefix(tmp_path / "raid-night.json", through_pull=1)
    assert [pull.pull.pull_number for pull in prefix.pulls] == [1]
    assert prefix.assertions is None


def test_prefix_does_not_validate_later_manifest_entries(tmp_path):
    source = FIXTURES / "raid-night.json"
    manifest = json.loads(source.read_text())
    manifest["pulls"][1].pop("fixture")
    (tmp_path / "pull-1.json").write_text((source.parent / "pull-1.json").read_text())
    (tmp_path / "raid-night.json").write_text(json.dumps(manifest))

    prefix = load_raid_night_prefix(tmp_path / "raid-night.json", through_pull=1)

    assert [pull.pull.pull_number for pull in prefix.pulls] == [1]


def test_missing_required_field_fails_clearly(tmp_path):
    data = json.loads((FIXTURES / "pull-1.json").read_text())
    del data["events"]
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(data))
    with pytest.raises(FixtureSchemaError, match="events"):
        load_pull_fixture(path)


def test_unsupported_version_fails_clearly(tmp_path):
    data = json.loads((FIXTURES / "pull-1.json").read_text())
    data["schema_version"] = 99
    path = tmp_path / "future.json"
    path.write_text(json.dumps(data))
    with pytest.raises(UnsupportedFixtureVersion, match="schema_version"):
        load_pull_fixture(path)


def test_findings_cannot_be_created_without_evidence():
    with pytest.raises(ValueError, match="evidence"):
        Finding("unsupported", "other", "low", {}, ())


def test_evidence_reference_must_identify_evidence_or_event():
    with pytest.raises(ValueError, match="identify"):
        EvidenceReference("", ())


def test_finding_and_observation_reject_empty_evidence_references():
    with pytest.raises(ValueError, match="evidence"):
        Finding("unsupported", "other", "low", {}, ())
    with pytest.raises(ValueError, match="evidence"):
        MechanicObservation("obs", "mechanic", 0, (), ())
    finding = Finding("supported", "other", "low", {}, (EvidenceReference("", ("event-1",)),))
    assert finding.evidence[0].event_ids == ("event-1",)


def test_normalized_event_requires_evidence_identifier():
    with pytest.raises(TypeError):
        NormalizedEvent(timestamp=1, event_type=EventType.DAMAGE)
    with pytest.raises(ValueError, match="evidence_id"):
        NormalizedEvent(timestamp=1, event_type=EventType.DAMAGE, evidence_id=" ")


def test_domain_contract_modules_have_no_infrastructure_imports():
    source = Path(__file__).parents[2] / "app/pull_coach/models/contracts.py"
    tree = ast.parse(source.read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imported.isdisjoint({"discord", "sqlalchemy", "requests", "warcraft_logs"})
