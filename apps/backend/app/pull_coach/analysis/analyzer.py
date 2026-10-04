"""Provider-independent deterministic facts for one normalized pull."""

from collections import defaultdict
import hashlib
import json
from typing import Iterable

from app.pull_coach.mechanics import MechanicMatch, MechanicRegistry
from app.pull_coach.models import (
    Actor, AnalysisMetadata, EventType, EvidenceReference, Finding,
    ExposureState, FindingCategory, MechanicExposure, MechanicObservation, NormalizedEvent, PullAnalysis,
    PullIdentity, Role, Severity, SummaryMetrics, is_raid_player,
)
from app.pull_coach.analysis.config import AnalyzerConfig

ANALYZER_NAME = "pull-coach-deterministic"
ANALYZER_VERSION = "3"


def _subject(event: NormalizedEvent, match: MechanicMatch) -> str | None:
    override = match.definition.metadata.get("subject_actor")
    if override is not None:
        if override == "source":
            return event.source_actor_id
        if override == "target":
            return event.target_actor_id
        return None
    if event.event_type == EventType.DAMAGE:
        return event.target_actor_id
    if event.event_type in (EventType.INTERRUPT, EventType.DISPEL, EventType.CAST, EventType.RESOURCE):
        return event.source_actor_id
    return None


def _evidence(event: NormalizedEvent, description: str) -> EvidenceReference:
    return EvidenceReference(event.evidence_id, (event.evidence_id,), description)


