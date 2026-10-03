"""Developer UX for offline Pull Coach replay and authorized WCL snapshots."""

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from app.pull_coach.analysis import PullAnalyzer
from app.pull_coach.analysis.replay import AnalysisReplayStage
from app.pull_coach.coaching import CoachingReplayStage, CoachingSynthesizer
from app.pull_coach.mechanics import MechanicSchemaError, load_mechanic_registry
from app.pull_coach.presentation import DiscordPresentationReplayStage
from app.pull_coach.progression import ProgressionComparator, ProgressionReplayStage
from app.pull_coach.history.inspect import inspect_snapshot, render_human
from app.pull_coach.history.sanitize import sanitize_files
from app.pull_coach.replay import ReplayRunner, ReplaySpeed
from app.pull_coach.replay.manifest import load_manifest
from app.web_requests.warcraft_logs import WCLClient, WCLSnapshot, parse_report_code

logger = logging.getLogger("pull_coach.demo")


def _stages(mechanics_path, manifest_path):
    registry = load_mechanic_registry(mechanics_path)
    manifest_path = Path(manifest_path).resolve()
    manifest = load_manifest(manifest_path)
    snapshot = WCLSnapshot.load(manifest.snapshot)
    selected_ids = {str(encounter_id) for encounter_id, _ in manifest.encounters}
    if len(selected_ids) != 1:
        raise ValueError("Pull Coach V0 replay requires exactly one selected encounter.")
    definitions = [definition for definition in registry.definitions
                   if definition.encounter.encounter_id in selected_ids]
    if not definitions:
        encounters = {str(f.get("encounterID")): f.get("name", "unknown encounter")
                      for f in snapshot.report.get("fights", [])
                      if str(f.get("encounterID")) in selected_ids}
        encounter = ", ".join(f"{name} ({eid})" for eid, name in sorted(encounters.items())) or ", ".join(sorted(selected_ids))
        raise ValueError(f"No Pull Coach mechanic definitions exist for encounter {encounter}.")
    labels = {item.mechanic_id: item.name for item in definitions}
    logger.info("replay mechanics loaded for encounters %s", ", ".join(sorted(selected_ids)))
    return [AnalysisReplayStage(PullAnalyzer(registry)), ProgressionReplayStage(ProgressionComparator()),
            CoachingReplayStage(CoachingSynthesizer(), labels), DiscordPresentationReplayStage()]


def _human(result):
    lines = [f"Replay: {result.replay_id}"]
    if result.baseline_status != "unchecked":
        lines.append(f"Baseline: {result.baseline_status.upper()}")
        lines.extend(f"Changed: {item}" for item in result.changes)
    for pull in result.pulls:
        ingestion = pull.ingestion
        state = ingestion.pull.state.value.title()
        pct = ingestion.pull.boss_percent
        lines.append(f"\nPull {pull.sequence_number} · Fight {pull.fight_id} · {state} · {pct:g}% remaining" if pct is not None
                     else f"\nPull {pull.sequence_number} · Fight {pull.fight_id} · {state}")
        payload = pull.stages["discord"]
        for field in payload.embed.fields:
            lines.append(f"\n{field.name}:\n  {field.value}")
    return "\n".join(lines)


def replay(args):
    stages = _stages(args.mechanics, args.manifest)
    runner = ReplayRunner(stages=stages)
    speed = ReplaySpeed(args.speed)
    result = runner.run(args.manifest, through_pull=args.through_pull, baseline=args.baseline,
                        update_baseline=args.update_baseline, speed=speed,
                        on_step=(lambda: input("Press Enter for next pull…")) if speed is ReplaySpeed.STEP else None)
    rendered = result.canonical_json() + "\n" if args.format == "json" else _human(result) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 1 if result.baseline_status == "changed" else 0


