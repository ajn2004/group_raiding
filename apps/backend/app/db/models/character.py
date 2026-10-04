from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from .base import Base


class Character(Base):
    __tablename__ = 'characters'

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    class_name = Column(String(50), nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    server = Column(String(100))
    region = Column(String(32))
    specializations = relationship('Specialization', backref='character', lazy=True)
    mainAlt = Column(Boolean, default=False)

    def __repr__(self) -> str:
        return f'<Character {self.name}>'
