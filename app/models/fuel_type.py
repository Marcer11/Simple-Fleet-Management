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

    user = relationship("User")

    def __repr__(self):
        return f"FuelType id={self.id} name={self.name} category={self.category}"
