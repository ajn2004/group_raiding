"""Translate Pull Coach domain contracts to and from SQLAlchemy storage."""

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.pull_coach import (
    PullCoachAnalysis, PullCoachEvidence, PullCoachFinding, PullCoachPull,
    PullCoachReport,
)
from app.pull_coach.models.contracts import (
    EncounterIdentity, EvidenceReference, Finding, FindingCategory, PullAnalysis,
    PullIdentity, PullState, RaidReportIdentity, Role, Severity, SourceIdentity,
)


@dataclass(frozen=True)
class AnalysisProvenance:
    analyzer_name: str
    analyzer_version: str
    result_fingerprint: str


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _canonical(value):
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


class PullCoachRepository:
    """Persistence boundary; accepts a caller-owned SQLAlchemy session."""

    def __init__(self, session: Session):
        self.session = session

    def _report(self, identity, scope):
        source = identity.source
        report = self.session.scalar(select(PullCoachReport).where(
            PullCoachReport.scope == scope,
            PullCoachReport.provider == source.provider,
            PullCoachReport.report_code == identity.report_code,
        ))
        if report is None:
            report = PullCoachReport(scope=scope, provider=source.provider,
                                     source_id=source.source_id, report_code=identity.report_code)
            self.session.add(report)
            self.session.flush()
        elif report.source_id != source.source_id:
            raise ValueError("report identity conflicts with existing source_id in this scope")
        return report

    @staticmethod
    def _to_pull(row, report):
        return PullIdentity(
            report=RaidReportIdentity(SourceIdentity(report.provider, report.source_id), report.report_code),
            encounter=EncounterIdentity(row.encounter_id, row.encounter_name),
            fight_id=row.fight_id, pull_number=row.pull_number,
            start_timestamp=row.start_timestamp, end_timestamp=row.end_timestamp,
            state=PullState(row.state), boss_percent=row.boss_percent,
        )

    def _upsert_pull_row(self, pull: PullIdentity, scope: str) -> PullCoachPull:
        report = self._report(pull.report, scope)
        row = self.session.scalar(select(PullCoachPull).where(
            PullCoachPull.report_id == report.id, PullCoachPull.fight_id == pull.fight_id,
        ))
        values = dict(encounter_id=pull.encounter.encounter_id,
                      encounter_name=pull.encounter.name, pull_number=pull.pull_number,
                      start_timestamp=pull.start_timestamp, end_timestamp=pull.end_timestamp,
                      state=pull.state.value, boss_percent=pull.boss_percent)
        if row is None:
            row = PullCoachPull(report_id=report.id, fight_id=pull.fight_id, **values)
            self.session.add(row)
        else:
            immutable = ("encounter_id", "pull_number", "start_timestamp")
            conflicts = [key for key in immutable if getattr(row, key) != values[key]]
            if conflicts:
                raise ValueError(f"pull source identity conflict for {', '.join(conflicts)}")
            for key in ("encounter_name", "end_timestamp", "state", "boss_percent"):
                value = values[key]
                setattr(row, key, value)
        self.session.flush()
        return row

    def upsert_pull(self, pull: PullIdentity, scope="live") -> PullIdentity:
        row = self._upsert_pull_row(pull, scope)
        return self._to_pull(row, row.report)

    def save_analysis(self, analysis: PullAnalysis, scope="live") -> PullCoachAnalysis:
        pull = self._upsert_pull_row(analysis.pull, scope)
        payload = {
            "pull": analysis.pull,
            "findings": analysis.findings,
            "mechanic_observations": analysis.mechanic_observations,
            "summary": analysis.summary,
        }
        fingerprint = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        analyzer = analysis.analyzer
        row = self.session.scalar(select(PullCoachAnalysis).where(
            PullCoachAnalysis.pull_id == pull.id,
            PullCoachAnalysis.analyzer_name == analyzer.analyzer_name,
            PullCoachAnalysis.analyzer_version == analyzer.analyzer_version,
            PullCoachAnalysis.result_fingerprint == fingerprint,
        ))
        if row is not None:
            return row
        row = PullCoachAnalysis(
            pull_id=pull.id, analyzer_name=analyzer.analyzer_name,
            analyzer_version=analyzer.analyzer_version, result_fingerprint=fingerprint,
            summary=_json_value(analysis.summary.values),
            mechanic_observations=_json_value(analysis.mechanic_observations),
        )
        self.session.add(row)
        self.session.flush()
        for finding in sorted(analysis.findings, key=lambda item: item.finding_id):
            stored = PullCoachFinding(
                analysis_id=row.id, finding_id=finding.finding_id,
                category=finding.category.value, severity=finding.severity.value,
                fact=_json_value(finding.fact), mechanic_id=finding.mechanic_id,
                actor_ids=list(finding.actor_ids),
                roles=[role.value for role in finding.roles],
                related_finding_ids=list(finding.related_finding_ids),
            )
            self.session.add(stored)
            self.session.flush()
            for evidence in sorted(finding.evidence, key=lambda item: item.evidence_id):
                self.session.add(PullCoachEvidence(
                    finding_row_id=stored.id, evidence_id=evidence.evidence_id,
                    event_ids=list(evidence.event_ids), description=evidence.description,
                ))
        self.session.flush()
        return row

    def list_pulls(self, report: RaidReportIdentity, scope="live") -> list[PullIdentity]:
        rows = self.session.execute(select(PullCoachPull, PullCoachReport).join(PullCoachReport).where(
            PullCoachReport.report_code == report.report_code,
            PullCoachReport.provider == report.source.provider,
            PullCoachReport.source_id == report.source.source_id,
            PullCoachReport.scope == scope,
        ).order_by(PullCoachPull.pull_number, PullCoachPull.start_timestamp,
                   PullCoachPull.fight_id)).all()
        return [self._to_pull(row, report) for row, report in rows]

    def list_findings_for_encounter(self, encounter_id: str, *, analyzer_name: str,
                                    analyzer_version: str, report: RaidReportIdentity | None = None,
                                    scope="live") -> list[tuple[PullIdentity, AnalysisProvenance, Finding]]:
        statement = (select(PullCoachPull, PullCoachFinding, PullCoachReport)
                     .join(PullCoachReport, PullCoachPull.report_id == PullCoachReport.id)
                     .join(PullCoachAnalysis, PullCoachAnalysis.pull_id == PullCoachPull.id)
                     .join(PullCoachFinding, PullCoachFinding.analysis_id == PullCoachAnalysis.id)
                     .where(PullCoachPull.encounter_id == encounter_id,
                            PullCoachReport.scope == scope))
        statement = statement.where(
            PullCoachAnalysis.analyzer_name == analyzer_name,
            PullCoachAnalysis.analyzer_version == analyzer_version,
        )
        if report is not None:
            statement = statement.where(
                PullCoachReport.report_code == report.report_code,
                PullCoachReport.provider == report.source.provider,
                PullCoachReport.source_id == report.source.source_id,
            )
        statement = statement.order_by(PullCoachPull.pull_number,
                                       PullCoachPull.start_timestamp,
                                       PullCoachFinding.finding_id,
                                       PullCoachAnalysis.analyzer_name,
                                       PullCoachAnalysis.analyzer_version)
        results = []
        for pull, finding, report in self.session.execute(statement).all():
            analysis = finding.analysis
            evidence = tuple(EvidenceReference(
                evidence_id=item.evidence_id,
                event_ids=tuple(item.event_ids),
                description=item.description,
            ) for item in sorted(finding.evidence, key=lambda item: item.evidence_id))
            domain_finding = Finding(
                finding_id=finding.finding_id,
                category=FindingCategory(finding.category),
                severity=Severity(finding.severity),
                fact=finding.fact,
                evidence=evidence,
                actor_ids=tuple(finding.actor_ids),
                roles=tuple(Role(role) for role in finding.roles),
                mechanic_id=finding.mechanic_id,
                related_finding_ids=tuple(finding.related_finding_ids),
            )
            results.append((self._to_pull(pull, report), AnalysisProvenance(
                analysis.analyzer_name, analysis.analyzer_version, analysis.result_fingerprint,
            ), domain_finding))
        return results
