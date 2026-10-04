from types import SimpleNamespace

import pytest

from app.pull_coach.history.catalog import EncounterCatalogDiscovery, NoCatalogEncounters
from app.web_requests.warcraft_logs.errors import MalformedResponse


class FakeWCL:
    def __init__(self, fights):
        self.fights = fights
        self.references = []

    def report_data(self, reference):
        self.references.append(reference)
        return {"fights": self.fights}

    def ingest_fight(self, *args, **kwargs):
        raise AssertionError("catalog discovery must not ingest combat events")


class Registry:
    def for_encounter(self, encounter):
        return (object(),) if encounter.encounter_id == "100" else ()


def fight(fid, encounter=100, name="Zulu", start=None, end=2, kill=False, percent=None, **extra):
    result = {"id": fid, "encounterID": encounter, "name": name,
              "startTime": start if start is not None else fid * 10,
              "endTime": end, "kill": kill}
    if percent is not None:
        result["bossPercentage"] = percent
    result.update(extra)
    return result


def discover(fights, reference="ABC123"):
    wcl = FakeWCL(fights)
    catalog = EncounterCatalogDiscovery(wcl, Registry()).discover(reference)
    return catalog, wcl


def test_url_and_bare_code_parse_and_source_is_canonical():
    fight_rows = [fight(1)]
    first, wcl = discover(fight_rows, "https://www.warcraftlogs.com/reports/ABC123?token=secret")
    second, _ = discover(fight_rows, "ABC123")
    assert first.report_code == second.report_code == "ABC123"
    assert first.source_url == "https://www.warcraftlogs.com/reports/ABC123"
    assert wcl.references == ["ABC123"]
    assert "secret" not in first.source_url


def test_groups_completed_pulls_and_orders_encounters_by_first_appearance():
    catalog, _ = discover([
        fight(1, 200, "Alpha", start=10, kill=True),
        fight(2, 100, "Zulu", start=20, percent=60.39),
        fight(3, 100, "Zulu", start=30, percent=2.98),
        fight(4, 100, "Zulu", start=40, kill=True, percent=0.01),
        fight(5, 0, "Trash", start=50),
    ])
    assert [(e.encounter_id, e.name) for e in catalog.encounters] == [("200", "Alpha"), ("100", "Zulu")]
    zulu = catalog.encounters[1]
    assert (zulu.fight_ids, zulu.pull_count, zulu.has_kill, zulu.latest_fight_id) == (("2", "3", "4"), 3, True, "4")
    assert zulu.best_boss_percent == 0.01
    assert zulu.mechanics_supported is True


def test_wipe_only_percent_validation_eligibility_and_equal_timestamp_order():
    catalog, _ = discover([
        fight(3, 300, "Beta", start=10, percent="bad"),
        fight(2, 300, "Beta", start=10, percent=True),
        fight(1, 300, "Beta", start=10, percent=100),
        fight(4, 300, "Beta", start=40, end=40, inProgress=True),
        fight(5, 300, "Beta", start=50, end=None),
        fight(6, "bad", "Trash", start=60),
        fight(7, -2, "Trash", start=70),
        {"id": 8, "name": "No encounter", "startTime": 80, "endTime": 90},
    ])
    beta = catalog.encounters[0]
    assert beta.fight_ids == ("1", "2", "3")
    assert beta.has_kill is False
    assert beta.best_boss_percent == 100
    assert beta.mechanics_supported is False


def test_one_boss_catalog_and_empty_catalog_error():
    catalog, _ = discover([fight(1)])
    assert len(catalog.encounters) == 1
    assert catalog.encounters[0].first_start_timestamp == 10
    assert catalog.encounters[0].latest_start_timestamp == 10
    with pytest.raises(NoCatalogEncounters):
        discover([fight(2, 0), fight(3, 101, end=None)])


def test_all_invalid_percentages_yield_none():
    catalog, _ = discover([fight(1, percent="1.2"), fight(2, percent=float("nan"))])
    assert catalog.encounters[0].best_boss_percent is None


@pytest.mark.parametrize("encounter_id", [True, 1.5, 0, -1, "bad"])
def test_malformed_and_nonpositive_encounter_ids_are_excluded(encounter_id):
    with pytest.raises(NoCatalogEncounters):
        discover([fight(1, encounter_id)])


def test_numeric_string_encounter_ids_are_canonicalized_for_grouping_and_lookup():
    catalog, _ = discover([fight(1, "00100")])
    entry = catalog.encounters[0]
    assert entry.encounter_id == "100"
    assert entry.mechanics_supported is True


@pytest.mark.parametrize("fights", [None, {"id": 1}])
def test_malformed_fights_collection_raises_typed_provider_error(fights):
    class BadReport(FakeWCL):
        def report_data(self, reference):
            return {"fights": fights}

    with pytest.raises(MalformedResponse):
        EncounterCatalogDiscovery(BadReport([]), Registry()).discover("ABC123")


def test_eligible_fight_missing_required_metadata_raises_typed_provider_error():
    with pytest.raises(MalformedResponse):
        discover([{"encounterID": 100, "endTime": 200}])
