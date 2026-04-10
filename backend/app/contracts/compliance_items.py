"""
Contrato de ítems de la lista maestra de cumplimiento (ComplianceAgent).

Refleja la forma real producida por ``_normalize_item`` y enriquecida en
``_reduce_zone_items`` / ``_dedupe_master_list_categories`` en
``app.agents.compliance``. Sirve como base para validadores Pydantic en el
plan de hardening y para alinear expectativas con Oracle v1.0.1 (p. ej. C01
sobre ``compliance.data.administrativo`` con evidencia en campos serializados).

El Oracle runtime actual no exige explícitamente ``match_tier`` ni ``page`` en
el JSON; valida listas y regex sobre el contenido agregado de los ítems.
Un validador estricto futuro sí puede exigirlos para reintentos dirigidos.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Valores devueltos por ``_verify_evidence``; ``unknown`` aparece en agregados
# (p. ej. ``audit_summary.tier_stats``) si faltara la clave en un ítem heredado.
ComplianceMatchTier = Literal["literal", "normalized", "weak", "none", "unknown"]

ComplianceCategory = Literal["administrativo", "tecnico", "formatos"]


class ComplianceMapChunkItemStrict(BaseModel):
    """
    Un requisito tal como lo exige el prompt de mapa en ``ComplianceAgent._extract_zone_chunk``.

    No incluye ``match_tier`` ni ``evidence_match`` (se calculan después en reduce).
    ``extra="ignore"``: el modelo a veces añade ``categoria`` u otras claves; se descartan al validar.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)

    nombre: str = ""
    page: int = Field(0, ge=0)
    descripcion: str = ""
    snippet: str = ""
    quality_flags: List[str] = Field(default_factory=list)
    seccion: str = "N/A"

    @field_validator("quality_flags", mode="before")
    @classmethod
    def _quality_flags_coerce(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: List[str] = []
        for x in v:
            if x is None:
                continue
            out.append(str(x))
        return out

    @field_validator("page", mode="before")
    @classmethod
    def _page_coerce(cls, v: Any) -> int:
        if v is None:
            return 0
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return max(0, v)
        if isinstance(v, float):
            return max(0, int(v))
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    @model_validator(mode="after")
    def _al_menos_un_campo_visible(self) -> "ComplianceMapChunkItemStrict":
        if max(
            len(self.nombre.strip()),
            len(self.descripcion.strip()),
            len(self.snippet.strip()),
        ) < 1:
            raise ValueError("cada ítem debe incluir al menos nombre, descripcion o snippet no vacío")
        return self


class ComplianceMapChunkOutputStrict(BaseModel):
    """Raíz JSON del bloque map (administrativo / tecnico / formatos)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    administrativo: List[ComplianceMapChunkItemStrict] = Field(default_factory=list)
    tecnico: List[ComplianceMapChunkItemStrict] = Field(default_factory=list)
    formatos: List[ComplianceMapChunkItemStrict] = Field(default_factory=list)


class ComplianceMapChunkOutputLoose(BaseModel):
    """
    Fallback tras fallos del esquema estricto: acepta listas heterogéneas y campos extra en la raíz.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=False)

    administrativo: List[Any] = Field(default_factory=list)
    tecnico: List[Any] = Field(default_factory=list)
    formatos: List[Any] = Field(default_factory=list)


class ComplianceRequirementItemNormalized(BaseModel):
    """
    Salida lógica de ``ComplianceAgent._normalize_item`` (antes de evidencia).

    Nota: en el código, ``id`` se deja en cadena vacía hasta la fase reduce/dedup.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    id: str = ""
    nombre: str
    seccion: str = "N/A"
    descripcion: str
    page: int = 0
    snippet: str
    quality_flags: List[str] = Field(default_factory=list)


class ComplianceRequirementItem(BaseModel):
    """
    Ítem tal como vive en ``full_master_list["administrativo|tecnico|formatos"]``
    tras ``_reduce_zone_items`` y ``_dedupe_master_list_categories``.

    Campos añadidos respecto a ``ComplianceRequirementItemNormalized``:
    ``evidence_match``, ``match_tier``, ``categoria``, ``zona_origen``;
    opcionalmente ``zonas_duplicadas_descartadas`` si ganó un duplicado en dedup.

    ``extra="allow"``: compatibilidad con JSON legado hasta cerrar el hardening;
    para contrato estricto usar un validador que rechace campos no declarados.
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=False)

    id: str = Field(..., min_length=1, description="p.ej. AD-01, TE-02, FO-03")
    nombre: str
    seccion: str = "N/A"
    descripcion: str
    page: int = Field(0, ge=0)
    snippet: str
    quality_flags: List[str] = Field(default_factory=list)
    evidence_match: bool
    match_tier: ComplianceMatchTier
    categoria: ComplianceCategory
    zona_origen: str = Field(
        ...,
        description="Macro-zona map-reduce, p.ej. ADMINISTRATIVO/LEGAL, TÉCNICO/OPERATIVO, FORMATOS/ANEXOS",
    )
    zonas_duplicadas_descartadas: Optional[List[str]] = None


class ComplianceRequirementItemStrict(ComplianceRequirementItem):
    """
    Misma forma que ``ComplianceRequirementItem`` pero sin campos adicionales.
    Objetivo: validación final / Oracle endurecido tras alinear el agente.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ComplianceAuditSummary(BaseModel):
    """Subestructura ``full_master_list["audit_summary"]`` (campos principales)."""

    model_config = ConfigDict(extra="allow")

    zones: List[Dict[str, Any]] = Field(default_factory=list)
    tier_stats: Dict[str, int] = Field(default_factory=dict)
    global_match_pct: float = 0.0
    total_items: int = 0
    causas_desechamiento: List[str] = Field(default_factory=list)


class ComplianceMasterListData(BaseModel):
    """
    Contenido típico de ``AgentOutput.data`` / ``compliance.data`` (tras normalizar envoltorio).

    Las claves ``confidence``, ``unknowns``, ``ambiguities`` solo existen si el
    scoring Fase 1 está activo (ver ``compliance.py``).
    """

    model_config = ConfigDict(extra="allow")

    administrativo: List[Dict[str, Any]] = Field(default_factory=list)
    tecnico: List[Dict[str, Any]] = Field(default_factory=list)
    formatos: List[Dict[str, Any]] = Field(default_factory=list)
    audit_summary: Optional[ComplianceAuditSummary] = None
    confidence: Optional[Dict[str, Any]] = None
    unknowns: Optional[List[Any]] = None
    ambiguities: Optional[List[Any]] = None
