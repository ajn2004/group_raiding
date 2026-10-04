"""SQLAlchemy storage models for the Pull Coach domain."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class CoachingProfile(Base):
    __tablename__ = "coaching_profiles"

    purpose: Mapped[str] = mapped_column(String(100), primary_key=True)
    active_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("coaching_profile_revisions.id", use_alter=True, name="fk_coaching_profile_active_revision"))
    revisions: Mapped[list["CoachingProfileRevision"]] = relationship(
        back_populates="profile", foreign_keys="CoachingProfileRevision.profile_purpose",
        cascade="all, delete-orphan", order_by="CoachingProfileRevision.revision")
    active_revision: Mapped["CoachingProfileRevision | None"] = relationship(
        foreign_keys=[active_revision_id], post_update=True)


class CoachingProfileRevision(Base):
    __tablename__ = "coaching_profile_revisions"
    __table_args__ = (UniqueConstraint("profile_purpose", "revision", name="uq_coaching_profile_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_purpose: Mapped[str] = mapped_column(ForeignKey("coaching_profiles.purpose", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(String, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(String, nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    provider_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(255))
    profile: Mapped[CoachingProfile] = relationship(back_populates="revisions", foreign_keys=[profile_purpose])


class CoachingSession(Base):
    """Durable provenance record for one coaching run and its conversation."""
    __tablename__ = "coaching_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("wipefest_fight_snapshots.id"), nullable=False)
    report_code: Mapped[str] = mapped_column(String(255), nullable=False)
    fight_id: Mapped[str] = mapped_column(String(100), nullable=False)
    encounter_id: Mapped[str] = mapped_column(String(255), nullable=False)
    audience: Mapped[str] = mapped_column(String(20), nullable=False)
    target_player_id: Mapped[str | None] = mapped_column(String(255))
    target_player_name: Mapped[str | None] = mapped_column(String(255))
    context_schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_context: Mapped[dict] = mapped_column(JSON, nullable=False)
    profile_revision_id: Mapped[int] = mapped_column(ForeignKey("coaching_profile_revisions.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_model: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    provider_response_id: Mapped[str | None] = mapped_column(String(255))
    actual_model: Mapped[str | None] = mapped_column(String(255))
    usage: Mapped[dict | None] = mapped_column(JSON)
    cost: Mapped[dict | None] = mapped_column(JSON)
    structured_response: Mapped[dict | None] = mapped_column(JSON)
    raw_response: Mapped[dict | str | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)
    messages: Mapped[list["CoachingSessionMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="CoachingSessionMessage.sequence")


class CoachingSessionMessage(Base):
    __tablename__ = "coaching_session_messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="uq_coaching_session_message_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("coaching_sessions.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    message_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    session: Mapped[CoachingSession] = relationship(back_populates="messages")


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
    profile_revision_id: Mapped[int | None] = mapped_column(ForeignKey("coaching_profile_revisions.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    rendered_output: Mapped[str | None] = mapped_column(String)
