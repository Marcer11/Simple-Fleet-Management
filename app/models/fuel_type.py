from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base


class FuelType(Base):
    """Palivo nabízené uživateli ve formuláři tankování (spravuje si ho sám)."""
    __tablename__ = "fuel_types"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_fuel_types_user_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(30), nullable=False)
    # Druh (Benzín, Nafta, LPG, CNG, Elektřina) - None = vlastní řada spotřeby
    category = Column(String(15), nullable=True)
    # Značky pump, u kterých se palivo nabízí (např. "ORLEN" pro Verva 100), oddělené čárkou;
    # prázdné = u všech pump
    station_brands = Column(String(255), nullable=True)

    user = relationship("User")

    @property
    def brands(self):
        return [b for b in (self.station_brands or "").split(",") if b]

    def __repr__(self):
        return f"FuelType id={self.id} name={self.name} category={self.category}"
