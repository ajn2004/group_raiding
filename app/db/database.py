from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import USERNAME, PASSWORD, DB_SERVER, DB_NAME

# Dev SQLite engine
# Engine = create_engine(f"sqlite:///sqlite.db")
# Production Postgres engine
Engine = create_engine(f"postgresql://{USERNAME}:{PASSWORD}@{DB_SERVER}/{DB_NAME}")

Session = sessionmaker(bind=Engine)


@contextmanager
def session_scope():
    session = Session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

