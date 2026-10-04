"""Canonical domain identifiers shared across provider and workflow boundaries."""
import re


def normalize_encounter_id(value):
    """Return a canonical positive encounter ID, or None for malformed IDs."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        number = int(value)
    else:
        return None
    return str(number) if number > 0 else None


def fight_sort_key(fight):
    """DAL-57 chronology: start time, then numeric/stable fight-ID tie-break."""
    fight_id = str(fight["id"])
    try:
        tie_break = (0, int(fight_id))
    except ValueError:
        tie_break = (1, fight_id)
    return fight["startTime"], tie_break
