from app.web_requests.warcraft_logs import WCLClient, WCLConfig, parse_report_code
from app.web_requests.warcraft_logs.client import EVENT_QUERY, REPORT_QUERY
from app.web_requests.warcraft_logs.snapshot import WCLSnapshot


def test_checked_in_graphql_queries_have_balanced_braces():
    for query in (REPORT_QUERY, EVENT_QUERY):
        depth = 0
        for char in query:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                assert depth >= 0
        assert depth == 0
def test_classic_defaults_and_explicit_endpoint():
    from app.web_requests.warcraft_logs.client import DEFAULT_ENDPOINT
    assert "classic.warcraftlogs.com" in DEFAULT_ENDPOINT
    assert parse_report_code("https://classic.warcraftlogs.com/reports/ABC123") == "ABC123"
    assert WCLConfig(endpoint="https://example.test/graphql").endpoint == "https://example.test/graphql"


def test_checked_in_snapshot_replays_and_round_trips(tmp_path):
    from pathlib import Path
    path = Path(__file__).parents[2] / "fixtures/warcraft_logs/reference_snapshot.json"
    snapshot = WCLSnapshot.load(path)
    client = WCLClient(WCLConfig())
    result = client.ingest_fight(snapshot, "REFERENCE01", 7)
    saved_path = tmp_path / "snapshot.json"
    snapshot.save(saved_path)
    assert client.ingest_fight(WCLSnapshot.load(saved_path), "REFERENCE01", 7) == result
    assert result.events[0].ability_name == "Reference Bolt"
    assert snapshot.report["masterData"]["abilities"][0] == {"gameID": 90, "name": "Reference Bolt"}
    assert "Synthetic representative WCL-shaped" in snapshot.to_dict().get("provenance", "") or \
        "Synthetic representative WCL-shaped" in path.read_text()


def test_actor_player_identity_comes_only_from_authoritative_wcl_type():
    from app.pull_coach.models import is_raid_player
    report = {"fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
                           "endTime": 400}],
              "masterData": {"actors": [
                  {"id": 1, "name": "Player", "type": "Player", "subType": "Mage"},
                  {"id": 2, "name": "NPC disguised by name", "type": "NPC", "subType": "Mage"},
                  {"id": 3, "name": "Pet", "type": "Pet", "subType": "Hunter"},
                  {"id": 4, "name": "Unknown", "type": "Environment"}], "abilities": []}}
    ingestion = WCLClient(WCLConfig()).ingest_fight(
        WCLSnapshot(report, {7: [{"data": [], "nextPageTimestamp": None}]}), "ABC123", 7)
    assert [is_raid_player(actor) for actor in ingestion.actors] == [True, False, False, False]
    assert ingestion.actors[0].player_name == "Player"


def test_boss_percent_uses_boss_percentage_not_fight_percentage():
    report = {"fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
        "endTime": 400, "bossPercentage": 37.2, "fightPercentage": 68.4}],
        "masterData": {"actors": [], "abilities": []}}
    result = WCLClient(WCLConfig()).ingest_fight(
        WCLSnapshot(report, {7: [{"data": [], "nextPageTimestamp": None}]}), "ABC123", 7)
    assert result.pull.boss_percent == 37.2


def test_interrupt_and_dispel_preserve_secondary_ability():
    report = {"fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
        "endTime": 400}], "masterData": {"actors": [], "abilities": [
            {"gameID": 1766, "name": "Kick"}, {"gameID": 12345, "name": "Shadow Bolt"},
            {"gameID": 4987, "name": "Cleanse"}, {"gameID": 67890, "name": "Curse of Doom"}]}}
    events = [
        {"type": "interrupt", "timestamp": 1, "abilityGameID": 1766,
         "extraAbilityGameID": 12345},
        {"type": "dispel", "timestamp": 2, "abilityGameID": 4987,
         "extraAbilityGameID": 67890},
    ]
    snapshot = WCLSnapshot(report, {7: [{"data": events, "nextPageTimestamp": None}]})
    interrupt, dispel = WCLClient(WCLConfig()).ingest_fight(snapshot, "ABC123", 7).events
    assert (interrupt.ability_id, interrupt.ability_name) == (1766, "Kick")
    assert interrupt.metadata["stopped_ability_id"] == 12345
    assert interrupt.metadata["stopped_ability_name"] == "Shadow Bolt"
    assert (dispel.ability_id, dispel.ability_name) == (4987, "Cleanse")
    assert dispel.metadata["stopped_ability_id"] == 67890
    assert dispel.metadata["stopped_ability_name"] == "Curse of Doom"


