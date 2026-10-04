from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import database_url

Engine = create_engine(database_url())

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
