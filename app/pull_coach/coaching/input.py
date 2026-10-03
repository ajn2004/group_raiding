from app.pull_coach.models import PullAnalysis
from app.pull_coach.progression.models import ProgressionComparison
from .models import CoachingInput, GroundedFinding


def build_input(analysis: PullAnalysis, progression: ProgressionComparison,
                history: tuple[PullAnalysis, ...] = (), mechanic_labels=None):
    if progression.current_pull != analysis.pull:
        raise ValueError("progression current_pull must match the analysis pull")
    labels = dict(mechanic_labels or {})
    # The causal prefix is explicit. The current pull is included once.
    analyses = tuple(history) + (analysis,)
    findings = []
    for item in analyses:
        if item.pull.encounter.encounter_id != analysis.pull.encounter.encounter_id:
            continue
        if item.pull.report != analysis.pull.report:
            continue
        if (item.analyzer.analyzer_name, item.analyzer.analyzer_version) != (analysis.analyzer.analyzer_name, analysis.analyzer.analyzer_version):
            if item is analysis:
                raise ValueError("analysis history must use the current analyzer name and version")
            continue
        if item is not analysis and item.pull.pull_number >= analysis.pull.pull_number:
            continue
        for finding in item.findings:
            findings.append(GroundedFinding(finding.finding_id, item.pull.pull_number,
                finding.category.value, finding.severity.value, finding.mechanic_id,
                labels.get(finding.mechanic_id), finding.fact.get("failure_category"),
                tuple(sorted(finding.fact.items())),
                tuple(sorted({e.evidence_id for e in finding.evidence})), finding.actor_ids,
                tuple(role.value for role in finding.roles)))
    findings.sort(key=lambda f: (f.pull_number, f.finding_id))
    return CoachingInput(analysis.pull.fight_id, analysis.pull.encounter.encounter_id,
        analysis.pull.pull_number, tuple(findings), progression, tuple(sorted(labels.items())))
