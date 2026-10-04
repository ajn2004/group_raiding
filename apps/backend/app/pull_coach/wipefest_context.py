"""Deterministic, compact coaching contexts derived from persisted Wipefest snapshots."""
from __future__ import annotations

import re
import math
from typing import Any

CONTEXT_SCHEMA_VERSION = 1


def _plain(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"\{\[(?:image|url|style)=[^]]*\]\s*", "", text)
    text = text.replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def _pick(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in fields if key in value and isinstance(value[key], (str, int, float, bool, type(None)))
            and not (isinstance(value[key], float) and not math.isfinite(value[key]))}


_VALUE_SCALARS = ("totalHits", "totalDamage", "averageDuration", "averageTimestamp", "totalEvents", "frequency", "damage", "duration", "timestamp", "value", "count")
_PLAYER_FIELDS = ("frequency", "hits", "damage", "duration", "timestamp", "timestamps", "value", "count")


def _values(value: Any) -> dict[str, Any]:
    """Allowlist compact insight aggregates and player evidence, never provider rendering data."""
    if not isinstance(value, dict):
        return {}
    result = _pick(value, _VALUE_SCALARS)
    timestamps = value.get("timestamps")
    if isinstance(timestamps, list):
        result["timestamps"] = [v for v in timestamps if isinstance(v, (int, float)) and not isinstance(v, bool)
                                and (not isinstance(v, float) or math.isfinite(v))]
    players_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in value.items():
        if not (key.startswith("playersAnd") and isinstance(rows, list)):
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("player"), dict):
                continue
            person = row["player"]
            record = _pick(person, ("id", "guid", "name"))
            record.update(_pick(row, _PLAYER_FIELDS))
            identity = ("id", str(record["id"])) if record.get("id") is not None else ("guid", str(record.get("guid")))
            if identity[1] == "None":
                continue
            existing = players_by_key.setdefault(identity, {})
            existing.update({field: item for field, item in record.items() if item is not None})
    if players_by_key:
        result["players"] = list(players_by_key.values())
    return result


def _interval(value: Any) -> dict[str, Any]:
    return _pick(value, ("unit", "startUnit", "endUnit", "startTimestamp", "endTimestamp"))


def _identity(insight: dict[str, Any]) -> dict[str, Any]:
    group, insight_id = insight.get("group"), insight.get("id")
    return {"key": f"{group}:{insight_id}", "group": group, "id": insight_id,
            "interval": _interval(insight.get("interval"))}


def _stats(items: Any) -> list[dict[str, Any]]:
    fields = ("name", "value", "percentile", "unscaledValue")
    return [_pick(item, fields) for item in items or [] if isinstance(item, dict)] if isinstance(items, list) else []


def _insight(insight: dict[str, Any]) -> dict[str, Any]:
    stats_players = []
    for row in insight.get("statisticsForPlayers", []) if isinstance(insight.get("statisticsForPlayers"), list) else []:
        if isinstance(row, dict):
            stats_players.append({"playerId": row.get("playerId"), "statistics": _stats(row.get("statistics"))})
    return {"identity": _identity(insight), "title": _plain(insight.get("title")),
            "details": _plain(insight.get("details")), "major": insight.get("major"),
            "weight": insight.get("weight"), "statistics": _stats(insight.get("statistics")),
            "aggregatedStatistics": _stats(insight.get("aggregatedStatistics")),
            "statisticsForPlayers": stats_players, "values": _values(insight.get("values"))}


def _source(snapshot: Any) -> dict[str, Any]:
    return {"provider": snapshot.provider, "snapshotId": snapshot.id, "reportCode": snapshot.report_code,
            "fightId": str(snapshot.fight_id), "groupId": snapshot.group_id}


def _fight(payload: dict[str, Any], snapshot: Any) -> dict[str, Any]:
    info = payload.get("info") or {}
    start, end = info.get("start_time"), info.get("end_time")
    return {"reportCode": snapshot.report_code, "reportId": (payload.get("report") or {}).get("id"),
            "fightId": str(snapshot.fight_id), "encounterId": info.get("boss"), "encounterName": _plain(info.get("name")),
            "difficulty": info.get("difficulty"), "result": "kill" if info.get("kill") else "wipe",
            "durationMs": max(0, end-start) if isinstance(start, (int,float)) and isinstance(end,(int,float)) else None,
            "bossPercentage": info.get("bossPercentage"), "fightPercentage": info.get("fightPercentage")}


def _player(player: dict[str, Any]) -> dict[str, Any]:
    spec = player.get("specialization") or {}
    return {"playerId": player.get("actorId", player.get("id")), "name": player.get("name"),
            "class": player.get("className"), "spec": spec.get("name"), "role": spec.get("role"),
            "itemLevel": player.get("itemLevel"), "server": player.get("server"), "region": player.get("region")}


