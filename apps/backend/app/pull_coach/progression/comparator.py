"""Causal, provider-independent comparison of structured PullAnalysis values."""
from collections import defaultdict

from app.pull_coach.models import (
    ExposureState, FindingCategory, ProgressionDelta, ProgressionStatus, PullAnalysis, PullState,
    Role, Severity,
)
from .config import ProgressionConfig
from .models import BlockerPriority, ProgressionBlocker, ProgressionComparison, ProgressionSubject

COMPARATOR_NAME = "pull-coach-progression"
COMPARATOR_VERSION = "2"
_SEVERITY = {Severity.INFO: 0, Severity.LOW: 1, Severity.MEDIUM: 2,
             Severity.HIGH: 3, Severity.CRITICAL: 4}
_NON_ERROR = {"unavoidable_damage", "healing_check"}


def _subject_id(key):
    kind, actor, role, mechanic, category = key
    if kind == "mechanic":
        return f"mechanic:{mechanic}"
    if kind == "actor_mechanic":
        return f"actor:{actor}:mechanic:{mechanic}"
    if kind == "role_mechanic":
        return f"role:{role}:mechanic:{mechanic}"
    return f"category:{category}"


def _aggregate_status(*statuses):
    if ProgressionStatus.REGRESSED in statuses:
        return ProgressionStatus.REGRESSED
    if ProgressionStatus.IMPROVED in statuses:
        return ProgressionStatus.IMPROVED
    return ProgressionStatus.STABLE


def _chronology(analysis):
    p = analysis.pull
    return p.start_timestamp, p.pull_number, p.fight_id


def _classify(previous, current, threshold, lower_better=True):
    difference = current - previous
    if difference == 0 or abs(difference) < threshold:
        return ProgressionStatus.STABLE
    improved = difference < 0 if lower_better else difference > 0
    return ProgressionStatus.IMPROVED if improved else ProgressionStatus.REGRESSED


