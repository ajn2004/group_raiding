from typing import Protocol

from .models import CoachingInput, CoachingSelection


class CoachingProviderError(Exception):
    """Normalized failure at the optional provider boundary."""


class CoachingProvider(Protocol):
    provider_name: str
    model_name: str | None

    def select(self, coaching_input: CoachingInput, prompt: str) -> CoachingSelection: ...
