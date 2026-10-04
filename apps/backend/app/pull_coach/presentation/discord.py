"""Single deterministic presenter shared by live Discord and replay."""
from app.pull_coach.models import PullState
from .models import DiscordEmbedField, DiscordEmbedPayload, DiscordMessagePayload


def _clip(value, limit):
    text = str(value or "")
    return text if len(text) <= limit else text[:max(0, limit - 1)].rstrip() + "…"


def _candidate(candidate):
    return candidate.text


def _duration(pull):
    if pull.end_timestamp is None:
        return None
    seconds = max(0, (pull.end_timestamp - pull.start_timestamp) // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


class PullCoachPresenter:
    def present(self, result):
        if not hasattr(result, "selected_pull"):
            return _present_coaching_run(result)
        pull, public = result.selected_pull, result.coaching.public
        duration = _duration(pull)
        if pull.state == PullState.KILL:
            status = "Kill"
            if result.historical_context is not None and pull.boss_percent is not None:
                status += f" · Boss {pull.boss_percent:g}%"
        else:
            status = "Wipe" + (f" · {pull.boss_percent:g}% remaining" if pull.boss_percent is not None else "")
        if duration:
            status += f" · {duration}"
        identity = f"Pull {pull.pull_number} · Fight {pull.fight_id} · {status}"
        historical = result.historical_context
        if historical is not None:
            identity = f"Historical sample · {historical.completed_pull_count} completed pulls analyzed\nTarget: {identity}"
        fields = []
        def add(name, values):
            values = [_candidate(value) for value in values if value and value.text.strip()]
            if values:
                fields.append(DiscordEmbedField(name, _clip("\n".join(f"• {v}" for v in values), 1024)))
        add("Primary failure", (public.primary_failure,))
        add("Next-pull priorities", public.next_pull_priorities[:3])
        add("What improved", public.improvements)
        add("DPS", public.dps_actions)
        add("Healers", public.healer_actions)
        add("Tanks", public.tank_actions)
        add("Raid", public.raid_actions)
        details = _details(result)
        # Calculate against final clipped aggregate text, as Discord does.
        title = _clip(f"Historical Pull Coach — {pull.encounter.name}" if historical is not None
                      else f"Pull Coach — {pull.encounter.name}", 256)
        description = _clip(identity, 4096)
        footer = _clip("Pull Coach", 2048)
        base = len(title) + len(description) + len(result.source_url) + len(footer)
        # Respect aggregate Discord text budget; lower-priority fields are dropped first.
        kept = []
        for field in fields:
            if len(kept) >= 25:
                break
            candidate = kept + [field]
            if base + sum(len(f.name) + len(f.value) for f in candidate) <= 6000:
                kept.append(field)
        return DiscordMessagePayload(DiscordEmbedPayload(
            title, description, result.source_url, tuple(kept), footer), details)


def _present_coaching_run(result):
    """Small source-neutral presentation until the richer coaching UI lands."""
    response = result.coaching if isinstance(result.coaching, dict) else {}
    recommendations = response.get("recommendations", [])
    lines = [str(item.get("text", "")).strip() for item in recommendations
             if isinstance(item, dict) and str(item.get("text", "")).strip()]
    fields = ()
    if lines:
        fields = (DiscordEmbedField("Coaching recommendations",
                                    _clip("\n".join(f"• {line}" for line in lines), 1024)),)
    description = f"{result.encounter_name} · Fight {result.fight_id} · {result.source.title()} source"
    return DiscordMessagePayload(DiscordEmbedPayload(
        _clip(f"Pull Coach — {result.encounter_name}", 256), _clip(description, 4096),
        result.source_url, fields), "\n".join(lines) or "No coaching recommendations.")


def _details(result):
    lines = []
    for finding in result.analysis.findings:
        if len(lines) >= 30:
            break
        mechanics = {key: value for key, value in result.coaching.input.mechanic_labels}
        label = mechanics.get(finding.mechanic_id, finding.mechanic_id or finding.category.value)
        evidence = ", ".join(e.evidence_id for e in finding.evidence[:4])
        lines.append(f"{finding.finding_id[:80]} · {label[:80]} · {finding.severity.value} · evidence: {evidence[:160]}")
    return _clip("\n".join(lines) or "No additional findings.", 1800)


def to_discord_embed(payload):
    """Thin py-cord transport conversion; no coaching decisions here."""
    import discord
    embed = discord.Embed(title=payload.embed.title, description=payload.embed.description,
                          url=payload.embed.url)
    for field in payload.embed.fields:
        embed.add_field(name=field.name, value=field.value, inline=field.inline)
    if payload.embed.footer:
        embed.set_footer(text=payload.embed.footer)
    return embed
