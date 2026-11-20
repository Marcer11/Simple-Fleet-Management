from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from .base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    # Vozidla, která uživatel vlastní
    vehicles = relationship("Vehicle", back_populates="owner")
    # Vozidla, která jsou s uživatelem sdílena
    shares = relationship("VehicleShare", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"User id={self.id} email={self.email}"
