"""Deterministic fixture-local sanitization for authorized WCL snapshots."""
import json
import re
from pathlib import Path

from app.pull_coach.replay.manifest import load_manifest
from app.web_requests.warcraft_logs import WCLSnapshot

PROVENANCE = "Authorized historical WCL-derived fixture; identities sanitized."


def sanitize_snapshot(snapshot):
    report = json.loads(json.dumps(snapshot.report))
    report_code = report.get("code")
    actors = report.get("masterData", {}).get("actors", [])
    identifiers, replacements = {}, {}
    player_no = 0
    for actor in actors:
        if actor.get("type") == "Player":
            player_no += 1
            identifiers[str(actor.get("id"))] = f"Player {player_no:03d}"
            pseudonym = f"Player {player_no:03d}"
            if actor.get("name"):
                identifiers[actor["name"]] = pseudonym
                replacements[actor["name"]] = pseudonym
            if actor.get("server"): replacements[actor["server"]] = pseudonym
    # Replace all direct player/server occurrences, including pet owner strings.
    def scrub_text(value):
        if report_code:
            value = re.sub(rf"(?<!\w){re.escape(str(report_code))}(?!\w)", "SANITIZED-HISTORICAL-FIXTURE", value)
        for private, pseudonym in sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True):
            if private:
                value = re.sub(rf"(?<!\w){re.escape(private)}(?!\w)", lambda _: pseudonym, value)
        return re.sub(r"https?://\S+", PROVENANCE, value)

    def scrub(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                low = str(key).lower()
                if low in {"server", "reportcode", "report_code", "code"}:
                    continue
                clean_key = scrub_text(str(key))
                result[clean_key] = PROVENANCE if low in {"provenance", "url", "reporturl", "report_url"} else scrub(item)
            return result
        if isinstance(value, list): return [scrub(v) for v in value]
        if isinstance(value, str): return scrub_text(value)
        return value
    report=scrub(report)
    for actor in report.get("masterData", {}).get("actors", []):
        original_id=str(actor.get("id"))
        # actor ordering is stable in the report; map using the original actor ID.
        if original_id in identifiers and identifiers[original_id].startswith("Player "):
            actor["name"] = identifiers[original_id]
        if actor.get("type") == "Player": actor.pop("server", None)
    report["code"]="SANITIZED-HISTORICAL-FIXTURE"
    report["provenance"] = PROVENANCE
    events=scrub(json.loads(json.dumps(snapshot.event_pages)))
    events={int(key): value for key,value in events.items()}
    return WCLSnapshot(report, events)


def sanitize_files(manifest_path, output_snapshot, output_manifest):
    manifest=load_manifest(manifest_path)
    sanitized=sanitize_snapshot(WCLSnapshot.load(manifest.snapshot))
    sanitized.save(output_snapshot)
    data={"schema_version":1,"replay_id":"sanitized-historical-fixture","report_code":"SANITIZED-HISTORICAL-FIXTURE",
          "snapshot":str(Path(__import__("os").path.relpath(Path(output_snapshot).resolve(), Path(output_manifest).resolve().parent))),
          "encounters":[{"encounter_id":eid,"fight_ids":list(ids)} for eid,ids in manifest.encounters],
          "provenance":PROVENANCE}
    # Assertions are fixture behavior, not identity-bearing data. Preserve them;
    # baselines are omitted because identity changes require regeneration.
    if manifest.assertions is not None:
        data["assertions"] = manifest.assertions
    Path(output_manifest).write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return sanitized
