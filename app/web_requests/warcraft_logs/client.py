"""WCL v2 transport, pagination, and Pull Coach ingestion boundary."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import urlparse

import requests

from app.config import WCL_CLIENT_ID, WCL_CLIENT_SECRET
from app.pull_coach.models import (Actor, EncounterIdentity, EventType, NormalizedEvent,
    PullIdentity, PullState, RaidReportIdentity, Role, SourceIdentity)
from .errors import (AuthenticationError, InvalidReportReference, MalformedResponse,
    PaginationError, RateLimitError, ReportUnavailable, TransportError)
from .snapshot import WCLSnapshot

DEFAULT_ENDPOINT = "https://classic.warcraftlogs.com/api/v2/client"
TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"

REPORT_QUERY = """query($reportCode:String!){reportData{report(code:$reportCode){code revision startTime endTime fights{id encounterID name difficulty kill startTime endTime inProgress bossPercentage fightPercentage friendlyPlayers} masterData{actors{id gameID type name server subType} abilities{gameID name}}}}}"""
EVENT_QUERY = """query($reportCode:String!,$startTime:Float!,$endTime:Float!,$limit:Int!,$fightIDs:[Int]){reportData{report(code:$reportCode){events(dataType:All,startTime:$startTime,endTime:$endTime,limit:$limit,fightIDs:$fightIDs){data nextPageTimestamp}}}}}"""


@dataclass(frozen=True)
class WCLConfig:
    client_id: str | None = WCL_CLIENT_ID
    client_secret: str | None = WCL_CLIENT_SECRET
    token_url: str = TOKEN_URL
    endpoint: str = DEFAULT_ENDPOINT
    token_refresh_margin_seconds: int = 60
    page_limit: int = 10000

    # The report URL identifies a report; endpoint selects the WCL product/API.
    # In particular, a www.warcraftlogs.com URL does not select Retail automatically.


@dataclass(frozen=True)
class FightIngestion:
    report: RaidReportIdentity
    pull: PullIdentity
    actors: tuple[Actor, ...]
    events: tuple[NormalizedEvent, ...]


def parse_report_code(reference: str) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise InvalidReportReference("report reference must be a report code or Warcraft Logs URL")
    value = reference.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in {
        "warcraftlogs.com", "www.warcraftlogs.com", "classic.warcraftlogs.com",
        "vanilla.warcraftlogs.com", "sod.warcraftlogs.com",
    }:
        raise InvalidReportReference(f"unsupported Warcraft Logs report reference: {reference!r}")
    match = re.fullmatch(r"/reports/([A-Za-z0-9_-]+)/?", parsed.path)
    if not match:
        raise InvalidReportReference(f"URL does not contain a supported report path: {reference!r}")
    return match.group(1)


def _canonical_ability_id(value):
    """Canonicalize numeric WCL ability IDs while retaining opaque IDs safely."""
    if isinstance(value, bool) or value is None:
        return value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(value)


class _RequestsTransport:
    def __init__(self, config: WCLConfig, clock):
        self.config, self.clock = config, clock
        self.session = requests.Session()
        self.token = None
        self.expires_at = None

    def _authenticate(self):
        if not self.config.client_id or not self.config.client_secret:
            raise AuthenticationError("WCL client credentials are not configured")
        try:
            response = self.session.post(self.config.token_url,
                data={"grant_type": "client_credentials"},
                auth=(self.config.client_id, self.config.client_secret), timeout=30)
            if response.status_code >= 400:
                raise AuthenticationError(f"WCL authentication failed (HTTP {response.status_code})")
            body = response.json()
            token, expires = body["access_token"], float(body["expires_in"])
            if not isinstance(token, str) or not token or expires <= 0:
                raise ValueError("invalid token fields")
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("WCL authentication response was invalid") from exc
        self.token = token
        self.expires_at = self.clock() + timedelta(seconds=expires)

    def _headers(self):
        if self.token is None or self.clock() >= self.expires_at - timedelta(
                seconds=self.config.token_refresh_margin_seconds):
            self._authenticate()
        return {"Authorization": f"Bearer {self.token}"}

    def graphql(self, query: str, variables: dict[str, Any]):
        try:
            response = self.session.post(self.config.endpoint, json={"query": query, "variables": variables},
                                         headers=self._headers(), timeout=60)
            if response.status_code == 401:
                self.token = self.expires_at = None
                response = self.session.post(self.config.endpoint,
                    json={"query": query, "variables": variables}, headers=self._headers(), timeout=60)
                if response.status_code == 401:
                    self.token = self.expires_at = None
                    raise AuthenticationError("WCL authentication failed (HTTP 401)")
            if response.status_code == 403:
                raise ReportUnavailable("WCL report is inaccessible with public client credentials")
            if response.status_code == 429:
                raise RateLimitError("WCL rate limit exceeded")
            if response.status_code >= 400:
                raise TransportError(f"WCL request failed (HTTP {response.status_code})")
            body = response.json()
        except (RateLimitError, ReportUnavailable, TransportError, AuthenticationError):
            raise
        except Exception as exc:
            raise TransportError("WCL request could not be completed") from exc
        if not isinstance(body, dict):
            raise MalformedResponse("WCL returned a non-object GraphQL response")
        if body.get("errors"):
            message = str(body["errors"][0].get("message", "GraphQL error"))
            if "rate" in message.lower() and "limit" in message.lower():
                raise RateLimitError("WCL rate limit exceeded")
            raise MalformedResponse(f"WCL GraphQL error: {message[:200]}")
        return body


class WCLClient:
    def __init__(self, config: WCLConfig | None = None, transport=None, clock=None):
        self.config = config or WCLConfig()
        self.transport = transport or _RequestsTransport(self.config, clock or (lambda: datetime.now(timezone.utc)))

    def report_data(self, reference: str):
        code = parse_report_code(reference)
        try:
            body = self.transport.graphql(REPORT_QUERY, {"reportCode": code})
            report = body["data"]["reportData"]["report"]
        except (ReportUnavailable, RateLimitError, TransportError, AuthenticationError, MalformedResponse):
            raise
        except Exception as exc:
            raise MalformedResponse(f"malformed report response for {code}") from exc
        if report is None:
            raise ReportUnavailable(f"report {code} was not found or is private; public credentials cannot access it")
        return report

    def _event_pages(self, report_code: str, fight: dict, snapshot=None):
        if snapshot is not None:
            try:
                pages = snapshot.event_pages[int(fight["id"])]
            except (KeyError, TypeError, ValueError) as exc:
                raise MalformedResponse(f"snapshot has no pages for fight {fight.get('id')}") from exc
            return pages
        if hasattr(self.transport, "events"):
            return self.transport.events(report_code, fight["startTime"], fight["endTime"])
        pages, cursor, seen = [], fight["startTime"], set()
        while True:
            variables = {"reportCode": report_code, "startTime": cursor,
                         "endTime": fight["endTime"], "limit": self.config.page_limit,
                         "fightIDs": [int(fight["id"])]}
            try:
                body = self.transport.graphql(EVENT_QUERY, variables)
                result = body["data"]["reportData"]["report"]["events"]
                data = result["data"]
                if not isinstance(data, list): raise TypeError("events data is not a list")
            except (ReportUnavailable, RateLimitError, TransportError, AuthenticationError, MalformedResponse):
                raise
            except Exception as exc:
                raise MalformedResponse(f"malformed event response for fight {fight['id']}") from exc
            pages.append({"data": data, "nextPageTimestamp": result.get("nextPageTimestamp")})
            nxt = result.get("nextPageTimestamp")
            if nxt is None: break
            if nxt in seen or (cursor is not None and nxt <= cursor):
                raise PaginationError(f"event pagination did not advance for fight {fight['id']}")
            seen.add(nxt)
            cursor = nxt
        return pages

    def ingest_fight(self, snapshot: WCLSnapshot | None, reference: str, fight_id: int | str) -> FightIngestion:
        code = parse_report_code(reference)
        report_data = snapshot.report if snapshot is not None else self.report_data(code)
        try:
            fights = report_data["fights"]
            fight = next(item for item in fights if str(item["id"]) == str(fight_id))
        except (KeyError, TypeError, StopIteration) as exc:
            raise ReportUnavailable(f"fight {fight_id} not found in report {code}") from exc
        try:
            actors_raw = report_data["masterData"]["actors"]
            actors = tuple(Actor(actor_id=f"wcl:{a['id']}", name=a["name"],
                player_name=a["name"] if a.get("type") == "Player" else None,
                class_name=a.get("subType") if a.get("type") == "Player" else None,
                source=SourceIdentity("warcraftlogs", str(a["id"]))) for a in actors_raw)
            actor_ids = {str(a["id"]): f"wcl:{a['id']}" for a in actors_raw}
            encounter_id = str(fight.get("encounterID") or fight["id"])
            encounter = EncounterIdentity(encounter_id, fight.get("name") or "Unknown encounter")
            state = PullState.IN_PROGRESS if fight.get("inProgress") else PullState.KILL if fight.get("kill") else PullState.WIPE
            pull = PullIdentity(RaidReportIdentity(SourceIdentity("warcraftlogs", code), code), encounter,
                str(fight["id"]), sum(1 for f in fights if f["startTime"] <= fight["startTime"] and
                    str(f.get("encounterID")) == str(fight.get("encounterID"))), fight["startTime"],
                fight.get("endTime"), state, fight.get("bossPercentage"))
        except (KeyError, TypeError, ValueError) as exc:
            raise MalformedResponse(f"malformed fight or actor metadata for report {code}") from exc
        pages = self._event_pages(code, fight, snapshot)
        events = []
        ability_catalog = report_data.get("masterData", {}).get("abilities", [])
        try:
            if not isinstance(ability_catalog, list):
                raise TypeError("abilities must be a list")
            ability_names = {}
            for item in ability_catalog:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    raise ValueError("ability entries require a name")
                ability_id = item.get("gameID")
                if ability_id is None:
                    raise ValueError("ability entries require an ID")
                ability_names[_canonical_ability_id(ability_id)] = item["name"]
        except (AttributeError, TypeError, KeyError, ValueError) as exc:
            raise MalformedResponse("malformed ability metadata in report") from exc
        event_index = 0
        for page_no, page in enumerate(pages):
            for event_no, raw in enumerate(page.get("data", [])):
                try:
                    if "timestamp" not in raw or "type" not in raw:
                        raise ValueError("event requires timestamp and type")
                    kind = {"damage": EventType.DAMAGE, "heal": EventType.HEAL,
                        "cast": EventType.CAST, "death": EventType.DEATH,
                        "combatantinfo": EventType.OTHER, "interrupt": EventType.INTERRUPT,
                        "dispel": EventType.DISPEL, "resourcechange": EventType.RESOURCE}.get(raw["type"].lower(), EventType.OTHER)
                    ability = raw.get("ability") or {}
                    extra_ability = raw.get("extraAbility") or {}
                    flags = frozenset(key for key in ("tick", "sourceIsFriendly", "targetIsFriendly") if raw.get(key))
                    ability_id = raw.get("abilityGameID", ability.get("guid"))
                    ability_name = ability.get("name") or ability_names.get(_canonical_ability_id(ability_id))
                    stopped_id = raw.get("extraAbilityGameID", extra_ability.get("guid"))
                    stopped_name = (extra_ability.get("name") or
                                    ability_names.get(_canonical_ability_id(stopped_id))) if stopped_id is not None else None
                    metadata = {"source_event_type": raw["type"]}
                    if raw.get("hitType") is not None:
                        metadata["hit_type"] = raw["hitType"]
                    if raw["type"].lower() in ("interrupt", "dispel") and stopped_id is not None:
                        metadata.update({"stopped_ability_id": stopped_id,
                                         "stopped_ability_name": stopped_name})
                    events.append(NormalizedEvent(int(raw["timestamp"]), kind,
                        f"wcl:{code}:{fight['id']}:{raw['timestamp']}:{event_index}",
                        actor_ids.get(str(raw.get("sourceID"))), actor_ids.get(str(raw.get("targetID"))),
                        ability_id, ability_name,
                        raw.get("amount"), raw.get("absorbed"), raw.get("overkill"), flags,
                        metadata))
                    event_index += 1
                except (TypeError, ValueError, AttributeError) as exc:
                    raise MalformedResponse(f"malformed event at page {page_no}, index {event_no}") from exc
        return FightIngestion(RaidReportIdentity(SourceIdentity("warcraftlogs", code), code), pull, actors, tuple(events))

    def snapshot(self, reference: str, fight_id: int | str) -> WCLSnapshot:
        code = parse_report_code(reference)
        report = self.report_data(code)
        fight = next((f for f in report["fights"] if str(f["id"]) == str(fight_id)), None)
        if fight is None: raise ReportUnavailable(f"fight {fight_id} not found in report {code}")
        return WCLSnapshot(report, {int(fight["id"]): self._event_pages(code, fight)})
