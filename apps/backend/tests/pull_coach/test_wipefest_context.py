import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.pull_coach.wipefest_context import build_fight_coaching_context, build_player_coaching_context

FIXTURE = Path(__file__).parents[1] / "fixtures/wipefest/reference_fight.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def snapshot(payload):
    return SimpleNamespace(id=1, provider="wipefest", report_code="j8wDLpCTaqhB7M1x", fight_id="10", group_id="1507", payload=payload)


def test_raid_context_is_compact_and_whole_fight_only(snapshot):
    context = build_fight_coaching_context(snapshot)
    assert all(i["identity"]["interval"]["unit"] == "EntireFight" for i in context["insights"])
    assert all("data-component-data" not in str(i) for i in context["insights"])
    assert len(json.dumps(context)) < len(json.dumps(snapshot.payload)) * .1
    assert context == json.loads((FIXTURE.parent / "reference_raid_context.json").read_text())


def test_player_context_uses_entire_fight_summary_and_interval_identity(snapshot):
    context = build_player_coaching_context(snapshot, player_id=10)
    assert context["player"]["name"] == "Aleannora"
    assert context["evaluation"] == {"totalValue": 54.0, "totalBonus": 1.0, "fightDurationFractionUntilFirstDeath": 1.0}
    assert all(v["interval"]["unit"] == "EntireFight" for v in context["playerValues"])
    assert all(i["identity"]["interval"]["unit"] == "EntireFight" for i in context["insights"])
    assert "fights" not in json.dumps(context)
    assert context == json.loads((FIXTURE.parent / "reference_player_context.json").read_text())


def test_player_evidence_always_has_matching_insight_metadata(snapshot):
    context = build_player_coaching_context(snapshot, player_id=10)
    evidence_ids = {e["insight"] for e in context["playerEvidence"]}
    metadata_ids = {f"{i['identity']['group']}:{i['identity']['id']}" for i in context["insights"]}
    assert evidence_ids <= metadata_ids


def test_character_id_lookup_matches_actor_id(snapshot):
    by_actor = build_player_coaching_context(snapshot, player_id=10)
    by_character = build_player_coaching_context(snapshot, player_id=99487903)
    assert by_actor == by_character


def test_values_keep_compact_player_evidence_and_exclude_rendering_data(snapshot):
    insight = snapshot.payload["insights"][0]
    insight["values"] = {"totalHits": 26, "timestamps": [1, float("inf")], "fights": [{"id": 1}],
                          "playersAndDurationsOverThreshold": [{"player": {"id": 7, "guid": 99488003, "name": "Deego", "fights": [{"id": 1}]}, "duration": 9434}],
                          "timeline": [1], "url": "https://example.test"}
    context = build_fight_coaching_context(snapshot)
    value = context["insights"][0]["values"]
    assert value == {"totalHits": 26, "timestamps": [1], "players": [{"id": 7, "guid": 99488003, "name": "Deego", "duration": 9434}]}
    player = build_player_coaching_context(snapshot, player_id=7)
    assert {"insight": f"{insight['group']}:{insight['id']}", "duration": 9434} in player["playerEvidence"]


def test_values_merge_player_records_across_collections(snapshot):
    values = snapshot.payload["insights"][0]["values"]
    person = {"id": 10, "guid": 99487903, "name": "Aleannora"}
    values["playersAndFrequencies"] = [{"player": person, "frequency": 22}]
    values["playersAndDamages"] = [{"player": person, "damage": 812343}]
    values["playersAndDurationsOverThreshold"] = [{"player": person, "duration": 9434}]
    context = build_fight_coaching_context(snapshot)
    assert context["insights"][0]["values"]["players"] == [
        {"id": 10, "guid": 99487903, "name": "Aleannora", "frequency": 22, "damage": 812343, "duration": 9434}
    ]


def test_context_defaults_show_true_but_excludes_explicit_hidden_and_other_intervals(snapshot):
    insights = snapshot.payload["insights"]
    original = len(build_fight_coaching_context(snapshot)["insights"])
    hidden = dict(insights[0]); hidden["show"] = False
    nonwhole = dict(insights[0]); nonwhole["interval"] = {"unit": "Death", "startUnit": 1, "endUnit": 2}
    del insights[0]["show"]
    insights.extend([hidden, nonwhole])
    assert len(build_fight_coaching_context(snapshot)["insights"]) == original


def test_noisy_nested_fields_are_excluded(snapshot):
    insight = snapshot.payload["insights"][0]
    insight["values"]["playersAndFrequencies"][0]["player"]["fights"].append({"id": 999})
    context = build_fight_coaching_context(snapshot)
    rendered = json.dumps(context)
    assert "fights" not in rendered and "data-component-data" not in rendered
    assert len(rendered) < len(json.dumps(snapshot.payload)) * .1


def test_player_metadata_match_includes_complete_interval_identity(snapshot):
    original = next(i for i in snapshot.payload["insights"] if i["group"] == "raidwc" and i["id"] == "3")
    duplicate = dict(original)
    duplicate["interval"] = {**original["interval"], "startTimestamp": 123}
    snapshot.payload["insights"].append(duplicate)
    context = build_player_coaching_context(snapshot, player_id=10)
    matches = [i for i in context["insights"] if i["identity"]["group"] == "raidwc" and i["identity"]["id"] == "3"]
    assert len(matches) == 1
    assert matches[0]["identity"]["interval"]["startTimestamp"] == original["interval"]["startTimestamp"]


def test_missing_player_is_reported(snapshot):
    with pytest.raises(ValueError, match="not present"):
        build_player_coaching_context(snapshot, player_id=99999)
