from .models import PublicCoaching


def render(public: PublicCoaching, max_characters: int) -> str:
    sections = []
    if public.primary_failure:
        sections.append(("Primary", [public.primary_failure.text]))
    for title, items in (("Improved", public.improvements), ("DPS", public.dps_actions),
                         ("Healers", public.healer_actions), ("Tanks", public.tank_actions),
                         ("Raid", public.raid_actions), ("Next pull", public.next_pull_priorities)):
        if items:
            content = ([f"{i}. {item.text}" for i, item in enumerate(items, 1)]
                       if title == "Next pull" else [item.text for item in items])
            sections.append((title, content))
    while sections:
        text = "\n\n".join(f"{title}:\n" + "\n".join(items) for title, items in sections)
        if len(text) <= max_characters:
            return text
        # Preserve primary; reduce optional sections from the lowest priority end.
        sections.pop()
    if public.primary_failure:
        primary = f"Primary:\n{public.primary_failure.text}"
        if len(primary) <= max_characters:
            return primary
        if max_characters <= len("Primary:\n…"):
            return "" if max_characters <= 0 else "…"[:max_characters]
        return primary[:max_characters - 1] + "…"
    return ""
