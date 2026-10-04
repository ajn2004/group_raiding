from sqlalchemy import Column, Integer, String, BigInteger
from sqlalchemy.orm import relationship

from .base import Base


class Player(Base):
    __tablename__ = 'players'

    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    characters = relationship('Character', backref='player', lazy=True)
    usage = relationship('Usage', backref='player', lazy=True)
    discord_id = Column(BigInteger)
    piter_death_tokens = Column(Integer)
    tokens_spent = Column(Integer, default=0)
    tokens_received = Column(Integer, default=0)
    bets = relationship('Bet', backref='player', lazy=True)

    def __repr__(self) -> str:
        return f'<Player {self.name} {self.discord_id}>'

