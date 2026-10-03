"""Sequential replay orchestration; each stage receives only a causal prefix."""
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import json
from pathlib import Path
import time
from typing import Any, Protocol, Sequence

from app.web_requests.warcraft_logs import WCLClient, WCLSnapshot
from .manifest import ReplayManifest, load_manifest


class ReplaySpeed(str, Enum):
    STEP = "step"
    MAX = "max"
    ORIGINAL = "original"
    NO_SLEEP = "no-sleep"


class ReplayStage(Protocol):
    name: str

    def run(self, context: "ReplayContext") -> Any: ...


class ReplayPersistence(ReplayStage, Protocol):
    """Optional DAL-46 adapter; accepts domain-only scoped replay context."""


class ReplayAnalyzer(ReplayStage, Protocol):
    """Optional DAL-47 adapter."""


class ReplayProgression(ReplayStage, Protocol):
    """Optional DAL-48 adapter."""


class ReplayCoach(ReplayStage, Protocol):
    """Optional DAL-49 adapter."""


class ReplayRenderer(ReplayStage, Protocol):
    """Optional DAL-50 adapter; rendering remains outside replay analysis."""


@dataclass(frozen=True)
class ReplayContext:
    replay_id: str
    report_code: str
    encounter_id: str
    current: Any
    history: tuple[Any, ...]
    sequence_number: int = 1
    ingestion_history: tuple[Any, ...] = ()
    encounter_history: tuple[Any, ...] = ()
    prior_pull_results: tuple[Any, ...] = ()
    current_stage_outputs: dict[str, Any] | None = None


@dataclass(frozen=True)
class PullResult:
    replay_id: str
    report_code: str
    encounter_id: str
    fight_id: str
    pull_number: int
    ingestion: Any
    stages: dict[str, Any]
    assertions: dict[str, bool]
    sequence_number: int = 1


@dataclass(frozen=True)
class ReplayResult:
    replay_id: str
    report_code: str
    pulls: tuple[PullResult, ...]
    baseline_status: str = "unchecked"
    changes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return _plain(self)

    def canonical_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def human(self) -> str:
        lines = [f"Replay: {self.replay_id}"]
        for pull in self.pulls:
            changed = [item.split(": ", 1)[1][:-8] for item in self.changes
                       if item.startswith(f"pull {pull.sequence_number} fight {pull.fight_id}: ")
                       and item.endswith(" changed")]
            status = "CHANGED" if changed else "PASS"
            lines.append(f"Pull {pull.sequence_number} / fight {pull.fight_id}   {status}")
            lines.extend(f"  {stage}" for stage in changed)
        lines.append(f"Baseline: {self.baseline_status.upper()}")
        lines.extend(f"Changed: {item}" for item in self.changes)
        return "\n".join(lines)


def _plain(value):
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list, set, frozenset)):
        values = list(value)
        if isinstance(value, (set, frozenset)):
            values.sort(key=str)
        return [_plain(v) for v in values]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    return str(value)


