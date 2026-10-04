"""Filesystem-backed mechanics lifecycle store.

Only artifacts in ``verified/`` are parsed into analyzer-facing registries.
Discovery and draft artifacts have separate codecs/storage paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from app.pull_coach.mechanics.loader import MechanicSchemaError, load_mechanic_registry
from app.pull_coach.mechanics.registry import MechanicRegistry
from app.pull_coach.models import EncounterDiscovery, discovery_from_json, discovery_to_json


class MechanicsStoreError(Exception):
    """Mechanics artifacts could not be loaded or persisted."""


class DirectoryMechanicsStore:
    """Directory-backed store with ``verified``, ``discovered`` and ``drafts`` lanes."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, lane: str, encounter_id: str) -> Path:
        if not isinstance(encounter_id, str) or not encounter_id or Path(encounter_id).name != encounter_id or encounter_id in (".", ".."):
            raise ValueError("encounter_id must be a non-empty filename-safe identifier")
        return self.root / lane / f"{encounter_id}.json"

    def load_verified_registry(self) -> MechanicRegistry:
        if not self.root.exists() or not self.root.is_dir():
            raise MechanicsStoreError(f"mechanics root {self.root} does not exist or is not a directory")
        folder = self.root / "verified"
        if folder.exists() and not folder.is_dir():
            raise MechanicsStoreError(f"verified mechanics path {folder} is not a directory")
        try:
            paths = sorted(folder.glob("*.json"), key=lambda path: path.name)
        except OSError as exc:
            raise MechanicsStoreError(f"cannot enumerate verified mechanics in {folder}: {exc}") from exc
        rules = []
        versions = []
        sources = {}
        for path in paths:
            try:
                registry = load_mechanic_registry(path, source_artifact=f"verified/{path.name}")
            except (MechanicSchemaError, OSError) as exc:
                raise MechanicsStoreError(f"invalid verified mechanics file {path}: {exc}") from exc
            versions.append(f"{path.name}={registry.registry_version}")
            for rule in registry.rules:
                identity = (rule.definition.encounter.encounter_id, rule.definition.mechanic_id)
                if identity in sources:
                    raise MechanicsStoreError(
                        f"duplicate mechanic_id {identity[1]!r} for encounter {identity[0]!r} in "
                        f"{sources[identity]} and {path}"
                    )
                sources[identity] = path
                rules.append(rule)
        version = ";".join(versions) if versions else "empty"
        try:
            return MechanicRegistry(tuple(rules), version)
        except ValueError as exc:
            raise MechanicsStoreError(
                f"verified mechanics across {', '.join(map(str, paths)) or folder} are ambiguous: {exc}"
            ) from exc

    def write_discovery(self, artifact: EncounterDiscovery) -> Path:
        return self._atomic_write(self._path("discovered", artifact.encounter_id), discovery_to_json(artifact) + "\n")

    def read_discovery(self, encounter_id: str) -> EncounterDiscovery | None:
        path = self._path("discovered", encounter_id)
        try:
            return discovery_from_json(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, ValueError) as exc:
            raise MechanicsStoreError(f"cannot read discovery artifact {path}: {exc}") from exc

    def write_draft(self, encounter_id: str, artifact: dict[str, Any]) -> Path:
        try:
            document = json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        except (TypeError, ValueError) as exc:
            raise MechanicsStoreError(f"draft artifact is not valid JSON: {exc}") from exc
        return self._atomic_write(self._path("drafts", encounter_id), document)

    def read_draft(self, encounter_id: str) -> dict[str, Any] | None:
        path = self._path("drafts", encounter_id)
        try:
            if not path.exists():
                return None
            result = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(result, dict):
                raise ValueError("draft document must be a JSON object")
            return result
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise MechanicsStoreError(f"cannot read draft artifact {path}: {exc}") from exc

    def write_verified(self, encounter_id: str, document: dict[str, Any], *, replace: bool = False) -> Path:
        """Validate the complete resulting registry before atomically adding/replacing a file."""
        path = self._path("verified", encounter_id)
        try:
            if path.exists() and not replace:
                raise MechanicsStoreError(f"verified mechanics file already exists: {path}; pass replace=True to update it")
            text = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            with tempfile.TemporaryDirectory() as temp_dir:
                validation_root = Path(temp_dir)
                validation_folder = validation_root / "verified"
                validation_folder.mkdir()
                if (self.root / "verified").exists():
                    for current in (self.root / "verified").glob("*.json"):
                        if current.name != path.name:
                            shutil.copyfile(current, validation_folder / current.name)
                candidate = validation_folder / path.name
                candidate.write_text(text, encoding="utf-8")
                new_registry = load_mechanic_registry(candidate)
                if any(rule.definition.encounter.encounter_id != encounter_id for rule in new_registry.rules):
                    raise MechanicsStoreError(f"verified definitions in {path} do not match encounter_id {encounter_id!r}")
                DirectoryMechanicsStore(validation_root).load_verified_registry()
        except (OSError, TypeError, ValueError, MechanicsStoreError) as exc:
            raise MechanicsStoreError(f"cannot validate verified mechanics for {path}: {exc}") from exc
        return self._atomic_write(path, text + "\n")

    @staticmethod
    def _atomic_write(path: Path, text: str) -> Path:
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return path
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise MechanicsStoreError(f"cannot persist mechanics artifact {path}: {exc}") from exc


def configured_mechanics_registry():
    """Build the live registry; root takes precedence over the legacy file setting."""
    from app.pull_coach.workflow import PullCoachConfigurationError

    root = os.getenv("PULL_COACH_MECHANICS_ROOT")
    legacy_path = os.getenv("PULL_COACH_MECHANICS_FILE")
    if root:
        try:
            return DirectoryMechanicsStore(root).load_verified_registry()
        except MechanicsStoreError as exc:
            raise PullCoachConfigurationError(f"configured mechanics root could not be loaded: {exc}") from exc
    if legacy_path:
        try:
            return load_mechanic_registry(legacy_path)
        except (MechanicSchemaError, OSError) as exc:
            raise PullCoachConfigurationError(f"configured mechanic definitions could not be loaded from {legacy_path}: {exc}") from exc
    raise PullCoachConfigurationError("configure PULL_COACH_MECHANICS_ROOT or PULL_COACH_MECHANICS_FILE")
