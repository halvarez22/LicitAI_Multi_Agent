from sqlalchemy import Column, String, JSON, Boolean, DateTime
from sqlalchemy.sql import func
import uuid
from app.models.base import Base

class NormativePolicy(Base):
    """
    Modelo para la Matriz de Obligatorios Universal.
    Permite parametrizar leyes y categorías sin hardcodear en el código.
    """
    __tablename__ = "normative_policies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    law = Column(String, nullable=False, index=True)      # Ej: "LAASSP", "LOPSRM", "FEDERAL_PRIVATE"
    category = Column(String, nullable=False, index=True) # Ej: "SERVICIOS", "BIENES", "OBRA"
    
    # Lista de etiquetas obligatorias (Must-Have)
    # Ej: ["LEG_ACTA_CONSTITUTIVA", "FIS_SAT_OPINION", ...]
    mandatory_labels = Column(JSON, nullable=False)
    
    # Reglas críticas de validación por ley
    # Ej: ["PRECIOS_MAX_2_DECIMALES"]
    critical_rules = Column(JSON, default=list)
    
    # Mapeo de labels a aliases para matching semántico
    # Ej: {"LEG_ACTA_CONSTITUTIVA": ["acta constitutiva", "constitucion"]}
    alias_map = Column(JSON, default=dict)
    
    # Metadatos
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<NormativePolicy(law='{self.law}', category='{self.category}')>"
