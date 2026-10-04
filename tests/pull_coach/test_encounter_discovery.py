import json
import math

import pytest

from app.pull_coach.history.discovery import EncounterDiscoveryService, NoCompletedEncounterPulls
from app.pull_coach.mechanics.store import DirectoryMechanicsStore
from app.pull_coach.models import ActorType, EventType, discovery_to_json
from app.web_requests.warcraft_logs.errors import MalformedResponse, RateLimitError


class FakeClient:
    def __init__(self):
        self.requested = []
        self.report = {"code": "private-code", "fights": [
            {"id": 3, "encounterID": "10", "name": "Durumu", "startTime": 300, "endTime": 400, "inProgress": False, "kill": False},
            {"id": 1, "encounterID": 10, "name": "Durumu", "startTime": 100, "endTime": 200, "inProgress": False, "kill": False},
            {"id": 4, "encounterID": 10, "name": "Durumu", "startTime": 500, "endTime": None, "inProgress": True, "kill": False},
            {"id": 5, "encounterID": 11, "name": "Other", "startTime": 500, "endTime": 600, "inProgress": False, "kill": True},
        ], "masterData": {"actors": [{"id": 1, "type": "Player", "name": "Private Name"},
            {"id": 2, "type": "NPC", "name": "Boss"}], "abilities": []}}

    def report_data(self, ref):
        assert ref == "private-code"
        return self.report

    def _event_pages(self, code, fight):
        self.requested.append(fight["id"])
        ability = "140495" if fight["id"] == 1 else 140495
        return [{"data": [
            {"type": "damage", "timestamp": fight["startTime"] + 10, "abilityGameID": ability,
             "ability": {"name": "Lingering Gaze"}, "sourceID": 2, "targetID": 1, "amount": 50},
            {"type": "cast", "timestamp": fight["startTime"] + 20, "abilityGameID": 134755,
             "ability": {"name": "Eye Sore"}, "sourceID": 2, "targetID": 1},
            {"type": "death", "timestamp": fight["startTime"] + 30, "targetID": 1},
        ]}]


def test_discovery_selects_completed_encounter_and_emits_stable_private_artifact():
    client = FakeClient()
    service = EncounterDiscoveryService(client)
    artifact = service.discover("https://www.warcraftlogs.com/reports/private-code", "010")
    assert client.requested == [1, 3]
    gaze = next(candidate for candidate in artifact.candidates if candidate.ability_id == "140495")
    assert gaze.event_types == (EventType.DAMAGE,)
    assert gaze.source_actor_type_counts == ((ActorType.NPC, 2),)
    assert gaze.target_actor_type_counts == ((ActorType.PLAYER, 2),)
    assert gaze.fight_occurrence_counts == (("1", 1), ("3", 1))
    assert gaze.damage_total == 100
    assert (gaze.first_timestamp, gaze.last_timestamp) == (110, 310)
    assert gaze.death_window_observations == 2
    document = discovery_to_json(artifact)
    assert "Private Name" not in document and "private-code" not in document
    assert "player_name" not in document and "avoidable" not in document and "severity" not in document
    assert document == discovery_to_json(service.discover("private-code", 10))
    assert json.loads(document)["provenance"][0]["source_fingerprint"]


def test_durumu_shaped_candidates_have_factual_per_fight_observations():
    artifact = EncounterDiscoveryService(FakeClient()).discover("private-code", 10)
    by_id = {candidate.ability_id: candidate for candidate in artifact.candidates}
    assert by_id["140495"].ability_name == "Lingering Gaze"
    assert by_id["134755"].ability_name == "Eye Sore"
    assert by_id["134755"].fight_occurrence_counts == (("1", 1), ("3", 1))
    assert not any(word in discovery_to_json(artifact) for word in ("positioning", "avoidable_damage", "failure_category"))


def test_missing_completed_pulls_is_expected_error():
    client = FakeClient()
    client.report["fights"] = [client.report["fights"][2]]
    with pytest.raises(NoCompletedEncounterPulls):
        EncounterDiscoveryService(client).discover("private-code", 10)


