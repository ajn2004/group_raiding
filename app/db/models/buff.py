from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from .base import Base


class Buff(Base):
    __tablename__ = 'buffs'

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    raidscore = Column(Integer, nullable=True)
    specialization_id = Column(Integer, ForeignKey('specializations.id'), nullable=False)

    def __repr__(self):
        return f'<Buff {self.name}>'

