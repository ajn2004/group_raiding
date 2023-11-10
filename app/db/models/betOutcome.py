from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base


class BetOutcome(Base):
    __tablename__ = 'bet_outcomes'

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    betEvent = Column(Integer, ForeignKey('bet_events.id'), nullable=False)
    outNumber = Column(Integer, nullable = False) # code outcomes by integer