def test_numeric_ability_ids_are_canonicalized_for_catalog_lookups():
    report = {"fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
        "endTime": 400}], "masterData": {"actors": [],
        "abilities": [{"gameID": 90.0, "name": "Reference Bolt"}]}}
    snapshot = WCLSnapshot(report, {7: [{"data": [{"type": "cast", "timestamp": 1,
        "abilityGameID": 90}], "nextPageTimestamp": None}]})
    event = WCLClient(WCLConfig()).ingest_fight(snapshot, "ABC123", 7).events[0]
    assert event.ability_name == "Reference Bolt"


def test_event_ids_are_independent_of_pagination_and_ability_catalog():
    report = {"fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
        "endTime": 400}], "masterData": {"actors": [], "abilities": [{"gameID": 90, "name": "Blast"}]}}
    events = [{"type": "damage", "timestamp": 12, "abilityGameID": 90},
              {"type": "damage", "timestamp": 12, "abilityGameID": 999}]
    one = WCLSnapshot(report, {7: [{"data": events, "nextPageTimestamp": None}]})
    split = WCLSnapshot(report, {7: [{"data": events[:1], "nextPageTimestamp": 12},
                                    {"data": events[1:], "nextPageTimestamp": None}]})
    client = WCLClient(WCLConfig())
    a = client.ingest_fight(one, "ABC123", 7).events
    b = client.ingest_fight(split, "ABC123", 7).events
    assert a == b
    assert a[0].ability_name == "Blast"
    assert a[1].ability_id == 999 and a[1].ability_name is None


def test_snapshot_validation_is_explicit(tmp_path):
    import json
    import pytest
    from app.web_requests.warcraft_logs.errors import SnapshotError
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 1, "provider": "warcraftlogs", "report": [], "event_pages": []}))
    with pytest.raises(SnapshotError):
        WCLSnapshot.load(path)


def test_malformed_ability_catalog_fails_clearly():
    import pytest
    from app.web_requests.warcraft_logs.errors import MalformedResponse
    report = {"fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
        "endTime": 400}], "masterData": {"actors": [], "abilities": [{"id": 1}]}}
    snapshot = WCLSnapshot(report, {7: [{"data": [], "nextPageTimestamp": None}]})
    with pytest.raises(MalformedResponse, match="ability metadata"):
        WCLClient(WCLConfig()).ingest_fight(snapshot, "ABC123", 7)


def test_report_reference_parser():
    assert parse_report_code("ABC123") == "ABC123"
    assert parse_report_code("https://www.warcraftlogs.com/reports/ABC123#fight=2") == "ABC123"
    assert parse_report_code("https://classic.warcraftlogs.com/reports/ABC123") == "ABC123"
    for value in ("", "https://example.com/reports/ABC", "bad code"):
        try:
            parse_report_code(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid reference: {value}")


def test_null_report_is_report_unavailable():
    import pytest
    from app.web_requests.warcraft_logs.errors import ReportUnavailable
    class Transport:
        def graphql(self, query, variables):
            return {"data": {"reportData": {"report": None}}}
    with pytest.raises(ReportUnavailable):
        WCLClient(WCLConfig(), transport=Transport()).report_data("ABC123")


def test_snapshot_pagination_normalizes_stably():
    report = {"code": "ABC123", "startTime": 100, "endTime": 500,
              "fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
                          "endTime": 400, "kill": False, "inProgress": False,
                          "fightPercentage": 20}],
              "masterData": {"actors": [{"id": 1, "name": "Player", "type": "Player",
                                           "subType": "Mage"}]}}
    pages = [{"data": [{"type": "damage", "timestamp": 110, "sourceID": 1,
                        "targetID": 2, "abilityGameID": 90, "amount": 12}],
              "nextPageTimestamp": 120},
             {"data": [{"type": "mystery", "timestamp": 120, "sourceID": 2}],
              "nextPageTimestamp": None}]
    snapshot = WCLSnapshot(report, {7: pages})
    result = WCLClient(WCLConfig()).ingest_fight(snapshot, "https://www.warcraftlogs.com/reports/ABC123", 7)
    assert [event.timestamp for event in result.events] == [110, 120]
    assert result.events[1].event_type.value == "other"
    again = WCLClient(WCLConfig()).ingest_fight(snapshot, "ABC123", 7)
    assert result == again
    assert len({event.evidence_id for event in result.events}) == 2


