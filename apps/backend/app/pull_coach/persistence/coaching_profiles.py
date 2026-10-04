"""Database-backed, immutable coaching profile revisions."""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models.pull_coach import CoachingProfile, CoachingProfileRevision


class CoachingProfileNotFound(LookupError):
    """No logical profile exists for the requested purpose."""


class ActiveCoachingRevisionMissing(LookupError):
    """A profile exists but has no valid active revision."""


class CoachingProfileRepository:
    def __init__(self, session: Session):
        self.session = session

    def active(self, purpose: str) -> CoachingProfile:
        profile = self.session.scalar(select(CoachingProfile).options(
            joinedload(CoachingProfile.active_revision)).where(CoachingProfile.purpose == purpose))
        if profile is None:
            raise CoachingProfileNotFound(f"coaching profile {purpose!r} does not exist")
        if profile.active_revision is None:
            raise ActiveCoachingRevisionMissing(f"coaching profile {purpose!r} has no active revision")
        return profile

    def create_revision(self, purpose: str, *, provider: str, model_slug: str,
                        system_prompt: str, user_prompt_template: str,
                        output_schema_version: str, temperature: float | None = None,
                        max_output_tokens: int | None = None,
                        provider_options: dict | None = None, created_by: str | None = None,
                        activate: bool = False) -> CoachingProfileRevision:
        profile = self.session.get(CoachingProfile, purpose)
        if profile is None:
            profile = CoachingProfile(purpose=purpose)
            self.session.add(profile)
            self.session.flush()
        latest = self.session.scalar(select(CoachingProfileRevision.revision).where(
            CoachingProfileRevision.profile_purpose == purpose).order_by(
                CoachingProfileRevision.revision.desc()).limit(1)) or 0
        revision = CoachingProfileRevision(
            profile_purpose=purpose, revision=latest + 1, provider=provider,
            model_slug=model_slug, system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            output_schema_version=output_schema_version, temperature=temperature,
            max_output_tokens=max_output_tokens, provider_options=provider_options or {},
            created_by=created_by)
        self.session.add(revision)
        self.session.flush()
        if activate:
            profile.active_revision_id = revision.id
            self.session.flush()
        return revision

    def activate(self, purpose: str, revision: int) -> CoachingProfile:
        profile = self.session.get(CoachingProfile, purpose)
        if profile is None:
            raise CoachingProfileNotFound(f"coaching profile {purpose!r} does not exist")
        row = self.session.scalar(select(CoachingProfileRevision).where(
            CoachingProfileRevision.profile_purpose == purpose,
            CoachingProfileRevision.revision == revision))
        if row is None:
            raise LookupError(f"revision {revision} does not exist for coaching profile {purpose!r}")
        profile.active_revision_id = row.id
        self.session.flush()
        return profile
