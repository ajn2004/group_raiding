"""Deterministic factual summaries of saved Warcraft Logs snapshots."""
from collections import Counter, defaultdict


def inspect_snapshot(snapshot, *, fight=None, fight_ids=None, replay_id=None, ability=None, name=None, event_type=None,
                     death_window_ms=8000):
    report = snapshot.report
    actors = {str(a.get("id")): a for a in report.get("masterData", {}).get("actors", [])}
    abilities = defaultdict(set)
    for item in report.get("masterData", {}).get("abilities", []):
        abilities[str(item.get("gameID"))].add(item.get("name", "Unknown ability"))
    fights = {str(item.get("id")): item for item in report.get("fights", [])}
    ordered_ids = [str(fid) for fid in fight_ids] if fight_ids is not None else list(fights)
    selected = [fights[fid] for fid in ordered_ids if fid in fights and (fight is None or str(fight) == fid)]
    events = []
    for f in selected:
        for page in snapshot.event_pages.get(int(f["id"]), []):
            for event in page.get("data", []):
                events.append((f, event))
    counts = Counter(str(e.get("type", "unknown")).lower() for _, e in events)
    groups = defaultdict(list)
    for f, event in events:
        aid = event.get("abilityGameID", (event.get("ability") or {}).get("guid"))
        if aid is None and not (event.get("ability") or {}).get("name"):
            continue
        aname = (event.get("ability") or {}).get("name") or next(iter(sorted(abilities.get(str(aid), ()))), "Unknown ability")
        if ability is not None and str(ability) != str(aid):
            continue
        if name and name.casefold() not in aname.casefold():
            continue
        if event_type and str(event.get("type", "")).lower() != event_type.lower():
            continue
        groups[(str(aid) if aid is not None else "unknown", aname)].append((f, event))
    result = {"report_identity": report.get("code", "unknown"), "replay_identity": replay_id or report.get("code", "unknown"),
              "total_events": len(events), "event_type_counts": dict(sorted(counts.items())),
              "fights": [{"fight_id": f.get("id"), "encounter_id": f.get("encounterID"), "name": f.get("name"),
                          "state": "in_progress" if f.get("inProgress") else "kill" if f.get("kill") else "wipe",
                          "boss_percent": f.get("bossPercentage"), "start_time": f.get("startTime"), "end_time": f.get("endTime"),
                          "event_count": sum(len(p.get("data", [])) for p in snapshot.event_pages.get(int(f["id"]), []))}
                         for f in selected], "abilities": [], "deaths": []}
    for (aid, aname), items in sorted(groups.items(), key=lambda x: (x[0][1].casefold(), x[0][0])):
        type_counts, sources, targets, by_fight, variants = Counter(), Counter(), Counter(), defaultdict(Counter), Counter()
        damage = 0
        for f, e in items:
            typ = str(e.get("type", "unknown")).lower(); type_counts[typ] += 1; by_fight[str(f["id"])][typ] += 1
            source = actors.get(str(e.get("sourceID")), {})
            target = actors.get(str(e.get("targetID")), {})
            sources[(str(e.get("sourceID", "unknown")), source.get("name", "Unknown"), source.get("type", "Unknown"))] += 1
            variants[(typ, str(e.get("sourceID", "unknown")), source.get("name", "Unknown"), source.get("type", "Unknown"))] += 1
            targets[(str(e.get("targetID", "unknown")), target.get("name", "Unknown"))] += 1
            if typ == "damage": damage += e.get("amount", 0) or 0
        result["abilities"].append({"ability_id": aid, "name": aname, "event_types": dict(sorted(type_counts.items())),
             "variants": [{"event_type": typ, "source_actor_id": sid, "source_name": sname, "source_type": stype, "count": count}
                          for (typ, sid, sname, stype), count in sorted(variants.items())],
             "source_actors": [{"actor_id": x[0], "name": x[1], "type": x[2], "count": n} for x,n in sorted(sources.items())],
             "targets": [{"actor_id": x[0], "name": x[1], "count": n} for x,n in sorted(targets.items())],
             "event_count": len(items), "damage": damage,
             "per_fight": [{"fight_id": fid, "event_types": dict(sorted(cnt.items()))} for fid,cnt in sorted(by_fight.items(), key=lambda x: int(x[0]))]})
    for f, e in sorted(((f,e) for f,e in events if str(e.get("type", "")).lower() == "death"), key=lambda x:(x[0].get("id",0),x[1].get("timestamp",0))):
        ts=e.get("timestamp",0); history=[x for ff,x in events if ff.get("id")==f.get("id") and x.get("targetID")==e.get("targetID") and str(x.get("type", "")).lower()=="damage" and 0 <= ts-x.get("timestamp",ts) <= death_window_ms]
        result["deaths"].append({"fight_id":f.get("id"),"timestamp":ts,"target_id":e.get("targetID"),"pre_death_damage_window_ms":death_window_ms,
                                "damage_events":[{"timestamp":x.get("timestamp"),"ability_id":x.get("abilityGameID"),"source_id":x.get("sourceID"),"target_id":x.get("targetID"),"amount":x.get("amount")} for x in history]})
    return result


def render_human(data):
    lines=[f"Report: {data['report_identity']} · Replay: {data['replay_identity']}", f"Events: {data['total_events']}", f"Event types: {data['event_type_counts']}"]
    for f in data["fights"]:
        lines.append(f"Fight {f['fight_id']} · {f.get('name')} · {f['state']} · boss {f.get('boss_percent')}% · {f['event_count']} events · {f.get('start_time')}–{f.get('end_time')}")
    for a in data["abilities"]:
        lines.append(f"\n{a['name']}")
        for variant in a["variants"]:
            lines.append(f"  {a['ability_id']} {variant['event_type']:<14} source={variant['source_name']} ({variant['source_type']}) events={variant['count']}")
        lines.append("  targets: " + ", ".join(f"{x['name']}={x['count']}" for x in a["targets"]))
        lines.append(f"  total events={a['event_count']} damage={a['damage']}")
        lines.extend(f"  fight {x['fight_id']}: {x['event_types']}" for x in a["per_fight"])
    for d in data["deaths"]: lines.append(f"Death fight={d['fight_id']} at={d['timestamp']} target={d['target_id']} pre-death damage={len(d['damage_events'])} (last {d['pre_death_damage_window_ms']}ms)")
    return "\n".join(lines)