def test_live_shaped_transport_matches_snapshot():
    report = {"code": "ABC123", "startTime": 100, "endTime": 500,
              "fights": [{"id": 7, "encounterID": 42, "name": "Boss", "startTime": 0,
                          "endTime": 400, "kill": True, "inProgress": False}],
              "masterData": {"actors": []}}
    page = {"data": [{"type": "death", "timestamp": 12}], "nextPageTimestamp": None}
    class Transport:
        def graphql(self, query, variables):
            return {"data": {"reportData": {"report": report}}}
        def events(self, code, start, end):
            return [page]
    client = WCLClient(WCLConfig(), transport=Transport())
    live = client.ingest_fight(None, "ABC123", 7)
    saved = client.ingest_fight(WCLSnapshot(report, {7: [page]}), "ABC123", 7)
    assert live == saved


def test_event_pagination_uses_next_page_timestamp_and_preserves_page_order():
    report = {"code": "ABC123", "fights": [{"id": 7, "encounterID": 42,
        "name": "Boss", "startTime": 0, "endTime": 400}], "masterData": {"actors": []}}
    pages = iter([
        {"data": [{"type": "cast", "timestamp": 20}], "nextPageTimestamp": 21},
        {"data": [{"type": "death", "timestamp": 20}], "nextPageTimestamp": 22},
        {"data": [{"type": "heal", "timestamp": 22}], "nextPageTimestamp": None},
    ])
    class Transport:
        cursors = []
        def graphql(self, query, variables):
            if "revision" in query:
                return {"data": {"reportData": {"report": report}}}
            self.cursors.append(variables["startTime"])
            return {"data": {"reportData": {"report": {"events": next(pages)}}}}
    transport = Transport()
    result = WCLClient(WCLConfig(), transport=transport).ingest_fight(None, "ABC123", 7)
    assert transport.cursors == [0, 21, 22]
    assert [e.event_type.value for e in result.events] == ["cast", "death", "heal"]
    assert [e.timestamp for e in result.events] == [20, 20, 22]


def test_non_advancing_pagination_fails_clearly():
    from app.web_requests.warcraft_logs.errors import PaginationError
    report = {"code": "ABC123", "fights": [{"id": 7, "encounterID": 42,
        "name": "Boss", "startTime": 0, "endTime": 400}], "masterData": {"actors": []}}
    class Transport:
        def graphql(self, query, variables):
            if "revision" in query:
                return {"data": {"reportData": {"report": report}}}
            return {"data": {"reportData": {"report": {"events": {
                "data": [], "nextPageTimestamp": variables["startTime"]}}}}}
    import pytest
    with pytest.raises(PaginationError):
        WCLClient(WCLConfig(), transport=Transport()).ingest_fight(None, "ABC123", 7)


