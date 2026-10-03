import json
from pathlib import Path
import pytest

from app.pull_coach.demo import main
from app.pull_coach.history.inspect import inspect_snapshot, render_human
from app.pull_coach.history.sanitize import sanitize_snapshot
from app.pull_coach.demo import _stages
from app.pull_coach.replay import ReplayRunner
from app.web_requests.warcraft_logs import WCLSnapshot


def sample():
    report={"code":"SECRETREPORT","fights":[{"id":4,"encounterID":9,"name":"Boss","startTime":100,"endTime":500,"kill":False,"bossPercentage":20}],
            "masterData":{"actors":[{"id":1,"name":"Alice","type":"Player","server":"PrivateRealm"},{"id":2,"name":"Boss","type":"NPC"},{"id":3,"name":"Add","type":"NPC"}],
                          "abilities":[{"gameID":10,"name":"Gaze"},{"gameID":11,"name":"Gaze"}]}}
    events=[{"timestamp":100,"type":"cast","abilityGameID":10,"sourceID":2,"targetID":1},
            {"timestamp":200,"type":"damage","abilityGameID":11,"sourceID":3,"targetID":1,"amount":50},
            {"timestamp":250,"type":"death","sourceID":1,"targetID":1}]
    return WCLSnapshot(report,{4:[{"data":events}]})


def test_inspector_reports_factual_variants_filters_and_bounded_deaths():
    result=inspect_snapshot(sample(),death_window_ms=60)
    assert [(a["ability_id"],a["name"],a["event_types"]) for a in result["abilities"]]==[("10","Gaze",{"cast":1}),("11","Gaze",{"damage":1})]
    assert result["abilities"][0]["source_actors"][0]["type"]=="NPC"
    assert result["abilities"][1]["targets"][0]["count"]==1
    assert len(result["deaths"][0]["damage_events"])==1
    assert inspect_snapshot(sample(),fight=99)["fights"]==[]
    assert inspect_snapshot(sample(),ability="10")["abilities"][0]["ability_id"]=="10"
    assert "failure" not in json.dumps(result).lower() and "avoidable" not in json.dumps(result).lower()
    assert render_human(result)==render_human(inspect_snapshot(sample(),death_window_ms=60))


def test_inspect_cli_is_offline_and_json_is_deterministic(tmp_path,monkeypatch,capsys):
    snapshot=tmp_path/"s.json"; sample().save(snapshot)
    manifest=tmp_path/"m.json"; manifest.write_text(json.dumps({"schema_version":1,"replay_id":"x","report_code":"SECRETREPORT","snapshot":"s.json","encounters":[{"encounter_id":"9","fight_ids":["4"]}]}))
    monkeypatch.setattr("app.pull_coach.demo.WCLClient",lambda: (_ for _ in ()).throw(AssertionError("network client used")))
    main(["inspect",str(manifest),"--format","json"]); first=capsys.readouterr().out
    main(["inspect",str(manifest),"--format","json"]); assert capsys.readouterr().out==first


def test_inspect_cli_is_scoped_to_manifest_fights(tmp_path, capsys):
    raw=sample()
    raw.report["fights"]=[{"id":i,"encounterID":9,"name":"Boss"} for i in range(1,59)]
    pages={4:[{"data":[{"timestamp":1,"type":"cast","abilityGameID":10,"sourceID":2}]}]}
    pages.update({i:[] for i in range(1,59)})
    raw=WCLSnapshot(raw.report,pages)
    snapshot=tmp_path/"s.json"; raw.save(snapshot)
    manifest=tmp_path/"m.json"; manifest.write_text(json.dumps({"schema_version":1,"replay_id":"replay-abc","report_code":"SECRETREPORT","snapshot":"s.json","encounters":[{"encounter_id":"9","fight_ids":["38","40","41"]}]}))
    main(["inspect",str(manifest),"--format","json"])
    data=json.loads(capsys.readouterr().out)
    assert [f["fight_id"] for f in data["fights"]]==[38,40,41]
    assert data["replay_identity"]=="replay-abc"
    with pytest.raises(SystemExit):
        main(["inspect",str(manifest),"--fight","20"])


