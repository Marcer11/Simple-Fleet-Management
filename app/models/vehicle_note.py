from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship

from .base import Base

# Návrhy typu poznámky (lze napsat i vlastní)
NOTE_CATEGORIES = ["Garáž", "Půjčeno", "Vráceno", "Nehoda", "Poškození", "Pneumatiky", "Parkování", "Jiné"]


class VehicleNote(Base):
    """Poznámka k vozidlu v čase (uloženo do garáže, půjčeno, nehoda…) - zobrazuje se na časové ose."""
    __tablename__ = "vehicle_notes"
    __table_args__ = (Index("ix_vehicle_notes_vehicle_time", "vehicle_id", "note_datetime"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    note_datetime = Column(DateTime, nullable=False)
    odometer = Column(Integer, nullable=True)
    category = Column(String(40), nullable=True)
    text = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle", back_populates="notes")
    created_by = relationship("User")

    @property
    def title(self):
        return self.category or (self.text or "").strip().split("\n")[0][:80] or "Poznámka"

    def __repr__(self):
        return f"VehicleNote id={self.id} vehicle_id={self.vehicle_id} {self.note_datetime}"