def snapshot(args):
    client = WCLClient()
    code = parse_report_code(args.reference)
    logger.info("snapshot report %s", code)
    report = client.report_data(code)
    fights_by_id = {str(fight.get("id")): fight for fight in report.get("fights", [])}
    selected = []
    for fight_id in args.fight:
        fight = fights_by_id.get(str(fight_id))
        if fight is None:
            raise ValueError(f"fight {fight_id} not found in report {code}")
        if not isinstance(fight.get("encounterID"), int) or fight["encounterID"] <= 0:
            raise ValueError(f"fight {fight_id} has invalid encounterID; expected a positive encounter ID")
        if fight.get("inProgress") is True or fight.get("endTime") is None:
            raise ValueError(f"fight {fight_id} is not completed; only completed fights can be captured")
        selected.append(fight)
    encounter_ids = {str(fight["encounterID"]) for fight in selected}
    if len(encounter_ids) != 1:
        raise ValueError("Historical snapshot selection must contain exactly one encounter for Pull Coach V0.")
    parts = []
    for fight_id in args.fight:
        logger.info("snapshot report %s fight %s", code, fight_id)
        parts.append(client.snapshot(code, fight_id))
    pages = {fight_id: pages for part in parts for fight_id, pages in part.event_pages.items()}
    output = Path(args.output).resolve()
    WCLSnapshot(report, pages).save(output)
    if args.manifest:
        fights = {str(f["id"]): f for f in report["fights"]}
        selected = sorted((fights[str(fight_id)] for fight_id in args.fight), key=lambda f: f["startTime"])
        encounters = {}
        for fight in selected:
            encounters.setdefault(str(fight["encounterID"]), []).append(str(fight["id"]))
        manifest_path = Path(args.manifest).resolve()
        data = {"schema_version": 1, "replay_id": f"{code}-snapshot", "report_code": code,
                "snapshot": os.path.relpath(output, manifest_path.parent),
                "encounters": [{"encounter_id": eid, "fight_ids": ids}
                                                              for eid, ids in encounters.items()]}
        manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    logger.info("saved report %s snapshot to %s", code, output)
    return 0


def inspect(args):
    manifest = load_manifest(args.manifest)
    selected_ids = [fight_id for _, ids in manifest.encounters for fight_id in ids]
    if args.fight is not None and str(args.fight) not in selected_ids:
        raise ValueError(f"fight {args.fight} is not selected by replay manifest {manifest.replay_id}")
    data = inspect_snapshot(WCLSnapshot.load(manifest.snapshot), fight=args.fight, fight_ids=selected_ids,
                            replay_id=manifest.replay_id, ability=args.ability,
                            name=args.name, event_type=args.event_type, death_window_ms=args.death_window_ms)
    rendered = json.dumps(data, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_human(data) + "\n"
    if args.output: Path(args.output).write_text(rendered, encoding="utf-8")
    else: sys.stdout.write(rendered)
    return 0


def sanitize(args):
    sanitize_files(args.manifest, args.output_snapshot, args.output_manifest)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    replay_parser = sub.add_parser("replay", help="run all Pull Coach stages from a saved manifest")
    replay_parser.add_argument("manifest")
    replay_parser.add_argument("--mechanics", required=True)
    replay_parser.add_argument("--speed", choices=["max", "step", "original"], default="max")
    replay_parser.add_argument("--through-pull", type=int)
    replay_parser.add_argument("--format", choices=["human", "json"], default="human")
    replay_parser.add_argument("--output")
    replay_parser.add_argument("--baseline")
    replay_parser.add_argument("--update-baseline", action="store_true")
    snap_parser = sub.add_parser("snapshot", help="capture selected completed WCL fights")
    snap_parser.add_argument("reference", help="WCL report URL or code")
    snap_parser.add_argument("--fight", type=int, action="append", required=True)
    snap_parser.add_argument("--output", required=True)
    snap_parser.add_argument("--manifest", help="optional path for a new replay manifest")
    inspect_parser = sub.add_parser("inspect", help="inspect a saved snapshot through its replay manifest (offline)")
    inspect_parser.add_argument("manifest")
    inspect_parser.add_argument("--fight", type=int)
    inspect_parser.add_argument("--ability")
    inspect_parser.add_argument("--name")
    inspect_parser.add_argument("--event-type")
    inspect_parser.add_argument("--death-window-ms", type=int, default=8000)
    inspect_parser.add_argument("--format", choices=["human", "json"], default="human")
    inspect_parser.add_argument("--output")
    sanitize_parser = sub.add_parser("sanitize", help="write sanitized snapshot and manifest copies")
    sanitize_parser.add_argument("manifest")
    sanitize_parser.add_argument("--output-snapshot", required=True)
    sanitize_parser.add_argument("--output-manifest", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        return {"replay": replay, "snapshot": snapshot, "inspect": inspect, "sanitize": sanitize}[args.command](args)
    except (ValueError, MechanicSchemaError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