class ReplayRunner:
    def __init__(self, stages: Sequence[ReplayStage] = (), client: WCLClient | None = None,
                 sleeper=time.sleep):
        self.stages = tuple(stages)
        self.client = client or WCLClient()
        self.sleeper = sleeper

    def run(self, manifest_path: str | Path, through_pull: int | None = None,
            baseline: str | Path | None = None, update_baseline: bool = False,
            speed: ReplaySpeed = ReplaySpeed.NO_SLEEP, on_step=None) -> ReplayResult:
        manifest = load_manifest(manifest_path)
        snapshot = WCLSnapshot.load(manifest.snapshot)
        fights = [(encounter, fight) for encounter, ids in manifest.encounters for fight in ids]
        if through_pull is not None:
            if through_pull < 1:
                raise ValueError("through_pull must be >= 1")
            fights = fights[:through_pull]
        if not fights:
            raise ValueError(f"{manifest.path}: replay selected no fights")
        session = ReplaySession._from_prepared(self, manifest, snapshot, fights, speed)
        results = []
        while True:
            try:
                if speed is ReplaySpeed.STEP and results and on_step is not None:
                    on_step()
                results.append(session.next())
            except StopIteration:
                break
        result = ReplayResult(manifest.replay_id, manifest.report_code, tuple(results))
        if manifest.assertions:
            expected_count = manifest.assertions.get("expected_pull_count")
            full_replay = len(results) == sum(len(ids) for _, ids in manifest.encounters)
            if full_replay and expected_count is not None and expected_count != len(results):
                raise ValueError(f"replay {manifest.replay_id}, assertion expected_pull_count: "
                                 f"expected {expected_count}, actual {len(results)}")
            expected_ids = manifest.assertions.get("expected_fight_ids")
            actual_ids = [pull.fight_id for pull in results]
            if expected_ids is not None and [str(item) for item in expected_ids[:len(actual_ids)]] != actual_ids:
                raise ValueError(f"replay {manifest.replay_id}, assertion expected_fight_ids: "
                                 f"expected {expected_ids}, actual {actual_ids}")
        selected_baseline = Path(baseline) if baseline is not None else manifest.baseline
        if selected_baseline is not None:
            is_full_replay = len(fights) == sum(len(ids) for _, ids in manifest.encounters)
            if update_baseline and not is_full_replay:
                raise ValueError("cannot update full replay baseline from a prefix replay")
            result = self._compare(result, selected_baseline, update_baseline, is_full_replay)
        return result

    @staticmethod
    def _assert_pull(assertions, fight_id, ingestion, pull_number):
        if not assertions:
            return {}
        per_pull = assertions.get("pulls", {}).get(str(fight_id), {})
        if not isinstance(per_pull, dict):
            raise ValueError(f"assertion pulls[{fight_id}] must be an object")
        known = {"boss_percent", "event_count", "ability_exists"}
        unknown = set(per_pull) - known
        if unknown:
            raise ValueError(f"unknown assertion type(s) for fight {fight_id}: {sorted(unknown)}")
        actual_values = {
            "boss_percent": ingestion.pull.boss_percent,
            "event_count": len(ingestion.events),
            "ability_exists": [str(event.ability_id) for event in ingestion.events],
        }
        results = {}
        for key, expected in per_pull.items():
            actual = actual_values[key]
            passed = str(expected) in actual if key == "ability_exists" and isinstance(actual, list) else actual == expected
            results[key] = passed
            if not passed:
                raise ValueError(f"replay pull {pull_number}, fight {fight_id}, assertion {key}: "
                                 f"expected {expected!r}, actual {actual!r}")
        return results

    @staticmethod
    def _compare(result: ReplayResult, path: Path, update: bool, check_pull_count: bool = True) -> ReplayResult:
        actual = result.canonical_json() + "\n"
        if update:
            path.write_text(actual, encoding="utf-8")
            return ReplayResult(result.replay_id, result.report_code, result.pulls, "updated", (str(path),))
        try:
            expected = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ReplayResult(result.replay_id, result.report_code, result.pulls, "changed", ("baseline missing or invalid",))
        actual_obj = result.as_dict()
        changes = []
        for index, pull in enumerate(result.pulls):
            try:
                wanted = expected["pulls"][index]
            except (KeyError, IndexError, TypeError):
                changes.append(f"pull {pull.sequence_number} fight {pull.fight_id}: missing in baseline")
                continue
            got = actual_obj["pulls"][index]
            prefix = f"pull {pull.sequence_number} fight {pull.fight_id}"
            for section in sorted(set(wanted) | set(got)):
                if section == "stages":
                    wanted_stages, got_stages = wanted.get(section, {}), got.get(section, {})
                    for stage in sorted(set(wanted_stages) | set(got_stages)):
                        if wanted_stages.get(stage) != got_stages.get(stage):
                            changes.append(f"{prefix}: {stage} changed")
                elif wanted.get(section) != got.get(section):
                    changes.append(f"{prefix}: {section} changed")
        if check_pull_count and len(expected.get("pulls", [])) != len(result.pulls):
            changes.append("pull count changed")
        return ReplayResult(result.replay_id, result.report_code, result.pulls,
                            "changed" if changes else "pass", tuple(changes))