def test_malformed_events_and_transport_errors_remain_typed():
    class Malformed(FakeClient):
        def _event_pages(self, code, fight):
            return [{"data": [{"type": "damage"}]}]
    with pytest.raises(MalformedResponse):
        EncounterDiscoveryService(Malformed()).discover("private-code", 10)

    class Limited(FakeClient):
        def report_data(self, ref):
            raise RateLimitError("limited")
    with pytest.raises(RateLimitError):
        EncounterDiscoveryService(Limited()).discover("private-code", 10)


@pytest.mark.parametrize("master_data", [
    {"actors": ["malformed"], "abilities": []},
    {"actors": [], "abilities": ["malformed"]},
])
def test_malformed_nested_master_data_is_typed_response(master_data):
    client = FakeClient()
    client.report["masterData"] = master_data
    with pytest.raises(MalformedResponse):
        EncounterDiscoveryService(client).discover("private-code", 10)


def test_cast_only_candidate_has_no_damage_total():
    class CastOnly(FakeClient):
        def _event_pages(self, code, fight):
            return [{"data": [{"type": "cast", "timestamp": fight["startTime"] + 20,
                               "abilityGameID": 134755, "ability": {"name": "Eye Sore"},
                               "sourceID": 2, "targetID": 1}]}]

    artifact = EncounterDiscoveryService(CastOnly()).discover("private-code", 10)
    candidate = artifact.candidates[0]
    assert candidate.event_types == (EventType.CAST,)
    assert candidate.damage_total is None


def test_nested_guid_death_window_and_name_only_abilities_keep_stable_identity():
    class NestedGuid(FakeClient):
        def _event_pages(self, code, fight):
            return [{"data": [
                {"type": "damage", "timestamp": fight["startTime"] + 10,
                 "ability": {"guid": "00999", "name": "Nested Hit"}, "sourceID": 2, "targetID": 1, "amount": 8},
                {"type": "damage", "timestamp": fight["startTime"] + 20,
                 "ability": {"name": "Alpha"}, "sourceID": 2, "targetID": 1, "amount": 2},
                {"type": "damage", "timestamp": fight["startTime"] + 21,
                 "ability": {"name": "Beta"}, "sourceID": 2, "targetID": 1, "amount": 3},
                {"type": "death", "timestamp": fight["startTime"] + 30, "targetID": 1},
            ]}]

    artifact = EncounterDiscoveryService(NestedGuid()).discover("private-code", 10)
    candidates = {item.ability_id: item for item in artifact.candidates}
    assert candidates["999"].death_window_observations == 2
    assert candidates["999"].first_timestamp == 110
    assert "name:alpha" in candidates and "name:beta" in candidates
    assert candidates["name:alpha"].first_timestamp != candidates["name:beta"].first_timestamp


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_nonfinite_event_timestamps_are_typed_malformed_responses(bad_value):
    class BadTimestamp(FakeClient):
        def _event_pages(self, code, fight):
            return [{"data": [{"type": "damage", "timestamp": bad_value, "abilityGameID": 3}]}]
    with pytest.raises(MalformedResponse):
        EncounterDiscoveryService(BadTimestamp()).discover("private-code", 10)


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_nonfinite_damage_values_are_typed_malformed_responses(bad_value):
    class BadDamage(FakeClient):
        def _event_pages(self, code, fight):
            return [{"data": [{"type": "damage", "timestamp": fight["startTime"] + 10,
                               "abilityGameID": 140495, "amount": bad_value}]}]

    with pytest.raises(MalformedResponse):
        EncounterDiscoveryService(BadDamage()).discover("private-code", 10)


def test_nonfinite_fight_times_and_nonboolean_kill_are_typed_malformed_responses():
    for mutation in (
        lambda fight: fight.update(startTime=math.inf),
        lambda fight: fight.update(kill=1),
    ):
        client = FakeClient()
        mutation(client.report["fights"][0])
        with pytest.raises(MalformedResponse):
            EncounterDiscoveryService(client).discover("private-code", 10)


def test_discovery_persists_through_dal61_directory_store(tmp_path):
    store = DirectoryMechanicsStore(tmp_path)
    result = EncounterDiscoveryService(FakeClient(), store).discover("private-code", 10)
    saved = list((tmp_path / "discovered").glob("*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text()) == json.loads(discovery_to_json(result))
