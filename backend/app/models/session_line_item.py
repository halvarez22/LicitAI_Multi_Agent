"""Partidas económicas extraídas de documentos tabulares (primera clase, no solo RAG)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class SessionLineItem(Base):
    """
    Fila de costo/partida ligada a sesión y documento fuente.
    Alimenta al EconomicAgent con precios estructurados antes del LLM.
    """

    __tablename__ = "session_line_items"

    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String, nullable=False, default="document_tabular")
    concepto_raw = Column(Text, nullable=False)
    concepto_norm = Column(String, nullable=False, index=True)
    unidad = Column(String, nullable=True)
    cantidad = Column(Float, nullable=True)
    precio_unitario = Column(Float, nullable=False)
    moneda = Column(String, nullable=False, default="MXN")
    sheet_name = Column(String, nullable=True)
    row_index = Column(Float, nullable=True)
    extra = Column(JSON, default=dict)
    extraction_version = Column(String, nullable=False, default="1")
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="line_items")
