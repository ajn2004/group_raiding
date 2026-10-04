"""Discord-neutral immutable outbound payloads."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DiscordEmbedField:
    name: str
    value: str
    inline: bool = False


@dataclass(frozen=True)
class DiscordEmbedPayload:
    title: str
    description: str
    url: str
    fields: tuple[DiscordEmbedField, ...]
    footer: str = "Pull Coach"


@dataclass(frozen=True)
class DiscordMessagePayload:
    embed: DiscordEmbedPayload
    details: str = ""
    content: str | None = None