class PullAnalyzer:
    """Analyze normalized domain values and a DAL-45 mechanic registry."""

    def __init__(self, registry: MechanicRegistry, config: AnalyzerConfig | None = None) -> None:
        self.registry = registry
        self.config = config or AnalyzerConfig()

    def analyze(self, pull: PullIdentity, actors: Iterable[Actor],
                events: Iterable[NormalizedEvent]) -> PullAnalysis:
        actor_by_id = {actor.actor_id: actor for actor in actors}
        ordered = sorted(enumerate(events), key=lambda pair: (pair[1].timestamp, pair[0]))
        matches_by_index: dict[int, tuple[MechanicMatch, ...]] = {}
        exposure_counts: dict[str, int] = defaultdict(int)
        exposure_evidence: dict[str, list] = defaultdict(list)
        observations: list[MechanicObservation] = []
        # Stable IDs refer to source evidence rather than iteration/hash order.
        for index, event in ordered:
            for mechanic_id, evidence in self.registry.exposure_matches(pull.encounter, event):
                exposure_counts[mechanic_id] += 1
                exposure_evidence[mechanic_id].append(evidence)
            matches = self.registry.match(pull.encounter, event)
            matches_by_index[index] = matches
            for match in matches:
                subject = _subject(event, match)
                actor_ids = tuple(dict.fromkeys(x for x in (subject, event.source_actor_id,
                                                            event.target_actor_id) if x))
                observations.append(MechanicObservation(
                    f"{pull.fight_id}:{match.definition.mechanic_id}:{event.evidence_id}",
                    match.definition.mechanic_id, event.timestamp, actor_ids,
                    (_evidence(event, f"Matched {match.definition.name}"),),
                    {"failure_category": match.definition.failure_category,
                     "avoidable": match.definition.avoidable,
                     "definition_version": match.definition_version,
                     "registry_version": match.registry_version,
                     "weight": match.weight, "relationships": dict(match.relationships)},
                ))

        findings: list[Finding] = []
        buckets: dict[tuple[str, str | None], list[tuple[NormalizedEvent, MechanicMatch]]] = defaultdict(list)
        for index, event in ordered:
            for match in matches_by_index[index]:
                # Native interrupt/dispel records are direct evidence of success.
                if event.event_type in (EventType.INTERRUPT, EventType.DISPEL):
                    category = FindingCategory.INTERRUPT if event.event_type == EventType.INTERRUPT else FindingCategory.DISPEL
                    stopped_id = event.metadata.get("stopped_ability_id")
                    fact = {"outcome": "success",
                            "mechanic_id": match.definition.mechanic_id,
                            "failure_category": match.definition.failure_category,
                            "stopped_ability_id": stopped_id,
                            "stopped_ability_name": event.metadata.get("stopped_ability_name")}
                    self._append_finding(findings, pull, category, match.definition.severity, fact,
                        (_evidence(event, f"Observed {event.event_type.value}"),),
                        (event.source_actor_id,) if event.source_actor_id else (), match.definition.mechanic_id,
                        actor_by_id)
                    continue
                if event.event_type == EventType.DAMAGE and (
                    match.definition.avoidable is True or
                    (match.definition.avoidable is False and match.definition.failure_category
                     not in ("unavoidable_damage", "healing_check")) or
                    (match.definition.failure_category not in ("unavoidable_damage", "healing_check")
                     and match.definition.metadata.get("outcome") == "failure")
                ):
                    buckets[(match.definition.mechanic_id, _subject(event, match))].append((event, match))

        # Mechanic/subject facts include known damage and generic matched failure rules.
        for index, event in ordered:
            for match in matches_by_index[index]:
                if event.event_type == EventType.DAMAGE and (match.definition.avoidable is not None or
                    match.definition.failure_category in ("unavoidable_damage", "healing_check")):
                    continue
                if event.event_type in (EventType.INTERRUPT, EventType.DISPEL):
                    continue
                if match.definition.metadata.get("outcome") != "failure":
                    continue
                subject = _subject(event, match)
                if event.event_type == EventType.CAST and match.definition.failure_category in ("interrupt", "dispel"):
                    category = (FindingCategory.INTERRUPT if match.definition.failure_category == "interrupt"
                                else FindingCategory.DISPEL)
                    fact = {"outcome": "failure", "mechanic_id": match.definition.mechanic_id,
                            "failure_category": match.definition.failure_category}
                    self._append_finding(findings, pull, category, match.definition.severity, fact,
                        (_evidence(event, f"Observed configured {match.definition.failure_category} failure"),),
                        (subject,) if subject else (), match.definition.mechanic_id, actor_by_id)
                    continue
                buckets[(match.definition.mechanic_id, subject)].append((event, match))

        for (mechanic_id, subject), items in sorted(buckets.items(), key=lambda item: (item[1][0][0].timestamp, item[0][0], item[0][1] or "")):
            items.sort(key=lambda item: item[0].timestamp)
            event, match = items[0]
            definition = match.definition
            category = definition.failure_category
            amounts = [float(item.amount or 0) for item, _ in items if item.amount is not None]
            fact = {"mechanic_id": mechanic_id, "failure_category": category,
                    "hit_count": len(items), "total_damage": sum(amounts),
                    "repeated": len(items) >= self.config.repeated_failure_threshold,
                    "avoidable": definition.avoidable, "first_timestamp": items[0][0].timestamp,
                    "last_timestamp": items[-1][0].timestamp}
            ids = (subject,) if subject else ()
            evidence = tuple(_evidence(item, f"Observed {definition.name}") for item, _ in items)
            self._append_finding(findings, pull, FindingCategory.MECHANIC, definition.severity,
                                 fact, evidence, ids, mechanic_id, actor_by_id)

        # Raid-level unavoidable/healing-check windows aggregate affected targets.
        raid_damage: dict[str, list[tuple[NormalizedEvent, MechanicMatch]]] = defaultdict(list)
        for index, event in ordered:
            if event.event_type != EventType.DAMAGE:
                continue
            for match in matches_by_index[index]:
                if match.definition.failure_category in (
                    "unavoidable_damage", "healing_check"
                ):
                    raid_damage[match.definition.mechanic_id].append((event, match))
        for mechanic_id, items in sorted(raid_damage.items()):
            windows: list[list[tuple[NormalizedEvent, MechanicMatch]]] = []
            for item in items:
                if not windows or item[0].timestamp - windows[-1][-1][0].timestamp > self.config.raid_window_gap_ms:
                    windows.append([])
                windows[-1].append(item)
            for window in windows:
                _, match = window[0]
                targets = tuple(sorted({event.target_actor_id for event, _ in window if event.target_actor_id}))
                events_in_window = [event for event, _ in window]
                self._append_finding(findings, pull, FindingCategory.MECHANIC,
                    match.definition.severity,
                    {"mechanic_id": mechanic_id, "failure_category": match.definition.failure_category,
                     "window": True, "start_timestamp": events_in_window[0].timestamp,
                     "end_timestamp": events_in_window[-1].timestamp,
                     "affected_actor_count": len(targets), "event_count": len(window),
                     "total_damage": sum(float(event.amount or 0) for event in events_in_window),
                     "avoidable": False},
                    tuple(_evidence(event, f"Observed {match.definition.name} raid damage")
                          for event in events_in_window), targets, mechanic_id, actor_by_id)

        # Death facts retain every in-window damage event, including unknown abilities.
        damage_events = [(i, e, matches_by_index[i]) for i, e in ordered if e.event_type == EventType.DAMAGE]
        mechanic_findings_by_pair: dict[tuple[str | None, str], list[Finding]] = defaultdict(list)
        for finding in findings:
            if finding.category == FindingCategory.MECHANIC:
                for actor_id in finding.actor_ids:
                    mechanic_findings_by_pair[(finding.mechanic_id, actor_id)].append(finding)
        for index, death in ordered:
            if death.event_type != EventType.DEATH or not is_raid_player(
                    actor_by_id.get(death.target_actor_id)):
                continue
            lower = death.timestamp - self.config.pre_death_window_ms
            window = [(event, matches) for _, event, matches in damage_events
                      if event.target_actor_id == death.target_actor_id and lower <= event.timestamp <= death.timestamp]
            matched_avoidable = 0.0
            matched_unavoidable = 0.0
            unmatched = 0.0
            categories: set[str] = set()
            mechanic_ids: set[str] = set()
            related: set[str] = set()
            for damage, matches in window:
                if not matches:
                    unmatched += float(damage.amount or 0)
                    continue
                event_avoidable = False
                event_unavoidable_categories: set[str] = set()
                for m in matches:
                    cat = m.definition.failure_category
                    mechanic_ids.add(m.definition.mechanic_id)
                    if m.definition.avoidable is True:
                        event_avoidable = True
                        categories.add("avoidable_damage")
                    elif m.definition.avoidable is False or cat in ("unavoidable_damage", "healing_check"):
                        event_unavoidable_categories.add(cat)
                        categories.add(cat)
                    for finding in mechanic_findings_by_pair.get(
                            (m.definition.mechanic_id, death.target_actor_id), ()):
                        finding_event_ids = {event_id for item in finding.evidence for event_id in item.event_ids}
                        if damage.evidence_id in finding_event_ids:
                            related.add(finding.finding_id)
                amount = float(damage.amount or 0)
                if event_avoidable:
                    matched_avoidable += amount
                if event_unavoidable_categories:
                    matched_unavoidable += amount
            total = sum(float(e.amount or 0) for e, _ in window)
            fact = {"timestamp": death.timestamp, "pre_death_damage_total": total,
                    "pre_death_event_count": len(window), "matched_avoidable_damage_total": matched_avoidable,
                    "matched_unavoidable_damage_total": matched_unavoidable, "unmatched_damage_total": unmatched,
                    "contributing_categories": tuple(sorted(categories)),
                    "contributing_mechanic_ids": tuple(sorted(mechanic_ids)),
                    "pre_death_event_ids": tuple(e.evidence_id for e, _ in window)}
            if categories == {"avoidable_damage"}:
                fact["failure_category"] = "avoidable_damage"
            elif categories and not categories.intersection({"avoidable_damage"}):
                fact["failure_category"] = ",".join(sorted(categories))
            self._append_finding(findings, pull, FindingCategory.DEATH, Severity.HIGH, fact,
                (_evidence(death, "Observed death"),) + tuple(_evidence(e, "Pre-death damage") for e, _ in window),
                (death.target_actor_id,), None, actor_by_id, tuple(sorted(related)))

        # Recover ordering from source events, then stable domain keys.
        event_time = {event.evidence_id: event.timestamp for _, event in ordered}
        findings.sort(key=lambda f: (f.fact.get("timestamp", min(
                                         (event_time.get(e.event_ids[0], 0) for e in f.evidence), default=0)),
                                     f.category.value, f.mechanic_id or "", f.actor_ids, f.finding_id))
        # Observations were appended in timestamp/source order, with registry
        # match ordering retained for equal-timestamp events.
        avoidable_events = [e for index, e in ordered if e.event_type == EventType.DAMAGE and
                            any(m.definition.avoidable is True for m in matches_by_index[index])]
        categories = set()
        for finding in findings:
            if finding.fact.get("outcome") == "failure":
                categories.add(finding.fact["failure_category"])
            categories.update(finding.fact.get("contributing_categories", ()))
            if finding.category == FindingCategory.MECHANIC and "failure_category" in finding.fact:
                categories.add(finding.fact["failure_category"])
        cats = sorted(categories)
        summary = SummaryMetrics({
            "death_count": sum(e.event_type == EventType.DEATH and is_raid_player(
                actor_by_id.get(e.target_actor_id)) for _, e in ordered),
            "mechanic_observation_count": len(observations),
            "avoidable_damage_total": sum(float(e.amount or 0) for e in avoidable_events),
            "avoidable_damage_event_count": len(avoidable_events),
            "repeated_mechanic_failure_count": sum(bool(f.fact.get("repeated")) for f in findings),
            "interrupt_success_count": sum(f.category == FindingCategory.INTERRUPT and f.fact["outcome"] == "success" for f in findings),
            "interrupt_failure_count": sum(f.category == FindingCategory.INTERRUPT and f.fact["outcome"] == "failure" for f in findings),
            "dispel_success_count": sum(f.category == FindingCategory.DISPEL and f.fact["outcome"] == "success" for f in findings),
            "dispel_failure_count": sum(f.category == FindingCategory.DISPEL and f.fact["outcome"] == "failure" for f in findings),
            "failure_categories": ",".join(cats), "mechanic_registry_version": self.registry.registry_version,
        })
        exposures = tuple(
            MechanicExposure(
                rule.definition.mechanic_id,
                (ExposureState.EXPOSED if exposure_counts.get(rule.definition.mechanic_id, 0)
                 else ExposureState.NOT_EXPOSED),
                exposure_counts.get(rule.definition.mechanic_id, 0),
                tuple(exposure_evidence.get(rule.definition.mechanic_id, ())),
            ) if rule.exposure_event_types else
            MechanicExposure(rule.definition.mechanic_id, ExposureState.UNKNOWN)
            for rule in self.registry.rules_for_encounter(pull.encounter)
        )
        return PullAnalysis(pull, tuple(findings), tuple(observations), summary,
                            AnalysisMetadata(ANALYZER_NAME, ANALYZER_VERSION), exposures,
                            tuple(sorted(actor_id for actor_id, actor in actor_by_id.items()
                                         if is_raid_player(actor))))

    @staticmethod
    def _append_finding(findings, pull, category, severity, fact, evidence, actor_ids,
                        mechanic_id, actors, related=()):
        ids = tuple(actor_ids)
        roles = tuple((actors[a].role if a in actors else None) or Role.UNKNOWN for a in ids)
        identity = json.dumps([pull.fight_id, category.value, mechanic_id or "none", ids,
                               [event_id for item in evidence for event_id in item.event_ids]],
                              ensure_ascii=True, separators=(",", ":"))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        finding_id = f"{pull.fight_id}:{category.value}:{digest}"
        findings.append(Finding(finding_id, category, severity, fact, tuple(evidence), ids,
                                roles, mechanic_id, tuple(related)))
