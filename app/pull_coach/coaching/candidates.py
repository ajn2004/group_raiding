import hashlib

from app.pull_coach.models import ProgressionStatus
from .models import CoachingCandidate

RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
STATUS_RANK = {ProgressionStatus.STABILIZED: 0, ProgressionStatus.RESOLVED: 1,
               ProgressionStatus.IMPROVED: 2}


def _id(kind, audience, refs):
    source = ":".join((kind, audience, *refs))
    return kind + ":" + hashlib.sha256(source.encode()).hexdigest()[:16]


def generate(value):
    labels = dict(value.mechanic_labels)
    grouped = {}
    for finding in value.findings:
        if finding.pull_number != value.pull_number:
            continue
        category = finding.failure_category
        facts = dict(finding.fact)
        if (finding.category == "death" or not category or
                (category in ("interrupt", "dispel") and facts.get("outcome") != "failure")):
            continue
        subject_id = "mechanic:" + finding.mechanic_id if finding.mechanic_id else "category:" + category
        key = (subject_id, category)
        grouped.setdefault(key, []).append(finding)

    candidates = []
    for (subject_id, category), findings in sorted(grouped.items()):
        findings = sorted(findings, key=lambda finding: finding.finding_id)
        finding_ids = tuple(f.finding_id for f in findings)
        mechanic = findings[0].mechanic_id
        label = labels.get(mechanic, mechanic) if mechanic else category.replace("_", " ")
        severity = max((f.severity for f in findings), key=lambda item: RANK[item])
        high_pressure = category in ("healing_check", "unavoidable_damage")
        if high_pressure:
            text = f"{label} is a raid-wide pressure point this pull."
            if value.progression.newly_exposed_blocker and value.progression.newly_exposed_blocker.subject.subject_id == subject_id:
                text = f"{label} is a newly exposed raid-wide pressure point this pull."
        elif category == "avoidable_damage":
            count = sum((dict(f.fact).get("hit_count") or 1) for f in findings)
            unit = "time" if count == 1 else "times"
            text = f"{label} was hit {count} {unit} this pull."
        else:
            text = f"{label}: {category.replace('_', ' ')} failure was observed."
        candidates.append(CoachingCandidate(_id("primary", "raid", (subject_id, *finding_ids)), "raid",
            "primary_failure", finding_ids, (subject_id,), mechanic, category, severity, text))
        if high_pressure:
            continue
        action_text = {"avoidable_damage": f"Reduce avoidable hits from {label}.",
            "positioning": f"Clean up positioning on {label}.", "interrupt": f"Improve interrupt execution on {label}.",
            "dispel": f"Improve dispel execution on {label}.", "target_priority": f"Improve target-priority execution on {label}.",
            "tank_execution": f"Clean up tank execution on {label}.",
            "cooldown_or_resource": f"Improve cooldown/resource execution on {label}.",
            "assignment": f"Clean up assignment execution on {label}."}.get(category, f"Keep {label} controlled.")
        for role, audience in (("damage", "dps"), ("healer", "healer"), ("tank", "tank")):
            subset = tuple(f.finding_id for f in findings if role in f.roles)
            if subset:
                candidates.append(CoachingCandidate(_id("action", audience, (subject_id, *subset)), audience,
                    "role_action", subset, (subject_id,), mechanic, category, severity,
                    f"{audience.title()}: {action_text}"))
        candidates.append(CoachingCandidate(_id("action", "raid", (subject_id, *finding_ids)), "raid",
            "raid_action", finding_ids, (subject_id,), mechanic, category, severity, f"Raid: {action_text}"))

    # Exactly one legal primary slot, but all grounded failures remain eligible choices.
    history_ids = {f.finding_id for f in value.findings}
    improvements = []
    for subject in value.progression.subjects:
        if subject.status not in STATUS_RANK:
            continue
        matching = [f for f in value.findings if f.finding_id in history_ids and
                    ((subject.subject_type == "mechanic" and f.mechanic_id == subject.mechanic_id) or
                     (subject.subject_type == "category" and f.failure_category == subject.failure_category)) and
                    (f.pull_number < value.pull_number or
                     (subject.status == ProgressionStatus.IMPROVED and f.pull_number == value.pull_number))]
        ids = tuple(sorted({f.finding_id for f in matching}))
        if not ids:
            continue
        mechanic = subject.mechanic_id
        label = labels.get(mechanic, mechanic) if mechanic else subject.failure_category
        text = f"{label} {subject.status.value.lower()}."
        improvements.append(CoachingCandidate(_id("improvement", "raid", (subject.subject_id, *ids)),
            "raid", "improvement", ids, (subject.subject_id,), mechanic, subject.failure_category,
            "high" if subject.max_severity_rank >= 3 else "medium", text))
    # Keep aggregate category progression internally, but do not publish it when
    # an equivalent named mechanic statement is grounded by the same evidence.
    by_id = {f.finding_id: f for f in value.findings}
    retained = []
    for candidate in improvements:
        subject = next((s for s in value.progression.subjects
                        if s.subject_id == candidate.progression_subject_ids[0]), None)
        if subject and subject.subject_type == "category":
            candidate_evidence = {e for fid in candidate.finding_ids
                                  for e in by_id.get(fid, ()).evidence_ids} if candidate.finding_ids else set()
            covered_evidence = set()
            for other in improvements:
                other_subject = next((s for s in value.progression.subjects
                                      if s.subject_id == other.progression_subject_ids[0]), None)
                if (other_subject and other_subject.subject_type == "mechanic" and
                        other_subject.failure_category == subject.failure_category and
                        other_subject.status == subject.status):
                    other_evidence = {e for fid in other.finding_ids
                                      for e in by_id.get(fid, ()).evidence_ids}
                    covered_evidence.update(other_evidence)
            if candidate_evidence and candidate_evidence <= covered_evidence:
                continue
        retained.append(candidate)
    candidates.extend(retained)
    return tuple(sorted(candidates, key=lambda candidate: candidate.candidate_id))