def test_oauth_token_is_reused_then_refreshed_without_network(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.web_requests.warcraft_logs.client import _RequestsTransport
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    class Response:
        status_code = 200
        def __init__(self, count): self.count = count
        def json(self): return {"access_token": f"token-{self.count}", "expires_in": 3600}
    class Session:
        count = 0
        def post(self, url, **kwargs):
            assert kwargs["data"] == {"grant_type": "client_credentials"}
            self.count += 1
            return Response(self.count)
    session = Session()
    monkeypatch.setattr("app.web_requests.warcraft_logs.client.requests.Session", lambda: session)
    transport = _RequestsTransport(WCLConfig("id", "secret"), lambda: now[0])
    assert transport._headers()["Authorization"] == "Bearer token-1"
    assert transport._headers()["Authorization"] == "Bearer token-1"
    now[0] += timedelta(seconds=3550)
    assert transport._headers()["Authorization"] == "Bearer token-2"
    assert session.count == 2


def test_malformed_oauth_token_response_is_explicit(monkeypatch):
    import pytest
    from app.web_requests.warcraft_logs.client import _RequestsTransport
    from app.web_requests.warcraft_logs.errors import AuthenticationError
    class Response:
        status_code = 200
        def json(self): return {"access_token": "missing expiry"}
    class Session:
        def post(self, *args, **kwargs): return Response()
    monkeypatch.setattr("app.web_requests.warcraft_logs.client.requests.Session", Session)
    with pytest.raises(AuthenticationError):
        _RequestsTransport(WCLConfig("id", "secret"), lambda: __import__("datetime").datetime.now())._headers()


def test_http_auth_authorization_and_rate_limit_are_distinct(monkeypatch):
    from datetime import datetime, timezone
    import pytest
    from app.web_requests.warcraft_logs.client import _RequestsTransport
    from app.web_requests.warcraft_logs.errors import AuthenticationError, RateLimitError, ReportUnavailable

    class Response:
        def __init__(self, status, body=None): self.status_code, self.body = status, body or {}
        def json(self): return self.body
    class Session:
        def __init__(self, statuses): self.statuses, self.calls = list(statuses), []
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/oauth/token"):
                return Response(200, {"access_token": f"token-{len(self.calls)}", "expires_in": 3600})
            return Response(self.statuses.pop(0))

    for status, error in ((401, AuthenticationError), (403, ReportUnavailable), (429, RateLimitError)):
        statuses = [401, 401] if status == 401 else [status]
        session = Session(statuses)
        monkeypatch.setattr("app.web_requests.warcraft_logs.client.requests.Session", lambda: session)
        config = WCLConfig("id", "secret", endpoint="https://alternate.test/graphql")
        transport = _RequestsTransport(config, lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        with pytest.raises(error):
            transport.graphql("query {}", {})
        graphql_requests = [call for call in session.calls if call[0] == config.endpoint]
        assert len(graphql_requests) == (2 if status == 401 else 1)


def test_401_refreshes_token_once_and_explicit_endpoint_is_used(monkeypatch):
    from datetime import datetime, timezone
    from app.web_requests.warcraft_logs.client import _RequestsTransport
    class Response:
        def __init__(self, status, body=None): self.status_code, self.body = status, body or {}
        def json(self): return self.body
    class Session:
        def __init__(self): self.endpoint_calls = 0; self.urls = []
        def post(self, url, **kwargs):
            self.urls.append(url)
            if url.endswith("/oauth/token"):
                return Response(200, {"access_token": "token", "expires_in": 3600})
            self.endpoint_calls += 1
            return Response(401 if self.endpoint_calls == 1 else 200, {"data": {}})
    session = Session()
    monkeypatch.setattr("app.web_requests.warcraft_logs.client.requests.Session", lambda: session)
    config = WCLConfig("id", "secret", endpoint="https://alternate.test/graphql")
    _RequestsTransport(config, lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)).graphql("query {}", {})
    assert session.endpoint_calls == 2
    assert session.urls.count(config.endpoint) == 2


def test_legacy_controller_returns_raw_report_shape(monkeypatch):
    from app.web_requests.warcraft_logs.controller import WCLController
    raw_report = {"fights": [{"id": 1, "name": "Boss"}], "masterData": {"actors": []}}
    class Client:
        def report_data(self, reference): return raw_report
        class transport:
            @staticmethod
            def graphql(query, variables):
                return {"data": {"reportData": {"report": {"events": {"data": []}}}}}
    monkeypatch.setattr("app.web_requests.warcraft_logs.controller.WCLClient", lambda: Client())
    controller = WCLController()
    assert controller.get_log_data("ABC123") is raw_report
    assert controller.get_encounter_deaths("ABC123", 1, 2) == {"events": {"data": []}}
