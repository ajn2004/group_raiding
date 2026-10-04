from sqlalchemy import Column, Integer, String, DateTime, ForeignKey

from .base import Base


class Usage(Base):
    __tablename__ = 'usage'

    id = Column(Integer, primary_key=True)
    command = Column(String(100))
    player_id = Column(Integer, ForeignKey('players.id'))
    timestamp = Column(DateTime, index=True)
