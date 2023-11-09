from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class Role(Base):
    __tablename__ = 'roles'

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    specializations = relationship('Specialization', backref='role', lazy=True)

    def __repr__(self) -> str:
        return f'<Role {self.name}>'

