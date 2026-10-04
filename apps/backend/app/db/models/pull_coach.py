"""SQLAlchemy storage models for the Pull Coach domain."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PullCoachReport(Base):
    __tablename__ = "pull_coach_reports"
    __table_args__ = (UniqueConstraint("scope", "provider", "report_code", name="uq_pc_report_scope_provider_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(255), nullable=False, default="live")
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    report_code: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    pulls: Mapped[list["PullCoachPull"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class PullCoachPull(Base):
    __tablename__ = "pull_coach_pulls"
    __table_args__ = (UniqueConstraint("report_id", "fight_id", name="uq_pc_pull_report_fight"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("pull_coach_reports.id", ondelete="CASCADE"), nullable=False)
    encounter_id: Mapped[str] = mapped_column(String(255), nullable=False)
    encounter_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fight_id: Mapped[str] = mapped_column(String(255), nullable=False)
    pull_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_timestamp: Mapped[int] = mapped_column(Integer, nullable=False)
    end_timestamp: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    boss_percent: Mapped[float | None] = mapped_column(Float)
    report: Mapped[PullCoachReport] = relationship(back_populates="pulls")
    analyses: Mapped[list["PullCoachAnalysis"]] = relationship(back_populates="pull", cascade="all, delete-orphan")


class PullCoachAnalysis(Base):
    __tablename__ = "pull_coach_analyses"
    __table_args__ = (UniqueConstraint("pull_id", "analyzer_name", "analyzer_version", "result_fingerprint", name="uq_pc_analysis_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pull_id: Mapped[int] = mapped_column(ForeignKey("pull_coach_pulls.id", ondelete="CASCADE"), nullable=False)
    analyzer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(255), nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    mechanic_observations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    pull: Mapped[PullCoachPull] = relationship(back_populates="analyses")
    findings: Mapped[list["PullCoachFinding"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")


class PullCoachFinding(Base):
    __tablename__ = "pull_coach_findings"
    __table_args__ = (UniqueConstraint("analysis_id", "finding_id", name="uq_pc_finding_analysis_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("pull_coach_analyses.id", ondelete="CASCADE"), nullable=False)
    finding_id: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    fact: Mapped[dict] = mapped_column(JSON, nullable=False)
    mechanic_id: Mapped[str | None] = mapped_column(String(255))
    actor_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    roles: Mapped[list] = mapped_column(JSON, nullable=False)
    related_finding_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    analysis: Mapped[PullCoachAnalysis] = relationship(back_populates="findings")
    evidence: Mapped[list["PullCoachEvidence"]] = relationship(back_populates="finding", cascade="all, delete-orphan")


class PullCoachEvidence(Base):
    __tablename__ = "pull_coach_evidence"
    __table_args__ = (UniqueConstraint("finding_row_id", "evidence_id", name="uq_pc_evidence_finding_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_row_id: Mapped[int] = mapped_column(ForeignKey("pull_coach_findings.id", ondelete="CASCADE"), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    finding: Mapped[PullCoachFinding] = relationship(back_populates="evidence")


class CoachingOutput(Base):
    __tablename__ = "pull_coach_coaching_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("pull_coach_analyses.id", ondelete="CASCADE"), nullable=False)
    generator: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    template_version: Mapped[str | None] = mapped_column(String(255))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    rendered_output: Mapped[str | None] = mapped_column(String)
