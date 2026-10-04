import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as ORMSession

from app.db.models import Base
from app.db.models.wipefest import WipefestFightSnapshot
from app.web_requests.wipefest import (
    WipefestHTTPError, WipefestProvider, WipefestResponseError,
    WipefestSnapshotRepository, WipefestTransportError,
)


FIXTURE = Path(__file__).parents[1] / "fixtures/wipefest/reference_fight.json"


class Response:
    status_code = 200
    headers = {"ETag": '"reference-etag"'}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params, timeout))
        return Response(self.payload)


def test_fetch_persists_complete_fixture_immutably_and_deduplicates_fingerprint():
    payload = json.loads(FIXTURE.read_text())
    assert {
        "abilities", "eventConfigs", "events", "info", "insightConfigs",
        "insights", "playerValues", "raid", "report",
    }.issubset(payload)
    assert payload["info"]["id"] == 10
    session = Session(payload)
    provider = WipefestProvider(session=session, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    snapshot = provider.fetch_fight("j8wDLpCTaqhB7M1x", "10", "1507")

    assert snapshot.payload == payload
    assert session.calls[0][1] == {"markupFormat": "Markup", "group": "1507", "insightsOnly": "false"}
    assert all(0 < value <= 30 for value in session.calls[0][2])
    assert snapshot.request_url.startswith("https://api.wipefest.gg/report/")
    assert snapshot.response_etag == '"reference-etag"'

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with ORMSession(engine) as db:
        repository = WipefestSnapshotRepository(db)
        row1 = repository.persist(snapshot)
        row2 = repository.persist(provider.fetch_fight("j8wDLpCTaqhB7M1x", "10", "1507"))
        assert row1.id == row2.id
        reloaded = repository.get(row1.id)
        assert reloaded.payload == payload
        assert reloaded.fingerprint == snapshot.fingerprint

        changed = dict(payload, additiveField={"preserve": [1, 2]})
        newer = provider.snapshot_from_payload(snapshot, changed)
        row3 = repository.persist(newer)
        assert row3.id != row1.id
        assert db.scalar(select(WipefestFightSnapshot).where(WipefestFightSnapshot.id == row1.id)).payload == payload
        assert db.query(WipefestFightSnapshot).count() == 2
        assert repository.latest("j8wDLpCTaqhB7M1x", "10", "1507").id == row3.id


def test_provider_keeps_additive_unknown_fields():
    payload = json.loads(FIXTURE.read_text())
    payload["futureField"] = {"unknown": True}
    result = WipefestProvider(session=Session(payload)).fetch_fight("report", "10", "1507")
    assert result.payload["futureField"] == {"unknown": True}


def test_provider_maps_transport_http_and_json_failures():
    import requests
    import pytest

    class FailingSession:
        def __init__(self, error):
            self.error = error

        def get(self, *args, **kwargs):
            if isinstance(self.error, Exception):
                raise self.error
            return self.error

    with pytest.raises(WipefestTransportError):
        WipefestProvider(session=FailingSession(requests.Timeout())).fetch_fight("r", "1", "1507")

    http_error = Response({})
    http_error.status_code = 503
    with pytest.raises(WipefestHTTPError):
        WipefestProvider(session=FailingSession(http_error)).fetch_fight("r", "1", "1507")

    malformed = Response(None)
    malformed.json = lambda: (_ for _ in ()).throw(ValueError("not json"))
    with pytest.raises(WipefestResponseError):
        WipefestProvider(session=FailingSession(malformed)).fetch_fight("r", "1", "1507")
