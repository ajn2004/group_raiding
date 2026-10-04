"""Immutable Wipefest source fight snapshots."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WipefestFightSnapshot(Base):
    __tablename__ = "wipefest_fight_snapshots"
    __table_args__ = (UniqueConstraint("provider", "report_code", "fight_id", "group_id", "fingerprint",
                                      name="uq_wipefest_snapshot_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    report_code: Mapped[str] = mapped_column(String(255), nullable=False)
    fight_id: Mapped[str] = mapped_column(String(100), nullable=False)
    group_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_url: Mapped[str] = mapped_column(String, nullable=False)
    request_params: Mapped[dict] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_etag: Mapped[str | None] = mapped_column(String(500))
