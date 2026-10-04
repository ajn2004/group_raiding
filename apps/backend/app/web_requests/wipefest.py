"""Full-response Wipefest fight ingestion and immutable source snapshot storage."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Protocol
from urllib.parse import quote

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.wipefest import WipefestFightSnapshot

BASE_URL = "https://api.wipefest.gg"


class WipefestProviderError(Exception):
    """Base error for Wipefest boundary failures."""


class WipefestTransportError(WipefestProviderError):
    pass


class WipefestHTTPError(WipefestProviderError):
    pass


class WipefestResponseError(WipefestProviderError):
    pass


class FightSnapshotProvider(Protocol):
    def fetch_fight(self, report_code: str, fight_id: str, group: str) -> "FightSnapshot": ...


@dataclass(frozen=True)
class FightSnapshot:
    report_code: str
    fight_id: str
    group_id: str
    request_url: str
    request_params: dict[str, str]
    fetched_at: datetime
    payload: dict[str, Any]
    fingerprint: str
    response_status: int | None = None
    response_etag: str | None = None


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class WipefestProvider:
    def __init__(self, *, session=None, clock=None, endpoint=BASE_URL, timeout=(5, 30)):
        self.session = session or requests.Session()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def fetch_fight(self, report_code: str, fight_id: str, group: str) -> FightSnapshot:
        params = {"markupFormat": "Markup", "group": str(group), "insightsOnly": "false"}
        url = f"{self.endpoint}/report/{quote(str(report_code), safe='')}/fight/{quote(str(fight_id), safe='')}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise WipefestTransportError("Wipefest request could not be completed") from exc
        if response.status_code >= 400:
            raise WipefestHTTPError(f"Wipefest request failed (HTTP {response.status_code})")
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise WipefestResponseError("Wipefest returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise WipefestResponseError("Wipefest returned a non-object fight response")
        return FightSnapshot(str(report_code), str(fight_id), str(group), url, params,
            self.clock(), payload, _fingerprint(payload), response.status_code,
            response.headers.get("ETag"))

    @staticmethod
    def snapshot_from_payload(snapshot: FightSnapshot, payload: dict[str, Any]) -> FightSnapshot:
        return FightSnapshot(snapshot.report_code, snapshot.fight_id, snapshot.group_id,
            snapshot.request_url, snapshot.request_params, snapshot.fetched_at, payload,
            _fingerprint(payload), snapshot.response_status, snapshot.response_etag)


class WipefestSnapshotRepository:
    """Append-only source snapshot persistence; equal canonical payloads are idempotent."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, snapshot_id: int) -> WipefestFightSnapshot | None:
        """Load a persisted snapshot by its stable database identifier."""
        return self.session.get(WipefestFightSnapshot, snapshot_id)

    def latest(self, report_code: str, fight_id: str, group_id: str) -> WipefestFightSnapshot | None:
        """Load the newest stored source version for a fight and group."""
        return self.session.scalar(select(WipefestFightSnapshot).where(
            WipefestFightSnapshot.provider == "wipefest",
            WipefestFightSnapshot.report_code == report_code,
            WipefestFightSnapshot.fight_id == fight_id,
            WipefestFightSnapshot.group_id == group_id,
        ).order_by(WipefestFightSnapshot.fetched_at.desc(), WipefestFightSnapshot.id.desc()).limit(1))

    def persist(self, snapshot: FightSnapshot) -> WipefestFightSnapshot:
        row = self.session.scalar(select(WipefestFightSnapshot).where(
            WipefestFightSnapshot.provider == "wipefest",
            WipefestFightSnapshot.report_code == snapshot.report_code,
            WipefestFightSnapshot.fight_id == snapshot.fight_id,
            WipefestFightSnapshot.group_id == snapshot.group_id,
            WipefestFightSnapshot.fingerprint == snapshot.fingerprint,
        ))
        if row is not None:
            from app.players.linkage import observe_snapshot
            observe_snapshot(self.session, row)
            return row
        row = WipefestFightSnapshot(provider="wipefest", report_code=snapshot.report_code,
            fight_id=snapshot.fight_id, group_id=snapshot.group_id,
            request_url=snapshot.request_url, request_params=snapshot.request_params,
            fetched_at=snapshot.fetched_at, payload=snapshot.payload,
            fingerprint=snapshot.fingerprint, response_status=snapshot.response_status,
            response_etag=snapshot.response_etag)
        self.session.add(row)
        self.session.flush()
        from app.players.linkage import observe_snapshot
        observe_snapshot(self.session, row)
        return row
