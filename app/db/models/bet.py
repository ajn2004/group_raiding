from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from .base import Base


class Bet(Base):
    __tablename__ = 'bet'

    id = Column(Integer, primary_key=True)
    eventID = Column(Integer, ForeignKey('bet_events.id'), nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    outcome = Column(Integer, nullable=False) # outcome will be the index of the selected outcomes in the betEvent table
    amount = Column(Integer, nullable=False)
    resolved = Column(Boolean, default = False)
    
    def __repr__(self) -> str:
        return f'<Player {self.player_id} bet {self.amount} on {self.outcome}>'
