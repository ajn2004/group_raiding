import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.pull_coach.persistence.coaching_profiles import (
    ActiveCoachingRevisionMissing, CoachingProfileNotFound, CoachingProfileRepository,
)


def test_profiles_are_versioned_activatable_and_historical_rows_survive():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repo = CoachingProfileRepository(session)
        first = repo.create_revision("raid_coach", provider="openrouter", model_slug="vendor/model-a",
            system_prompt="system a", user_prompt_template="user a", output_schema_version="selection-v1",
            provider_options={"reasoning": {"effort": "low"}}, activate=True)
        pinned_id = first.id
        second = repo.create_revision("raid_coach", provider="openrouter", model_slug="vendor/model-b",
            system_prompt="system b", user_prompt_template="user b", output_schema_version="selection-v2")
        assert repo.active("raid_coach").active_revision.id == pinned_id
        repo.activate("raid_coach", second.revision)
        assert repo.active("raid_coach").active_revision.model_slug == "vendor/model-b"
        assert session.get(type(first), pinned_id).system_prompt == "system a"
        assert second.revision == 2


def test_missing_profile_and_missing_active_revision_are_explicit():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repo = CoachingProfileRepository(session)
        with pytest.raises(CoachingProfileNotFound):
            repo.active("unknown")
        repo.create_revision("no-active", provider="openrouter", model_slug="x/y",
            system_prompt="s", user_prompt_template="u", output_schema_version="v1")
        with pytest.raises(ActiveCoachingRevisionMissing):
            repo.active("no-active")
        with pytest.raises(LookupError, match="revision"):
            repo.activate("no-active", 99)
