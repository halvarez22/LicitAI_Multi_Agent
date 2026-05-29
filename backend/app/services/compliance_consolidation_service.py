"""
Capa de Consolidación de Compliance (CCC) — LicitAI v2.1

DISEÑO UNIVERSAL: Este servicio NO asume nombres, números ni contenido específico
de ninguna licitación. Aprende la estructura de anexos del propio texto del pliego.

Pipeline:
  1. AnnexExtractor    → Detecta patrones "Anexo X" / "Documento No. N" en cualquier pliego
  2. GroupBuilder       → Agrupa ítems que refieren al mismo anexo/documento
  3. OrphanCollector    → Captura ítems sin número de Anexo con dedup por nombre
  4. SobreClassifier    → Clasifica en Sobre 1/2 por keywords genéricas (no hardcodeadas por licitación)
  5. TraceabilityBuilder→ Preserva evidencia_original por entregable (trazabilidad Gemini)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers de normalización (universales)
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin puntuación extra."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _token_overlap(a: str, b: str) -> float:
    """Similitud por tokens compartidos / tokens totales (Jaccard)."""
    ta = set(_normalize(a).split())
    tb = set(_normalize(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# Paso 1: AnnexExtractor — Detecta números de Anexo/Documento en cualquier pliego
# ---------------------------------------------------------------------------

# Patrones universales — funcionan para CUALQUIER licitación
_ANNEX_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # "Anexo I", "Anexo XII", "Anexo 3", "ANEXO IV"
    ("anexo_roman",  re.compile(r"\banexo\s+([IVXLCDM]+)\b",       re.IGNORECASE)),
    ("anexo_arabic", re.compile(r"\banexo\s+n[uú]m(?:ero)?\.?\s*(\d+)\b", re.IGNORECASE)),
    ("anexo_num",    re.compile(r"\banexo\s+(\d+)\b",               re.IGNORECASE)),
    # "Documento No. 14", "Documento Núm. 3"
    ("doc_num",      re.compile(r"\bdocumento\s+n[oú](?:m(?:ero)?)?\.?\s*(\d+)\b", re.IGNORECASE)),
    # "Formato 1", "Formato A"
    ("formato_num",  re.compile(r"\bformato\s+([A-Z\d]+)\b",        re.IGNORECASE)),
]


def _extract_annex_key(text: str) -> Optional[str]:
    """
    Extrae la clave canónica de Anexo/Documento del texto.
    Ejemplo: 'Anexo XII' → 'anexo_XII', 'Documento No. 14' → 'doc_14'
    Retorna None si no hay patrón reconocible.
    """
    for kind, pattern in _ANNEX_PATTERNS:
        m = pattern.search(text)
        if m:
            val = m.group(1).upper().strip()
            prefix = kind.split("_")[0]  # "anexo", "doc", "formato"
            return f"{prefix}_{val}"
    return None


# ---------------------------------------------------------------------------
# Paso 2: GroupBuilder — Agrupa ítems por clave de Anexo detectada
# ---------------------------------------------------------------------------

class GroupBuilder:
    """Agrupa ítems de compliance que hacen referencia al mismo Anexo/Documento."""

    def build(
        self, raw_items: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
        """
        Returns:
            groups: {annex_key: [items...]}}
            orphans: ítems sin clave de Anexo detectada
        """
        groups: Dict[str, List[Dict]] = {}
        orphans: List[Dict] = []

        for item in raw_items:
            name    = str(item.get("nombre")  or "")
            snippet = str(item.get("snippet") or "")

            key = _extract_annex_key(name) or _extract_annex_key(snippet)
            if key:
                groups.setdefault(key, []).append(item)
            else:
                orphans.append(item)

        return groups, orphans


# ---------------------------------------------------------------------------
# Paso 3: OrphanCollector + SemanticGrouper (LLM) — Dedup semántico de ítems sin número de Anexo
# ---------------------------------------------------------------------------

_SIMILARITY_THRESHOLD = 0.45   # Jaccard mínimo para considerar "mismo documento"


class OrphanCollector:
    """
    Agrupa ítems huérfanos (sin número de Anexo) por similitud de nombre.
    No usa LLM — solo Jaccard sobre tokens normalizados.
    """

    def deduplicate(self, orphans: List[Dict]) -> List[Dict]:
        if not orphans:
            return []
        clusters: List[List[Dict]] = []
        for item in orphans:
            placed = False
            name = str(item.get("nombre") or "")
            for cluster in clusters:
                rep = cluster[0]
                rep_name = str(rep.get("nombre") or "")
                if _token_overlap(name, rep_name) >= _SIMILARITY_THRESHOLD:
                    cluster.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])
        result = []
        for cluster in clusters:
            rep = max(cluster, key=lambda x: len(str(x.get("nombre") or "")))
            rep = dict(rep)
            rep["_cluster_members"] = cluster
            result.append(rep)
        return result

import json
from app.services.resilient_llm import ResilientLLMClient

class SemanticGrouper:
    """Agrupa ítems huérfanos usando el LLM."""
    
    def __init__(self):
        self.llm = ResilientLLMClient()
        
    async def group(self, orphans: List[Dict], session_id: str = "") -> List[Dict]:
        if not orphans:
            return []
            
        # Pre-agrupar con Jaccard para reducir tokens al LLM
        collector = OrphanCollector()
        pre_deduped = collector.deduplicate(orphans)
        
        if len(pre_deduped) <= 3:
            return pre_deduped
            
        items_payload = []
        for i, item in enumerate(pre_deduped):
            items_payload.append({
                "id": str(i),
                "nombre": str(item.get("nombre") or "")[:150],
                "snippet": str(item.get("snippet") or "")[:200]
            })
            
        prompt = f"""
