"""
Contratos versionados para resolución por bloques (Hito A1).

Define el paquete ``InteractionBlock`` que el backend puede enviar al frontend
para captura tabular masiva, con anclaje forense y metadatos de gobernanza.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


INTERACTION_BLOCK_SCHEMA_VERSION = "1.0.0"


class BlockAnchor(BaseModel):
    """Anclaje a pliego/anexo; la cita legal debe ser verificable (no inventada por el LLM)."""

    title: str = Field(default="", description="Título humano del anexo o sección.")
    page: Optional[int] = Field(
        default=None,
        description="Número de página en el PDF de bases, si consta en metadatos.",
    )
    description: str = Field(
        default="",
        description="Resumen opcional; si viene de RAG, marcar provenance en metadata.",
    )
    legal_reference: str = Field(
        default="",
        description="Fragmento literal o referencia tomada de analisis_bases / requisito, sin inferencia.",
    )
    provenance: Literal["analisis_bases", "compliance_item", "pending_only", "none"] = Field(
        default="none",
        description="Origen del anclaje mostrado al usuario.",
    )


class InteractionBlockItem(BaseModel):
    """Una fila resoluble dentro del bloque."""

    item_id: str = Field(..., description="Identificador estable; p. ej. campo pending `price_*`.")
    label: str = Field(default="", description="Etiqueta humana del concepto.")
    unit: str = Field(
        default="PU",
        description="Unidad de cotización (p. ej. mes, guardia, pieza) si se conoce.",
    )
    suggested_value: Optional[float] = Field(
        default=None,
        description="Sugerencia desde catálogo empresa, si existe coincidencia.",
    )
    is_required: bool = True
    format: Literal["numeric", "text", "date"] = "numeric"
    example: str = Field(default="15000", description="Ejemplo de respuesta válida.")
    validation_rule: str = Field(
        default="must_be_finite_number",
        description="Clave de regla simple para validación en servidor.",
    )
    block_item_seq: int = Field(default=0, description="Orden dentro del bloque.")


class InteractionBlockMetadata(BaseModel):
    """Estado del bloque para UI y telemetría."""

    total_items: int = 0
    resolved_items: int = 0
    block_type: Literal["economic_proposal", "administrative_profile"] = "economic_proposal"
    feature_flag: str = Field(
        default="LICITAI_ENABLE_BLOCK_RESOLUTION",
        description="Nombre de la variable de entorno que activa el modo bloque.",
    )


class InteractionBlock(BaseModel):
    """Paquete canónico bloque → frontend (Hito A1)."""

    block_id: str = Field(..., description="UUID o identificador único del bloque.")
    block_version: str = Field(
        default=INTERACTION_BLOCK_SCHEMA_VERSION,
        description="Versión del contrato del bloque.",
    )
    anchor: BlockAnchor = Field(default_factory=BlockAnchor)
    items: List[InteractionBlockItem] = Field(default_factory=list)
    metadata: InteractionBlockMetadata = Field(default_factory=InteractionBlockMetadata)


class MassSaveRowResult(BaseModel):
    """Resultado por fila en guardado masivo."""

    item_id: str
    ok: bool
    error: Optional[str] = None


class InteractionBlockMassSaveRequest(BaseModel):
    """Cuerpo del endpoint de guardado masivo."""

    session_id: str
    company_id: str
    block_id: str
    correlation_id: str = Field(default="", description="Id de correlación HITL / auditoría.")
    rows: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de {item_id, value} (value string o número).",
    )


class InteractionBlockMassSaveResponse(BaseModel):
    """Respuesta agregada; no oculta filas fallidas."""

    success_count: int = 0
    failed_items: List[Dict[str, str]] = Field(default_factory=list)
    removed_fields: List[str] = Field(default_factory=list)
    block_id: str = ""
    correlation_id: str = ""
