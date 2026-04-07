"""Modelos Pydantic para el checklist de presentación (hitos del cronograma)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class HitoModel(BaseModel):
    """Un hito del procedimiento derivado del cronograma del Analista."""

    id: str = Field(..., description="Identificador canónico (ej. visita_instalaciones).")
    nombre: str = Field(..., description="Etiqueta legible en español.")
    fecha_texto_raw: str = Field(
        default="",
        description="Texto literal devuelto por el Analista (p. ej. fecha en bases).",
    )
    fecha_hora: Optional[datetime] = Field(
        None,
        description="Fecha/hora parseada si fue posible; None si no aplica o no se pudo parsear.",
    )
    obligatorio: bool = True
    estado: Literal["pendiente", "completado", "vencido"] = "pendiente"
    evidencia: Optional[str] = Field(
        None,
        description="Referencia opcional (nombre de archivo o nota); no es upload en MVP.",
    )
    notificado: bool = False


class SubmissionChecklistModel(BaseModel):
    """Estado persistido en sesión bajo la clave submission_checklist."""

    licitation_id: Optional[str] = None
    hitos: List[HitoModel] = Field(default_factory=list)
    ultima_actualizacion: datetime = Field(default_factory=datetime.utcnow)
    porcentaje_completado: float = 0.0


class MarkHitoPayload(BaseModel):
    """Cuerpo para marcar un hito desde la API."""

    estado: Literal["pendiente", "completado"] = "completado"
    evidencia: Optional[str] = None
