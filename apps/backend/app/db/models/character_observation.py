from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base


class CharacterObservation(Base):
    """Provenance linking an observed character to an immutable source snapshot."""
    __tablename__ = "character_observations"
    __table_args__ = (UniqueConstraint("character_id", "snapshot_id", name="uq_character_observation_source"),)

    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_id = Column(Integer, ForeignKey("wipefest_fight_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(String(100))
    character = relationship("Character")
    snapshot = relationship("WipefestFightSnapshot")
