from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class Company(Base):
    """
    Entidad de Empresa (Perfil Maestro).
    Almacena datos persistentes, catálogos y expedientes (Bóveda Digital).
    """
    __tablename__ = "companies"

    id = Column(String, primary_key=True)  # co_...
    name = Column(String, nullable=False)
    rfc = Column(String, nullable=True)
    type = Column(String, default="moral") # moral, fisica
    
    # Perfil Maestro: JSON con campos (nombre, representante, email, web, etc.)
    master_profile = Column(JSON, default={})
    
    # Catálogo de Precios: [{'item': 'Limpieza Hospital', 'unidad': 'm2', 'precio_unitario': 150.50}, ...]
    catalog = Column(JSON, default=[])
    
    # Expediente Digital (Activos): {'docs': {doc_id: {filename, type, indexed, expiry_date}}}
    docs = Column(JSON, default={})
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relación con licitaciones o sesiones (?) opcional
    # sessions = relationship("Session", back_populates="company")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "rfc": self.rfc,
            "type": self.type,
            "master_profile": self.master_profile,
            "catalog": self.catalog,
            "docs": self.docs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
