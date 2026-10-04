"""Small transaction-neutral repository for web authentication records."""
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import OAuthState, WebIdentity, WebSession


def create_state(db: Session, digest: str, return_to: str, expires_at: datetime) -> None:
    db.add(OAuthState(state_digest=digest, return_to=return_to, expires_at=expires_at))
    db.flush()


def consume_state(db: Session, digest: str, now: datetime) -> str | None:
    # DELETE .. RETURNING is atomic: concurrent callbacks cannot both consume it.
    result = db.execute(delete(OAuthState).where(OAuthState.state_digest == digest,
                                                OAuthState.expires_at > now).returning(OAuthState.return_to))
    return result.scalar_one_or_none()


def find_session(db: Session, digest: str, now: datetime) -> tuple[WebSession, WebIdentity] | None:
    row = db.execute(select(WebSession, WebIdentity).join(WebIdentity).where(
        WebSession.token_digest == digest, WebSession.expires_at > now)).one_or_none()
    return row


def upsert_identity(db: Session, discord_user_id: str, username: str, display_name: str,
                    avatar_url: str | None) -> WebIdentity:
    dialect = db.get_bind().dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if insert is None:
        # Preserve a clear failure rather than silently falling back to a racy
        # check-then-insert on an unsupported database.
        raise RuntimeError(f"Identity upsert is unsupported for database dialect {dialect!r}")

    statement = insert(WebIdentity).values(
        discord_user_id=discord_user_id,
        username=username,
        display_name=display_name,
        avatar_url=avatar_url,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[WebIdentity.discord_user_id],
        set_={"username": username, "display_name": display_name, "avatar_url": avatar_url},
    ).returning(WebIdentity)
    identity = db.scalars(statement).one()
    db.flush()
    return identity


def create_session(db: Session, identity: WebIdentity, digest: str, csrf_token: str,
                   expires_at: datetime) -> None:
    db.add(WebSession(identity=identity, token_digest=digest, csrf_token=csrf_token, expires_at=expires_at))
    db.flush()


def invalidate_session(db: Session, digest: str, now: datetime) -> WebSession | None:
    row = db.scalar(select(WebSession).where(WebSession.token_digest == digest, WebSession.expires_at > now))
    if row is not None:
        db.delete(row)
    return row


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