def test_death_damage_is_scoped_to_the_dead_actor():
    raw=sample()
    raw=WCLSnapshot(raw.report,{4:[{"data":[
        {"timestamp":200,"type":"damage","targetID":1,"sourceID":2},
        {"timestamp":210,"type":"damage","targetID":2,"sourceID":3},
        {"timestamp":220,"type":"damage","targetID":3,"sourceID":2},
        {"timestamp":250,"type":"death","targetID":1},
    ]}]})
    result=inspect_snapshot(raw,death_window_ms=100)
    assert [e["target_id"] for e in result["deaths"][0]["damage_events"]]==[1]


def test_inspector_preserves_joint_event_type_and_source_variants():
    raw=sample()
    raw=WCLSnapshot(raw.report,{4:[{"data":[
        {"timestamp":1,"type":"cast","abilityGameID":10,"sourceID":2},
        {"timestamp":2,"type":"damage","abilityGameID":10,"sourceID":3},
    ]}]})
    ability=inspect_snapshot(raw)["abilities"][0]
    assert [(v["event_type"],v["source_actor_id"],v["count"]) for v in ability["variants"]]==[("cast","2",1),("damage","3",1)]
    text=render_human({**inspect_snapshot(raw),"abilities":[ability]})
    assert text.count("events=1")==2


def test_inspection_uses_manifest_order_and_displays_both_identities():
    raw=sample()
    raw.report["fights"]=[{"id":i,"encounterID":9,"name":"Boss"} for i in (38,40,41)]
    raw=WCLSnapshot(raw.report,{})
    result=inspect_snapshot(raw,fight_ids=["41","38","40"],replay_id="replay-abc")
    assert [fight["fight_id"] for fight in result["fights"]]==[41,38,40]
    assert "Report: SECRETREPORT · Replay: replay-abc" in render_human(result)


def test_sanitizer_is_deterministic_and_preserves_event_links_and_mechanics():
    original=sample(); pages=json.loads(json.dumps(original.event_pages)); pages["4"][0]["data"][0]["note"]="Alice SECRETREPORT PrivateRealm"
    raw=WCLSnapshot(original.report,pages)
    a=sanitize_snapshot(raw); b=sanitize_snapshot(raw)
    assert json.dumps(a.to_dict(),sort_keys=True)==json.dumps(b.to_dict(),sort_keys=True)
    encoded=json.dumps(a.to_dict())
    assert "Alice" not in encoded and "PrivateRealm" not in encoded and "SECRETREPORT" not in encoded
    assert "Player 001" in encoded
    assert a.report["fights"]==raw.report["fights"]
    assert a.event_pages!=raw.event_pages
    assert a.event_pages[4][0]["data"][0]["note"]=="Player 001 SANITIZED-HISTORICAL-FIXTURE Player 001"
    assert a.report["masterData"]["actors"][0]["name"]=="Player 001"


def test_sanitizer_replaces_identity_tokens_without_changing_semantic_substrings():
    original=sample()
    report=json.loads(json.dumps(original.report))
    report["masterData"]["actors"][0]["name"]="Fire"
    report["masterData"]["abilities"].append({"gameID":12,"name":"Wildfire Fireball"})
    pages=json.loads(json.dumps(original.event_pages))
    pages["4"][0]["data"][0]["note"]="Fire's Guardian; Wildfire; Fireball; Fire-PrivateRealm"
    clean=sanitize_snapshot(WCLSnapshot(report,pages))
    assert clean.report["masterData"]["abilities"][-1]["name"]=="Wildfire Fireball"
    assert clean.event_pages[4][0]["data"][0]["note"]=="Player 001's Guardian; Wildfire; Fireball; Player 001-Player 001"


