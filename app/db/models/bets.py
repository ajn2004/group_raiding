from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from .base import Base


class betEvent(Base):
    __tablename__ = 'characters'

    id = Column(Integer, primary_key=True)
    eventName = Column(String(80), nullable=False)
    class_name = Column(String(50), nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    specializations = relationship('Specialization', backref='character', lazy=True)
    mainAlt = Column(Boolean, default=False)

    def __repr__(self) -> str:
        return f'<Character {self.name}>'