class ReplaySession:
    """Lazy pull-at-a-time replay; next() processes exactly one pull."""
    def __init__(self, runner: ReplayRunner, manifest_path: str | Path, through_pull: int | None = None):
        manifest = load_manifest(manifest_path)
        snapshot = WCLSnapshot.load(manifest.snapshot)
        fights = [(encounter, fight) for encounter, ids in manifest.encounters for fight in ids]
        if through_pull is not None:
            if through_pull < 1:
                raise ValueError("through_pull must be >= 1")
            fights = fights[:through_pull]
        self._init(runner, manifest, snapshot, fights, ReplaySpeed.NO_SLEEP)

    @classmethod
    def _from_prepared(cls, runner, manifest, snapshot, fights, speed):
        session = cls.__new__(cls)
        session._init(runner, manifest, snapshot, fights, speed)
        return session

    def _init(self, runner, manifest, snapshot, fights, speed):
        self.runner, self.manifest, self.snapshot = runner, manifest, snapshot
        self.fights, self.speed = tuple(fights), speed
        self.index, self.ingestions, self.completed, self.previous_end = 0, [], [], None

    def next(self) -> PullResult:
        if self.index >= len(self.fights):
            raise StopIteration
        sequence = self.index + 1
        encounter, fight = self.fights[self.index]
        m, runner = self.manifest, self.runner
        try:
            ingestion = runner.client.ingest_fight(self.snapshot, m.report_code, fight)
            actual_encounter = ingestion.pull.encounter.encounter_id
            if actual_encounter != encounter:
                raise ValueError(f"fight encounter {actual_encounter} does not match {encounter}")
            prior_encounter = [p for p in self.completed if p.encounter_id == encounter]
            if self.ingestions and ingestion.pull.start_timestamp < self.ingestions[-1].pull.start_timestamp:
                raise ValueError("manifest fights are not chronological")
            assertions = runner._assert_pull(m.assertions, fight, ingestion, sequence)
            if self.speed is ReplaySpeed.ORIGINAL and self.previous_end is not None:
                runner.sleeper(max(0, (ingestion.pull.start_timestamp - self.previous_end) / 1000))
            self.previous_end = ingestion.pull.end_timestamp or ingestion.pull.start_timestamp
            self.ingestions.append(ingestion)
            outputs = {}
            context = ReplayContext(m.replay_id, m.report_code, encounter, ingestion,
                tuple(self.ingestions), sequence, tuple(self.ingestions),
                tuple(p.ingestion for p in prior_encounter), tuple(self.completed), {})
            for stage in runner.stages:
                try:
                    stage_context = ReplayContext(context.replay_id, context.report_code,
                        context.encounter_id, context.current, context.history, context.sequence_number,
                        context.ingestion_history, context.encounter_history, context.prior_pull_results,
                        dict(outputs))
                    outputs[stage.name] = stage.run(stage_context)
                except Exception as exc:
                    raise RuntimeError(f"replay {m.replay_id}, report {m.report_code}, encounter {encounter}, fight {fight}, pull {sequence}, stage {stage.name}: {exc}") from exc
            result = PullResult(m.replay_id, m.report_code, encounter, str(fight), ingestion.pull.pull_number,
                                ingestion, outputs, assertions, sequence)
            self.completed.append(result)
            self.index += 1
            return result
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("replay "):
                raise
            raise RuntimeError(f"replay {m.replay_id}, report {m.report_code}, encounter {encounter}, fight {fight}, pull {sequence}, stage ingestion: {exc}") from exc
