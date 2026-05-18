"""
Contrato canónico del inventario de documentos de expediente (Fase 1).

Diseño alineado con el estándar Antigravity/LicitAI: verdad canónica versionada,
procedencia vía anclas (Tier A) o inferencia acotada (Tier B), HITL (Tier C) y
métricas de cobertura. Pydantic v2 (proyecto en ``pydantic==2.6.x``).

Notas respecto al borrador inicial:
- Las estadísticas no usan ``dict`` mutable por defecto ni ``@validator`` v1;
  se recalculan en ``model_validator(mode="after")``.
- ``category`` + ``destinations``: la categoría principal guía generador/UI;
  ``destinations`` lista todos los sobres donde el packager debe materializar
  copias (puede repetir el primero si solo hay un destino).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InventoryTier(str, Enum):
    """Origen de detección del ítem."""

    TIER_A_ANCHORED = "anchored"
    TIER_B_INFERRED = "inferred"
    TIER_C_USER = "user_added"


class DocumentEnvelope(str, Enum):
    """Sobre / bandeja lógica de entrega."""

    LEGAL = "legal_administrative"
    TECHNICAL = "technical"
    ECONOMIC = "economic"
    LOGISTICS = "logistics_outside"


class InventoryItemStatus(str, Enum):
    """Estado del ítem respecto a la fabricación."""

    PENDING = "pending"
    GENERATED = "generated"
    EXTERNAL = "external_input"
    NOT_APPLICABLE = "na"
    SKIPPED = "skipped"


class ItemAnchor(BaseModel):
    """Evidencia de procedencia (Tier A o refuerzo en B)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    pattern_id: Optional[str] = Field(
        default=None,
        description="Identificador del patrón (ej. regex_forma_dd).",
    )
    snippet: str = Field(..., min_length=1, description="Texto literal o fragmento indexado.")
    page_index: Optional[int] = Field(default=None, ge=0)
    source_file: Optional[str] = Field(
        default=None,
        description="Nombre o id del documento fuente en la sesión (bases, anexo).",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class InventoryItem(BaseModel):
    """Un requisito documental en el inventario canónico."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    canonical_id: str = Field(..., min_length=1, description="Id estable para dedup y merge.")
    display_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    category: DocumentEnvelope = Field(
        ...,
        description="Clasificación principal (UI, prioridad de cola).",
    )
    tier: InventoryTier
    status: InventoryItemStatus = InventoryItemStatus.PENDING

    anchors: List[ItemAnchor] = Field(default_factory=list)
    destinations: List[DocumentEnvelope] = Field(
        default_factory=list,
        description="Sobres donde debe existir el entregable; vacío = solo ``category``.",
    )
    bases_revision: str = Field(
        ...,
        min_length=1,
        description="Huella o revisión del texto de bases al detectar (stale detection).",
    )

    generator_hint: Optional[str] = Field(
        default=None,
        description="Plantilla, prompt corto o clave de generador sugerido.",
    )
    associated_artifact_id: Optional[str] = Field(
        default=None,
        description="Id lógico del artefacto generado (p. ej. hash o uuid interno).",
    )
    relative_output_path: Optional[str] = Field(
        default=None,
        description="Ruta relativa bajo /data/outputs/<session>/ si ya existe archivo.",
    )

    is_blocking: bool = Field(
        default=False,
        description="Si True y sigue pendiente, puede elevar severidad en cierre de job.",
    )
    user_override_note: Optional[str] = None
    not_applicable_reason: Optional[str] = Field(
        default=None,
        description="Motivo si status == na (ej. 'AT-07A no aplica según bases').",
    )

    @model_validator(mode="after")
    def _coalesce_destinations(self) -> InventoryItem:
        if not self.destinations:
            self.destinations = [self.category]
        return self


class InventoryStats(BaseModel):
    """KPIs materializados; recalculados al validar ``DocumentInventory``."""

    model_config = ConfigDict(extra="ignore")

    total_detected: int = 0
    total_generable: int = 0
    total_generated: int = 0
    coverage_percentage: float = 0.0
    blocking_missing_count: int = 0


class DocumentInventory(BaseModel):
    """Contenedor maestro del inventario por sesión."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    session_id: str = Field(..., min_length=1)
    schema_version: str = Field(default="1.0.0", min_length=1)
    revision: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    items: List[InventoryItem] = Field(default_factory=list)
    stats: InventoryStats = Field(default_factory=InventoryStats)

    @staticmethod
    def _compute_stats(items: List[InventoryItem]) -> InventoryStats:
        total = len(items)
        generable = [
            i
            for i in items
            if i.status
            not in (
                InventoryItemStatus.EXTERNAL,
                InventoryItemStatus.NOT_APPLICABLE,
                InventoryItemStatus.SKIPPED,
            )
        ]
        gen_ok = [i for i in items if i.status == InventoryItemStatus.GENERATED]
        pending_blocking = [
            i for i in items if i.is_blocking and i.status == InventoryItemStatus.PENDING
        ]
        denom = len(generable) if generable else total
        coverage = round((len(gen_ok) / denom) * 100.0, 2) if denom else 0.0
        return InventoryStats(
            total_detected=total,
            total_generable=len(generable),
            total_generated=len(gen_ok),
            coverage_percentage=coverage,
            blocking_missing_count=len(pending_blocking),
        )

    @model_validator(mode="after")
    def _refresh_stats(self) -> DocumentInventory:
        self.stats = self._compute_stats(self.items)
        return self