class ProgressionComparator:
    comparator_name = COMPARATOR_NAME
    comparator_version = COMPARATOR_VERSION

    def __init__(self, config: ProgressionConfig | None = None):
        self.config = config or ProgressionConfig()

    def compare_sequence(self, analyses):
        ordered = self._validate(analyses)
        return tuple(self.compare(ordered[:i]) for i in range(1, len(ordered) + 1))

    def compare(self, history):
        ordered = self._validate(history)
        if not ordered:
            raise ValueError("progression comparison requires at least one PullAnalysis")
        current = ordered[-1]
        previous = ordered[-2] if len(ordered) > 1 else None
        current_stats = self._subjects(current)
        per_pull = [self._subjects(item) for item in ordered]
        prior_universe = set().union(*(set(s) for s in per_pull[:-1])) if previous else set()
        all_ids = sorted(prior_universe | set(current_stats))
        out_subjects = []
        deltas = []
        prior_progress = self._has_prior_exposure_progress(ordered)
        for sid in all_ids:
            now = current_stats.get(sid)
            old_index = len(ordered) - 2 if previous else None
            old = per_pull[old_index].get(sid) if previous else None
            if sid.startswith("mechanic:"):
                exposed = lambda i: any(e.mechanic_id == sid.removeprefix("mechanic:") and
                                        e.state == ExposureState.EXPOSED for e in ordered[i].mechanic_exposures)
                # Direct observations are comparable even when exposure is unknown.
                # Exposure is needed only to bridge a gap where no prior finding exists.
                if old is None:
                    for i in range(len(ordered) - 2, -1, -1):
                        if sid in per_pull[i]:
                            old_index, old = i, per_pull[i][sid]
                            break
                        if exposed(i):
                            break
            else:
                if old is None and previous:
                    old = next((stats[sid] for stats in reversed(per_pull[:-1]) if sid in stats), None)
            if now is None:
                # Absence carries no evidence of a clean opportunity. Unknown and
                # not-exposed pulls intentionally leave the causal failure history intact.
                continue
            if old is None:
                reappeared = sid in prior_universe
                if sid.startswith("mechanic:") and reappeared:
                    # Do not manufacture a zero baseline from unknown/non-exposed
                    # history. Only an explicit exposed-clean pull establishes zero.
                    mechanic_id = sid.removeprefix("mechanic:")
                    reappeared = any(
                        any(e.mechanic_id == mechanic_id and e.state == ExposureState.EXPOSED
                            for e in item.mechanic_exposures) and sid not in stats
                        for item, stats in zip(ordered[:-1], per_pull[:-1]))
                status = ProgressionStatus.REGRESSED if reappeared else ProgressionStatus.NEWLY_OBSERVED
                before_count = 0 if reappeared else None
                subject = self._subject(sid, now, status, now["count"])
                out_subjects.append(subject)
                deltas.append(ProgressionDelta(sid, status, previous.pull.pull_number if previous else None,
                    current.pull.pull_number, "failure_count", before_count, now["count"]))
                continue
            missing_previous = old_index is not None and old_index != len(ordered) - 2
            use_rate = (old.get("opportunities", 0) > 0 and now.get("opportunities", 0) > 0)
            old_measure = old["count"] / old["opportunities"] if use_rate else old["count"]
            now_measure = now["count"] / now["opportunities"] if use_rate else now["count"]
            count_status = _classify(old_measure, now_measure,
                                     self.config.mechanic_rate_threshold if use_rate else self.config.mechanic_count_threshold)
            severity_status = _classify(old["severity"], now["severity"], self.config.severity_rank_threshold)
            resolved = (now["count"] == 0 and now.get("opportunities", 0) > 0 and
                        (old["count"] > 0 or sid.startswith("mechanic:") and
                         any((stats := values.get(sid)) is not None and stats["count"] > 0
                             for values in per_pull[:-1])))
            stabilized = (sid.startswith("mechanic:") and now["count"] == 0 and
                          self._exposed_clean_streak(ordered, sid) >=
                          self.config.stabilization_pulls)
            status = (ProgressionStatus.STABILIZED if stabilized else
                      ProgressionStatus.RESOLVED if resolved else
                      _aggregate_status(count_status, severity_status))
            subject = self._subject(sid, now, status, now["count"])
            out_subjects.append(subject)
            baseline_number = ordered[old_index].pull.pull_number if old_index is not None else previous.pull.pull_number
            deltas.append(ProgressionDelta(sid, count_status, baseline_number,
                current.pull.pull_number, "failure_rate" if use_rate else "failure_count", old_measure, now_measure))
            if old["severity"] != now["severity"]:
                deltas.append(ProgressionDelta(sid, severity_status, baseline_number,
                    current.pull.pull_number, "max_severity_rank", old["severity"], now["severity"]))
            prior_progress |= status in (ProgressionStatus.IMPROVED, ProgressionStatus.RESOLVED,
                                         ProgressionStatus.STABILIZED)

        self._scalar_deltas(ordered, deltas)
        result_status = None
        if previous:
            if previous.pull.state == PullState.WIPE and current.pull.state == PullState.KILL:
                result_status = ProgressionStatus.IMPROVED
            elif previous.pull.state == PullState.KILL and current.pull.state == PullState.WIPE:
                result_status = ProgressionStatus.REGRESSED
            elif previous.pull.state == current.pull.state:
                result_status = ProgressionStatus.STABLE
        # Select the canonical mechanic/category failure, not a duplicate actor/role
        # view of the same underlying finding. Those remain exposed as deltas.
        new_candidates = [s for s in out_subjects if s.status == ProgressionStatus.NEWLY_OBSERVED
                         and s.occurrence_count and s.subject_type in ("mechanic", "category")]
        if any(s.subject_type == "mechanic" for s in new_candidates):
            new_candidates = [s for s in new_candidates if s.subject_type == "mechanic"]
        blocker = None
        if new_candidates and prior_progress:
            chosen = sorted(new_candidates, key=lambda s: (-s.max_severity_rank, -int(s.repeated),
                -s.occurrence_count, -int(s.death_linked), s.subject_id))[0]
            blocker = ProgressionBlocker(chosen, BlockerPriority(chosen.max_severity_rank,
                chosen.repeated, chosen.occurrence_count, chosen.death_linked))
        return ProgressionComparison(self.comparator_name, self.comparator_version,
            current.pull.encounter.encounter_id, current.pull, tuple(a.pull.pull_number for a in ordered),
            result_status, tuple(sorted(deltas, key=lambda d: d.subject_id)),
            tuple(sorted(out_subjects, key=lambda s: s.subject_id)), blocker)

    def _validate(self, analyses):
        ordered = tuple(sorted(tuple(analyses), key=_chronology))
        if not ordered:
            return ordered
        first = ordered[0]
        for item in ordered:
            if not isinstance(item, PullAnalysis):
                raise TypeError("progression inputs must be PullAnalysis values")
            if item.pull.encounter.encounter_id != first.pull.encounter.encounter_id:
                raise ValueError("progression analyses must share encounter_id")
            if item.pull.report != first.pull.report:
                raise ValueError("progression analyses must share report identity")
            if item.analyzer != first.analyzer:
                raise ValueError("progression analyses must share analyzer name and version")
        return ordered

    def _subjects(self, analysis):
        grouped = defaultdict(list)
        death_related = {finding_id for finding in analysis.findings if finding.category == FindingCategory.DEATH
                         for finding_id in finding.related_finding_ids}
        for finding in analysis.findings:
            category = finding.fact.get("failure_category")
            outcome = finding.fact.get("outcome")
            non_error = outcome is None and category in _NON_ERROR
            if outcome == "success":
                continue
            if outcome == "failure" or finding.category == FindingCategory.MECHANIC and (category not in _NON_ERROR or non_error):
                count = int(finding.fact.get("hit_count", finding.fact.get("event_count", 1)))
                if count <= 0:
                    continue
                mechanic = finding.mechanic_id or finding.fact.get("mechanic_id")
                death_linked = finding.finding_id in death_related
                record = (finding, count, mechanic, category, death_linked)
                ids = []
                if mechanic:
                    ids.append((("mechanic", None, None, mechanic, category), "mechanic"))
                    if not non_error:
                        for actor in finding.actor_ids:
                            ids.append((("actor_mechanic", actor, None, mechanic, category), "actor_mechanic"))
                        for role in finding.roles:
                            if role != Role.UNKNOWN:
                                ids.append((("role_mechanic", None, role.value, mechanic, category), "role_mechanic"))
                if category:
                    ids.append((("category", None, None, None, category), "category"))
                if finding.category in (FindingCategory.INTERRUPT, FindingCategory.DISPEL) and outcome != "failure":
                    ids = []
                for sid, kind in ids:
                    grouped[sid].append((record, kind))
        result = {}
        for key, items in grouped.items():
            sid = _subject_id(key)
            records = [item[0] for item in items]
            first, kind = items[0]
            event_ids = {event_id for record in records for evidence in record[0].evidence
                         for event_id in evidence.event_ids}
            count = len(event_ids) if event_ids else sum(record[1] for record in records)
            result[sid] = {"count": count, "severity": max(_SEVERITY[r[0].severity] for r in records),
                "mechanic": key[3], "category": key[4],
                "actor": key[1], "role": key[2], "kind": key[0],
                "repeated": count > 1 or any(bool(r[0].fact.get("repeated")) or r[1] > 1
                                               for r in records),
                "death_linked": any(r[4] for r in records),
                "evidence": tuple(sorted({e.evidence_id for r in records for e in r[0].evidence}))}
        for exposure in analysis.mechanic_exposures:
            if exposure.state != ExposureState.EXPOSED:
                continue
            sid = f"mechanic:{exposure.mechanic_id}"
            if sid not in result:
                result[sid] = {"count": 0, "severity": 0, "mechanic": exposure.mechanic_id,
                    "category": None, "actor": None, "role": None, "kind": "mechanic",
                    "repeated": False, "death_linked": False,
                    "evidence": tuple(sorted(e.evidence_id for e in exposure.evidence)),
                    "opportunities": exposure.opportunity_count or 0}
            else:
                result[sid]["opportunities"] = exposure.opportunity_count or 0
                result[sid]["evidence"] = tuple(sorted(set(result[sid]["evidence"]) |
                                                        {e.evidence_id for e in exposure.evidence}))
        return result

    def _exposed_clean_streak(self, ordered, sid):
        mechanic_id = sid.removeprefix("mechanic:")
        if not any((stats := self._subjects(item).get(sid)) is not None and stats["count"] > 0
                   for item in ordered[:-1]):
            return 0
        streak = 0
        for item in reversed(ordered):
            exposure = next((e for e in item.mechanic_exposures
                             if e.mechanic_id == mechanic_id), None)
            if exposure is None or exposure.state != ExposureState.EXPOSED:
                break
            stats = self._subjects(item).get(sid)
            if stats is None or stats["count"] != 0 or not stats.get("opportunities", 0):
                break
            streak += 1
        return streak

    def _has_prior_exposure_progress(self, ordered):
        history = defaultdict(list)
        for item in ordered[:-1]:
            for stats in self._subjects(item).values():
                if stats["kind"] == "mechanic":
                    history[stats["mechanic"]].append(stats)
        latest_transition = {}
        for values in history.values():
            for a, b in zip(values, values[1:]):
                use_rate = a.get("opportunities", 0) > 0 and b.get("opportunities", 0) > 0
                before = a["count"] / a["opportunities"] if use_rate else a["count"]
                after = b["count"] / b["opportunities"] if use_rate else b["count"]
                threshold = (self.config.mechanic_rate_threshold if use_rate
                             else self.config.mechanic_count_threshold)
                status = _aggregate_status(_classify(before, after, threshold),
                    _classify(a["severity"], b["severity"], self.config.severity_rank_threshold))
                latest_transition[b["mechanic"]] = status
        return any(status == ProgressionStatus.IMPROVED for status in latest_transition.values())

    @staticmethod
    def _subject(sid, stats, status, count):
        return ProgressionSubject(sid, stats["kind"], status, count, stats["severity"],
            stats["mechanic"], stats["category"], stats["actor"], stats["role"],
            stats["repeated"], stats["death_linked"], stats["evidence"])

    def _scalar_deltas(self, ordered, deltas):
        if len(ordered) < 2:
            return
        old, new = ordered[-2], ordered[-1]
        p0, p1 = old.pull, new.pull
        def add(metric, a, b, threshold, lower=True):
            if a is None or b is None:
                return
            deltas.append(ProgressionDelta(metric, _classify(a, b, threshold, lower),
                p0.pull_number, p1.pull_number, metric, float(a), float(b)))
        add("boss_percent", p0.boss_percent, p1.boss_percent, self.config.boss_percent_threshold)
        duration0 = p0.end_timestamp - p0.start_timestamp if p0.end_timestamp is not None else None
        duration1 = p1.end_timestamp - p1.start_timestamp if p1.end_timestamp is not None else None
        if p0.state == p1.state == PullState.WIPE:
            add("duration_ms", duration0, duration1, self.config.duration_threshold_ms, lower=False)
        deaths = []
        for analysis in (old, new):
            times = [int(f.fact["timestamp"]) - analysis.pull.start_timestamp for f in analysis.findings
                     if f.category == FindingCategory.DEATH and isinstance(f.fact.get("timestamp"), (int, float))]
            deaths.append(min(times) if times else None)
        if deaths[0] is not None and deaths[1] is None:
            deltas.append(ProgressionDelta("first_death_offset_ms", ProgressionStatus.IMPROVED,
                p0.pull_number, p1.pull_number, "first_death_offset_ms", float(deaths[0]), None))
        elif deaths[0] is None and deaths[1] is not None:
            deltas.append(ProgressionDelta("first_death_offset_ms", ProgressionStatus.NEWLY_OBSERVED,
                p0.pull_number, p1.pull_number, "first_death_offset_ms", None, float(deaths[1])))
        else:
            add("first_death_offset_ms", deaths[0], deaths[1], self.config.first_death_threshold_ms, lower=False)