def _snapshot(snapshot: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Accept the persisted ORM snapshot (payload and provenance travel together)."""
    return snapshot.payload, _source(snapshot)


def build_fight_coaching_context(snapshot: Any) -> dict[str, Any]:
    payload, source = _snapshot(snapshot)
    insights = [_insight(i) for i in payload.get("insights", []) or []
                if isinstance(i, dict) and i.get("show", True) is True
                and (i.get("interval") or {}).get("unit") == "EntireFight"]
    roster = [_player(p) for p in payload.get("raid", {}).get("players", []) or [] if isinstance(p, dict)]
    roster.sort(key=lambda p: (str(p.get("playerId")), str(p.get("name"))))
    return {"context_schema_version": CONTEXT_SCHEMA_VERSION, "fight": _fight(payload, snapshot),
            "roster": roster, "insights": insights, "source": source}


def build_player_coaching_context(snapshot: Any, *, player_id: int | str) -> dict[str, Any]:
    payload, source = _snapshot(snapshot)
    player_key = str(player_id)
    player = next((p for p in payload.get("raid", {}).get("players", []) or []
                   if str(p.get("actorId", p.get("id"))) == player_key or str(p.get("id")) == player_key
                   or str(p.get("name", "")).casefold() == player_key.casefold()), None)
    if player is None:
        raise ValueError(f"Wipefest player {player_id!r} is not present in the snapshot roster")
    actor_key = str(player.get("actorId", player.get("id")))
    evaluation = next((entry for entry in payload.get("playerValues", []) or []
                       if str(entry.get("playerId")) == actor_key
                       and (entry.get("interval") or {}).get("unit") == "EntireFight"), None)
    values = []
    if evaluation:
        interval = _interval(evaluation.get("interval"))
        for value in evaluation.get("values", []) or []:
            if isinstance(value, dict):
                normalized = _pick(value, ("insightGroup", "insightId", "value", "weight", "weightedValue", "isBonus", "statisticName", "statisticUnscaledValue", "frequency"))
                normalized["interval"] = interval
                values.append(normalized)
    identities = {(str(v.get("insightGroup")), str(v.get("insightId")), tuple(sorted(v["interval"].items()))) for v in values}
    evidence_identities = set()
    for insight in payload.get("insights", []) or []:
        if not isinstance(insight, dict) or not insight.get("show", True) or (insight.get("interval") or {}).get("unit") != "EntireFight":
            continue
        for record in _values(insight.get("values")).get("players", []):
            if str(record.get("id")) == actor_key or str(record.get("guid")) == str(player.get("id")):
                ident = _identity(insight)
                evidence_identities.add((str(ident.get("group")), str(ident.get("id")), tuple(sorted(ident["interval"].items()))))
    metadata = []
    for i in payload.get("insights", []) or []:
        if not isinstance(i, dict) or not i.get("show", True) or (i.get("interval") or {}).get("unit") != "EntireFight":
            continue
        ident = _identity(i)
        key = (str(ident.get("group")), str(ident.get("id")), tuple(sorted(ident["interval"].items())))
        has_player_value_identity = any(item[:2] == key[:2] for item in identities)
        if key in identities or (key in evidence_identities and not has_player_value_identity):
            item = _insight(i)
            item["statisticsForPlayers"] = [r for r in item["statisticsForPlayers"] if str(r.get("playerId")) == actor_key]
            metadata.append(item)
    player_evidence = []
    for raw_insight in payload.get("insights", []) or []:
        if not isinstance(raw_insight, dict) or not raw_insight.get("show", True) or (raw_insight.get("interval") or {}).get("unit") != "EntireFight":
            continue
        ident = _identity(raw_insight)
        for record in _values(raw_insight.get("values")).get("players", []):
            if str(record.get("id")) == actor_key or str(record.get("guid")) == str(player.get("id")):
                evidence = {"insight": f"{ident.get('group')}:{ident.get('id')}"}
                evidence.update({key: record[key] for key in _PLAYER_FIELDS if key in record})
                player_evidence.append(evidence)
    result = {"context_schema_version": CONTEXT_SCHEMA_VERSION, "fight": _fight(payload, snapshot),
              "player": _player(player), "playerValues": sorted(values, key=lambda v: (str(v.get("insightGroup")), str(v.get("insightId")), str(v.get("statisticName")))),
              "insights": metadata, "playerEvidence": player_evidence, "source": source}
    if evaluation:
        result["evaluation"] = {key: evaluation.get(key) for key in ("totalValue", "totalBonus", "fightDurationFractionUntilFirstDeath")}
    return result
