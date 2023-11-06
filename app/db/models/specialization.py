from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from .base import Base


class Specialization(Base):
    __tablename__ = 'specializations'

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    role_id = Column(Integer, ForeignKey('roles.id'), nullable=False)  # 1 tank 2 melee 3 ranged 4 heals
    gearscore = Column(Integer, nullable=False)
    character_id = Column(Integer, ForeignKey('characters.id'), nullable=False)
    buffs = relationship('Buff', backref='specialization', lazy='dynamic')
