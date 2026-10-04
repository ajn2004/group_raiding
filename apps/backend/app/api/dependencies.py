"""Dependencies shared by API routes."""

from collections.abc import Generator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as SQLAlchemySession


def get_db_session() -> Generator["SQLAlchemySession", None, None]:
    """Yield a request-scoped session from the existing persistence layer.

    Import lazily so transport-only operations (including health and OpenAPI)
    don't require database configuration or establish a database connection.
    """
    from app.db.database import Session

    session = Session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
