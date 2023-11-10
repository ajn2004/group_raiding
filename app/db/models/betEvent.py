from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base


class BetEvent(Base):
    __tablename__ = 'bet_events'

    id = Column(Integer, primary_key=True)
    eventName = Column(String(80), nullable=False)
    expiration = Column(DateTime, nullable=False)
    bets = relationship('Bet', backref='BetEvent', lazy=True)
    outcomes = relationship('BetOutcome', backref='BetEvent', lazy=True)
