"""Small, versioned selection-only provider prompt."""
import json

from .models import CoachingCandidate, CoachingInput

PROMPT_VERSION = "2"


def build_prompt(value: CoachingInput, candidates: tuple[CoachingCandidate, ...], limits: dict[str, int]) -> str:
    available = [{"id": item.candidate_id, "finding_ids": item.finding_ids,
                  "progression_subject_ids": item.progression_subject_ids,
                  "mechanic_id": item.mechanic_id, "mechanic_label": dict(value.mechanic_labels).get(item.mechanic_id),
                  "failure_category": item.failure_category, "severity": item.severity,
                  "audience": item.audience, "kind": item.kind, "text": item.text}
                 for item in candidates]
    progression = {
        "pull_result": value.progression.pull_result.value if value.progression.pull_result else None,
        "subjects": [{"id": item.subject_id, "type": item.subject_type, "status": item.status.value}
                     for item in value.progression.subjects],
        "deltas": [{"subject_id": item.subject_id, "status": item.status.value,
                    "metric": item.metric} for item in value.progression.deltas],
        "newly_exposed_blocker": (value.progression.newly_exposed_blocker.subject.subject_id
                                   if value.progression.newly_exposed_blocker else None),
    }
    findings = [{"id": item.finding_id, "pull": item.pull_number, "category": item.category,
                 "severity": item.severity, "mechanic_id": item.mechanic_id,
                 "failure_category": item.failure_category} for item in value.findings]
    return (f"Pull Coach candidate selection prompt v{PROMPT_VERSION}.\n"
            f"PULL: {value.pull_number}; encounter: {value.encounter_id}; fight: {value.fight_id}\n"
            f"PROGRESSION: {json.dumps(progression, sort_keys=True)}\n"
            f"SUPPORTED FINDINGS: {json.dumps(findings, sort_keys=True)}\n"
            f"AVAILABLE_CANDIDATES: {json.dumps(available, sort_keys=True)}\n"
            f"LIMITS: {json.dumps(limits, sort_keys=True)}\n"
            "Return only CoachingSelection candidate IDs. Only IDs in AVAILABLE_CANDIDATES are legal. "
            "Select one primary, up to the configured improvement/action/priority limits. "
            "Do not write claims, prose, names, mechanics, causes, values, or actions.")
