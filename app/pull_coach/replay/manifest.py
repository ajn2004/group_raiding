"""Versioned replay manifest loading."""
from dataclasses import dataclass
import json
from pathlib import Path

SCHEMA_VERSION = 1


class ReplayManifestError(ValueError):
    """Invalid replay manifest."""


class UnsupportedReplayManifestVersion(ReplayManifestError):
    """Replay manifest version has no supported interpretation."""


@dataclass(frozen=True)
class ReplayManifest:
    path: Path
    replay_id: str
    snapshot: Path
    report_code: str
    encounters: tuple[tuple[str, tuple[str, ...]], ...]
    baseline: Path | None = None
    assertions: dict | None = None


def load_manifest(path: str | Path) -> ReplayManifest:
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayManifestError(f"{path}: cannot read replay manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise ReplayManifestError(f"{path}: manifest must be a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedReplayManifestVersion(
            f"{path}: schema version {version!r} is unsupported; supported version is {SCHEMA_VERSION}")
    try:
        replay_id, report_code = data["replay_id"], data["report_code"]
        snapshot = (path.parent / data["snapshot"]).resolve()
        baseline = (path.parent / data["baseline"]).resolve() if data.get("baseline") else None
        encounters = tuple((str(item["encounter_id"]), tuple(str(fid) for fid in item["fight_ids"]))
                           for item in data["encounters"])
        assertions = data.get("assertions")
        if assertions is not None and not isinstance(assertions, dict):
            raise ValueError("assertions must be an object")
        if not isinstance(replay_id, str) or not replay_id.strip() or not isinstance(report_code, str):
            raise ValueError("replay_id and report_code must be non-empty strings")
        if not encounters or any(not ids for _, ids in encounters):
            raise ValueError("at least one encounter with fight IDs is required")
        all_ids = [fid for _, ids in encounters for fid in ids]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("fight IDs must be unique")
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayManifestError(f"{path}: malformed replay manifest: {exc}") from exc
    return ReplayManifest(path, replay_id, snapshot, report_code, encounters, baseline, assertions)