Agrupa los siguientes ítems de compliance de una licitación en entregables únicos.
Fusiona los que pidan el mismo documento (ej. "Identificación oficial" y "Copia de INE").
Devuelve SOLO un JSON Array con este formato estricto:
[
  {{ "nombre_canonico": "Identificación Oficial", "ids_fusionados": ["0", "2", "5"] }},
  ...
]

Ítems:
{json.dumps(items_payload, ensure_ascii=False, indent=2)}
"""
        system_prompt = "Eres un experto en licitaciones públicas. Agrupa requisitos en entregables canónicos. Responde ÚNICAMENTE con JSON válido."
        
        llm_response = await self.llm.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            format="json",
            correlation_id=f"ccc-semantic-{session_id}"
        )
        
        if not llm_response.success or not llm_response.response:
            return pre_deduped
            
        try:
            llm_groups = json.loads(llm_response.response)
        except json.JSONDecodeError:
            return pre_deduped
            
        if not isinstance(llm_groups, list):
            return pre_deduped
            
        result = []
        for g in llm_groups:
            if not isinstance(g, dict):
                continue
            nombre_can = str(g.get("nombre_canonico") or "Documento general")
            ids = g.get("ids_fusionados", [])
            
            cluster = []
            for item_id in ids:
                try:
                    idx = int(item_id)
                    orig_item = pre_deduped[idx]
                    members = orig_item.get("_cluster_members", [orig_item])
                    cluster.extend(members)
                except (ValueError, IndexError):
                    pass
            
            if cluster:
                rep = dict(cluster[0])
                rep["nombre"] = nombre_can
                rep["_cluster_members"] = cluster
                result.append(rep)
                
        # Preservar cualquier ítem que el LLM haya omitido por error
        processed_ids = {int(i) for g in llm_groups if isinstance(g, dict) for i in g.get("ids_fusionados", []) if str(i).isdigit()}
        for i, item in enumerate(pre_deduped):
            if i not in processed_ids:
                result.append(item)
                
        return result


# ---------------------------------------------------------------------------
# Paso 4: SobreClassifier — Clasifica en Sobre 1 / Sobre 2 / Legal
# ---------------------------------------------------------------------------

# Keywords GENÉRICOS (no específicos de ninguna licitación)
_SOBRE2_KEYWORDS = (
    "econom", "precio", "fianza", "seriedad", "garantia de seriedad",
    "propuesta economica", "oferta economica", "cotizacion", "importe",
    "partida", "unitario", "desglose", "iva", "catalogo de conceptos",
    "analisis de precios", "anexo g", "tabla de precios",
)
_LEGAL_KEYWORDS = (
    "acta constitutiva", "poder notarial", "identificacion oficial",
    "identificacion personal", "situacion fiscal", "opinion de cumplimiento",
    "opinion del cumplimiento", "rfc", "registro federal", "padron de proveedores",
    "alta ante el sat", "cedula fiscal", "cedula de identificacion fiscal",
    "constancia fiscal", "notario", "imss", "infonavit", "servicio de administracion tributaria",
    "seguridad social", "comprobante fiscal", "cfdi", "instrumento juridico",
    "representante o apoderado", "constancia de no adeudos", "comprobante de domicilio",
    "credencial para votar", "credencial electronica",
)


def classify_deliverable_sobre(name: str, snippet: str = "") -> str:
    """
    Clasifica un entregable en sobre técnico, económico o legal.
    Precedencia: legal > económico > técnico (evita actas/opiniones en sobre económico).
    """
    combined = _normalize(f"{name} {snippet}")
    for kw in _LEGAL_KEYWORDS:
        if kw in combined:
            return "requisitos_legales"
    for kw in _SOBRE2_KEYWORDS:
        if kw in combined:
            return "sobre_2_economico"
    return "sobre_1_tecnico"


def _classify_sobre(name: str, snippet: str) -> str:
    return classify_deliverable_sobre(name, snippet)


# ---------------------------------------------------------------------------
# Paso 5: TraceabilityBuilder — Construye evidencia_original por entregable
# ---------------------------------------------------------------------------

def _build_deliverable(
    items: List[Dict],
    annex_key: Optional[str],
    zone_origin: str,
) -> Dict[str, Any]:
    """
    Construye un entregable consolidado con trazabilidad completa.
    El nombre canónico se infiere del ítem más descriptivo del grupo.
    """
    # Nombre canónico: el más largo y con más información
    best = max(items, key=lambda x: len(str(x.get("nombre") or "")))
    nombre_canonico = str(best.get("nombre") or "Sin nombre")

    # Snippet más informativo (el más largo)
    snippet_rep = max(
        (str(x.get("snippet") or "") for x in items),
        key=len, default=""
    )

    # Páginas de referencia
    pages: List[int] = []
    for item in items:
        p = item.get("page") or item.get("pagina")
        try:
            pages.append(int(p))
        except (TypeError, ValueError):
            pass
    pages = sorted(set(pages))

    # Tipo de entregable: compliance usa tipo_accion; presentar_fisico prevalece si algún ítem lo trae
    actions: List[str] = []
    for x in items:
        for key in ("tipo_accion", "tipo_item", "tipo"):
            val = str(x.get(key) or "").strip().lower()
            if val:
                actions.append(val)
                break
    if any(a == "presentar_fisico" for a in actions):
        tipo = "presentar_fisico"
    elif any(a == "generar" for a in actions):
        tipo = "generar"
    else:
        tipo = actions[0] if actions else "generar"

    # Confianza promedio
    confidences = [
        float(x.get("confidence") or x.get("confianza") or 0.7)
        for x in items
        if x.get("confidence") or x.get("confianza")
    ]
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.7

    # Evidencia original (trazabilidad — petición de Gemini)
    evidencia_original = [
        {
            "nombre":   str(x.get("nombre")  or ""),
            "snippet":  str(x.get("snippet") or "")[:200],
            "zona":     zone_origin,
        }
        for x in items
    ]

    # Clasificar sobre
    sobre_key = _classify_sobre(nombre_canonico, snippet_rep)

    return {
        "id":                   annex_key or _normalize(nombre_canonico)[:40].replace(" ", "_"),
        "nombre_canonico":      nombre_canonico,
        "numero_anexo":         annex_key.replace("_", " ").title() if annex_key else None,
        "origen":               "auto_descubrimiento" if annex_key else "agrupacion_semantica",
        "tipo":                 tipo or "generar",
        "tipo_accion_final":    tipo or "generar",
        "sobre_clasificado":    sobre_key,
        "snippet_representativo": snippet_rep[:300],
        "paginas_referencia":   pages,
        "items_fusionados":     len(items),
        "confidence":           avg_confidence,
        "evidencia_original":   evidencia_original,
    }


# ---------------------------------------------------------------------------
# Entry Point: ComplianceConsolidator
# ---------------------------------------------------------------------------

class ComplianceConsolidator:
    """
    Punto de entrada principal del CCC.
    """

    def __init__(self):
        self._group_builder    = GroupBuilder()
        self._semantic_grouper = SemanticGrouper()

    async def consolidate(
        self,
        raw_items: Dict[str, List[Dict[str, Any]]],
        session_id: str = "",
    ) -> Dict[str, Any]:
        import time
        t0 = time.time()

        # Aplanar todas las zonas en una lista única con metadato de zona
        all_items: List[Dict] = []
        for zone, items in (raw_items or {}).items():
            for item in (items or []):
                if not isinstance(item, dict):
                    continue   # Saltar strings u otros tipos inesperados
                enriched = dict(item)
                enriched["_source_zone"] = zone
                all_items.append(enriched)

        if not all_items:
            return self._empty_result(session_id, 0)

        # Paso 1 + 2: Agrupar por número de Anexo detectado
        groups, orphans = self._group_builder.build(all_items)

        # Paso 3: Dedup semántico de huérfanos usando el LLM
        deduped_orphans = await self._semantic_grouper.group(orphans, session_id=session_id)

        # Paso 4+5: Construir entregables con trazabilidad
        deliverables: List[Dict] = []

        # Entregables con Anexo explícito (auto-descubrimiento del pliego)
        for annex_key, items in groups.items():
            zone = items[0].get("_source_zone", "unknown")
            d = _build_deliverable(items, annex_key, zone)
            deliverables.append(d)

        # Entregables sin Anexo (agrupados semánticamente)
        for item in deduped_orphans:
            cluster = item.pop("_cluster_members", [item])
            zone = item.get("_source_zone", "unknown")
            d = _build_deliverable(cluster, None, zone)
            deliverables.append(d)

        # Clasificar en las 4 zonas de salida
        sobre_1, sobre_2, legales, huerfanos_criticos = [], [], [], []
        for d in deliverables:
            sc = d.get("sobre_clasificado")
            if sc == "sobre_2_economico":
                sobre_2.append(d)
            elif sc == "requisitos_legales":
                legales.append(d)
            elif d.get("confidence", 1.0) < 0.55:
                huerfanos_criticos.append(d)
            else:
                sobre_1.append(d)

        # Ordenar cada zona: primero los que tienen número de Anexo
        def _sort_key(d: Dict) -> Tuple:
            has_annex = 0 if d.get("numero_anexo") else 1
            return (has_annex, d.get("nombre_canonico", ""))

        sobre_1.sort(key=_sort_key)
        sobre_2.sort(key=_sort_key)
        legales.sort(key=_sort_key)

        latencia_ms = round((time.time() - t0) * 1000, 1)

        from app.services.document_deliverable_filter import (
            filter_consolidated_document_candidates,
        )

        payload = {
            "sobre_1_tecnico":          sobre_1,
            "sobre_2_economico":        sobre_2,
            "requisitos_legales":       legales,
            "otros_requisitos_criticos": huerfanos_criticos,
            "_meta": {
                "session_id":             session_id,
                "total_raw_items":        len(all_items),
                "total_consolidados":     len(sobre_1)
                + len(sobre_2)
                + len(legales)
                + len(huerfanos_criticos),
                "items_con_anexo":        len(groups),
                "items_agrupados_semanticamente": len(deduped_orphans),
                "latencia_ms":            latencia_ms,
            },
        }
        return filter_consolidated_document_candidates(payload)

    @staticmethod
    def _empty_result(session_id: str, total: int) -> Dict[str, Any]:
        return {
            "sobre_1_tecnico":           [],
            "sobre_2_economico":         [],
            "requisitos_legales":        [],
            "otros_requisitos_criticos": [],
            "_meta": {
                "session_id":         session_id,
                "total_raw_items":    total,
                "total_consolidados": 0,
                "latencia_ms":        0,
            },
        }