def test_sanitize_cli_writes_replayable_sanitized_manifest(tmp_path):
    snapshot=tmp_path/"private.json"; sample().save(snapshot)
    manifest=tmp_path/"private.manifest.json"
    manifest.write_text(json.dumps({"schema_version":1,"replay_id":"SECRETREPORT-private","report_code":"SECRETREPORT","snapshot":"private.json","encounters":[{"encounter_id":"9","fight_ids":["4"]}]}))
    out=tmp_path/"clean.json"; out_manifest=tmp_path/"clean.manifest.json"
    main(["sanitize",str(manifest),"--output-snapshot",str(out),"--output-manifest",str(out_manifest)])
    loaded=WCLSnapshot.load(out); doc=json.loads(out_manifest.read_text())
    assert loaded.report["code"]==doc["report_code"]=="SANITIZED-HISTORICAL-FIXTURE"
    assert doc["replay_id"]=="sanitized-historical-fixture"
    assert "SECRETREPORT" not in out.read_text()+out_manifest.read_text()
    assert "Alice" not in out.read_text()+out_manifest.read_text()
    assert "PrivateRealm" not in out.read_text()+out_manifest.read_text()


def test_sanitize_preserves_assertions_and_drops_baseline(tmp_path):
    sample().save(tmp_path/"private.json")
    manifest=tmp_path/"private.manifest.json"
    manifest.write_text(json.dumps({"schema_version":1,"replay_id":"r","report_code":"SECRETREPORT",
        "snapshot":"private.json","baseline":"baseline.json","assertions":{"pull_count":1},
        "encounters":[{"encounter_id":"9","fight_ids":["4"]}]}))
    out=tmp_path/"clean.json"; out_manifest=tmp_path/"clean.manifest.json"
    from app.pull_coach.history.sanitize import sanitize_files
    sanitize_files(manifest,out,out_manifest)
    data=json.loads(out_manifest.read_text())
    assert data["assertions"]=={"pull_count":1}
    assert "baseline" not in data


def test_sanitized_snapshot_replay_preserves_analysis_progression_and_public_text(tmp_path):
    root=Path(__file__).parents[2]
    source_manifest=root/"tests/replay/pull-coach-demo.json"
    doc=json.loads(source_manifest.read_text())
    raw_snapshot=(source_manifest.parent/doc["snapshot"]).resolve()
    # Use a fixture-local private report/player identity while retaining the replay corpus.
    raw=WCLSnapshot.load(raw_snapshot)
    report=json.loads(json.dumps(raw.report)); report["code"]="PRIVATE-REPLAY-ID"
    report["masterData"]["actors"][0].update({"name":"Fixture Person","server":"Hidden Realm"})
    private_snapshot=tmp_path/"private.json"; WCLSnapshot(report,raw.event_pages).save(private_snapshot)
    manifest={**doc,"report_code":"PRIVATE-REPLAY-ID","snapshot":"private.json"}
    manifest_path=tmp_path/"private.manifest.json"; manifest_path.write_text(json.dumps(manifest))
    sanitized_path=tmp_path/"sanitized.json"; sanitized_manifest=tmp_path/"sanitized.manifest.json"
    from app.pull_coach.history.sanitize import sanitize_files
    sanitize_files(manifest_path,sanitized_path,sanitized_manifest)
    # Create a parallel raw manifest so both inputs use identical saved files and mechanics.
    raw_manifest=tmp_path/"raw.manifest.json"; raw_manifest.write_text(json.dumps(manifest))
    mechanics=root/"app/pull_coach/mechanics/definitions/reference_analysis.json"
    raw_result=ReplayRunner(_stages(mechanics,raw_manifest)).run(raw_manifest)
    clean_result=ReplayRunner(_stages(mechanics,sanitized_manifest)).run(sanitized_manifest)
    def semantics(result):
        return [(p.fight_id,p.ingestion.pull.state,p.ingestion.pull.boss_percent,
                 [(f.category,f.severity,f.mechanic_id,len(f.evidence)) for f in p.stages["analysis"].findings],
                 [(x.status,x.occurrence_count,x.max_severity_rank,x.mechanic_id,x.failure_category) for x in p.stages["progression"].subjects],
                 [item.text for key in ("primary_failure","improvements","dps_actions","healer_actions","tank_actions","raid_actions","next_pull_priorities")
                  for item in ([getattr(p.stages["coaching"].public,key)] if key=="primary_failure" else getattr(p.stages["coaching"].public,key))
                  if item is not None]) for p in result.pulls]
    assert semantics(raw_result)==semantics(clean_result)
