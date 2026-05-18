"""
Servicio de inventario documental (Fase 1.3): extracción híbrida → ``DocumentInventory``.

Centraliza la lógica probada en ``scratch/extract_inventory_dry_run.py``:
anclaje regex (Tier A), heurística por capítulos 6–8 y/o LLM (Tier B), merge y
deduplicación. Incluye filtro de solape: líneas numeradas que ya mencionan una
Forma detectada en el Paso A se omiten (recomendación Antigravity).

Para texto agregado desde sesión (RAG), usar ``build_for_session``; para un
dump completo de bases (p. ej. OCR unificado), ``build_from_bases_text``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.config.settings import settings
from app.contracts.document_inventory import (
    DocumentEnvelope,
    DocumentInventory,
    InventoryItem,
    InventoryItemStatus,
    InventoryTier,
    ItemAnchor,
)
from app.core.observability import get_logger
from app.services.document_inventory_merge import _collect_rag_context
from app.services.resilient_llm import ResilientLLMClient

logger = get_logger(__name__)

_FORM_RE = re.compile(r"(?i)\b(?:forma\s+)?((?:DD|AT|AE)[-\s]?\d{1,2}[A-Za-z]?)\b")
_NUM_HEAD = re.compile(
    r"(?m)^\s*(6|7|8)\.(\d+(?:\.\d+)?)\s+(.{12,240}?)$",
)


def bases_revision_hash(text: str) -> str:
    """Huella corta del contenido de bases (stale / versionado)."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:24]


def normalize_form_code(raw: str) -> str:
    return raw.replace(" ", "").replace("–", "-").upper()


def canonical_id_forma(code: str) -> str:
    """Unifica ``DD-05``, ``DD05`` → ``forma_dd_05``."""
    c = normalize_form_code(code)
    m = re.match(r"^(DD|AT|AE)[-_]?(\d{1,2}[A-Z]?)$", c, flags=re.I)
    if m:
        return f"forma_{m.group(1).lower()}_{m.group(2).lower()}"
    tail = re.sub(r"[^A-Z0-9]+", "_", c, flags=re.I).strip("_").lower()
    return f"forma_{tail}"[:120]


def category_for_form(code: str) -> DocumentEnvelope:
    u = normalize_form_code(code)
    if u.startswith("DD"):
        return DocumentEnvelope.LEGAL
    if u.startswith("AT"):
        return DocumentEnvelope.TECHNICAL
    if u.startswith("AE"):
        return DocumentEnvelope.ECONOMIC
    return DocumentEnvelope.LEGAL


def slice_chapters_678(text: str) -> str:
    """Recorte capítulos 6–8 (hasta antes del 9). Si no hay ancla, cadena vacía."""
    m6 = re.search(r"(?is)6\.\-\s*DOCUMENTACI", text)
    m9 = re.search(r"(?is)9\.\-\s*LIMITACI", text)
    if not m6:
        return ""
    end = m9.start() if m9 else min(len(text), m6.start() + 150_000)
    return text[m6.start() : end]


def paso_a_regex_items(text: str, bases_revision: str, source_file: str) -> List[InventoryItem]:
    seen: Set[str] = set()
    out: List[InventoryItem] = []
    for m in _FORM_RE.finditer(text):
        code = normalize_form_code(m.group(1))
        cid = canonical_id_forma(code)
        if cid in seen:
            continue
        seen.add(cid)
        snip = text[max(0, m.start() - 20) : m.end() + 120].replace("\n", " ")[:400]
        pg = None
        pm = re.search(r"=== P[├A]GINA\s+(\d+)\s+===", text[: m.start()][-8000:])
        if pm:
            try:
                pg = int(pm.group(1))
            except ValueError:
                pg = None
        out.append(
            InventoryItem(
                canonical_id=cid,
                display_name=f"Forma {code}",
                description="Detectado por patrón Forma DD/AT/AE en texto de bases.",
                category=category_for_form(code),
                tier=InventoryTier.TIER_A_ANCHORED,
                status=InventoryItemStatus.PENDING,
                anchors=[
                    ItemAnchor(
                        pattern_id="regex_forma_dd_at_ae",
                        snippet=snip or m.group(0),
                        page_index=pg,
                        source_file=source_file,
                        confidence=1.0,
                    )
                ],
                bases_revision=bases_revision,
                generator_hint=f"plantilla_o_llm:{code}",
            )
        )
    return out


def _title_embeds_tier_a_form(title: str, tier_a: List[InventoryItem]) -> bool:
    """True si el título ya menciona una Forma capturada en el Paso A (evita solape)."""
    tier_ids = {it.canonical_id.lower() for it in tier_a}
    for m in _FORM_RE.finditer(title):
        cid = canonical_id_forma(normalize_form_code(m.group(1)))
        if cid.lower() in tier_ids:
            return True
    return False


def paso_b_heuristic_items(
    chunk: str,
    bases_revision: str,
    source_file: str,
    tier_a: List[InventoryItem],
) -> List[InventoryItem]:
    """Líneas 6.x / 7.x / 8.x; omite si el título ya ancla una Forma del Paso A."""
    out: List[InventoryItem] = []
    seen: Set[str] = set()
    for m in _NUM_HEAD.finditer(chunk):
        chap, sub, title = m.group(1), m.group(2), m.group(3).strip()
        if _title_embeds_tier_a_form(title, tier_a):
            continue
        slug = re.sub(r"[^\w]+", "_", f"{chap}_{sub}_{title[:40]}", flags=re.UNICODE).strip("_").lower()
        cid = f"cap_{slug}"[:120]
        if cid in seen or len(title) < 12:
            continue
        seen.add(cid)
        cat = (
            DocumentEnvelope.LEGAL
            if chap == "6"
            else DocumentEnvelope.TECHNICAL
            if chap == "7"
            else DocumentEnvelope.ECONOMIC
        )
        out.append(
            InventoryItem(
                canonical_id=cid,
                display_name=f"{chap}.{sub} {title[:120]}",
                description="Ítem de lista numerada (heurística capítulo 6–8).",
                category=cat,
                tier=InventoryTier.TIER_B_INFERRED,
                status=InventoryItemStatus.PENDING,
                anchors=[
                    ItemAnchor(
                        pattern_id="regex_numero_capitulo",
                        snippet=m.group(0)[:500],
                        source_file=source_file,
                        confidence=0.45,
                    )
                ],
                bases_revision=bases_revision,
            )
        )
    return out


async def paso_b_llm_items(
    chunk: str,
    bases_revision: str,
    source_file: str,
    existing_ids: Set[str],
    correlation_id: str,
) -> List[InventoryItem]:
    if not chunk.strip():
        return []
    llm = ResilientLLMClient()
    prompt = f"""Actúa como un experto en licitaciones públicas y análisis de pliegos de condiciones.
Tu misión es identificar CUALQUIER documento, anexo, formato, carta o constancia que el licitante deba entregar obligatoriamente según el texto de las bases.

FRAGMENTO DE BASES (Capítulos de Documentación y Proposiciones):
{chunk[:24000]}

FILTRO DE EXCLUSIÓN:
Ya tenemos estos identificadores detectados (NO los repitas):
{sorted(existing_ids)[:80]}

INSTRUCCIONES DE EXTRACCIÓN (LicitAI-Forensics):
1. Identificación Flexible: No busques solo "Anexo". Busca: "Formato", "Apéndice", "Carta", "Constancia", "Cédula", "Relación de...", "Manifiesto" o "Documento que acredite...".
2. Referencia Geográfica: Identifica la página aproximada (si aparece en el texto como === PÁGINA X ===) o el contexto del párrafo.
3. Snippet de Credibilidad: Extrae el fragmento exacto de 2-3 líneas donde se solicita el documento. Esto es VITAL para la confianza del usuario.
4. Categorización: Clasifica en legal_administrative, technical o economic.

TAREA: Devuelve exclusivamente un JSON array de objetos con esta estructura:
- "canonical_id": slug único en snake_case (ej: "anexo_1_personalidad")
- "display_name": Título corto y claro (ej: "Anexo 1: Acreditación de Personalidad")
- "description": Resumen de una línea de qué se pide.
- "category": legal_administrative | technical | economic
- "page": número de página (entero o null)
- "snippet": texto literal del requisito capturado (máx 200 caracteres).

Máximo 15 objetos."""
    resp = await llm.generate(
        prompt=prompt,
        system_prompt="Responde ÚNICAMENTE con un JSON array válido. Sin texto explicativo ni bloques markdown.",
        correlation_id=correlation_id or "document_inventory_service",
    )
    if not resp.success or not (resp.response or "").strip():
        return []
    raw = resp.response.strip()
    
    # Intento de rescate de JSON: buscar el bloque [ ... ]
    match = re.search(r"(\[.*\])", raw, re.DOTALL)
    if match:
        raw = match.group(1)
    elif raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)

    # Limpieza de caracteres de control que rompen json.loads (común en Ollama/Llama3)
    raw = raw.replace("\n", " ").replace("\r", " ")
    # Eliminar múltiples espacios
    raw = re.sub(r"\s+", " ", raw)
    
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("document_inventory_llm_json_fail", error=str(e), snippet=raw[:500])
        return []
    if not isinstance(data, list):
        return []
    out: List[InventoryItem] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("canonical_id") or "").strip()[:120]
        if not cid or cid.lower() in existing_ids:
            continue
        name = str(it.get("display_name") or cid)[:220]
        desc = str(it.get("description") or "")[:500]
        snippet = str(it.get("snippet") or "")[:1000]
        page = it.get("page")
        
        cat_s = str(it.get("category") or "legal_administrative").strip()
        try:
            cat = DocumentEnvelope(cat_s)
        except ValueError:
            cat = DocumentEnvelope.LEGAL
            
        existing_ids.add(cid.lower())
        out.append(
            InventoryItem(
                canonical_id=cid,
                display_name=name,
                description=desc,
                category=cat,
                tier=InventoryTier.TIER_B_INFERRED,
                status=InventoryItemStatus.PENDING,
                anchors=[
                    ItemAnchor(
                        pattern_id="llm_forensic_inventory",
                        snippet=snippet or name,
                        page_index=int(page) if page is not None and str(page).isdigit() else None,
                        source_file=source_file,
                        confidence=0.85,
                    )
                ],
                bases_revision=bases_revision,
            )
        )
    return out


_ALLOWED_SYNC_EXT = (".docx", ".xlsx", ".pdf")


def _canonical_token_for_filename(canonical_id: str) -> str:
    return re.sub(r"[^\w\-]+", "_", (canonical_id or "").strip()).strip("_").lower()


def _walk_output_file_pairs(output_root: str) -> List[Tuple[str, str]]:
    """Lista (ruta_relativa_lower, ruta_relativa_original) de artefactos bajo ``output_root``."""
    pairs: List[Tuple[str, str]] = []
    if not os.path.isdir(output_root):
        return pairs
    for dp, _dns, fns in os.walk(output_root):
        for fn in fns:
            if fn.startswith("~$"):
                continue
            low = fn.lower()
            if not any(low.endswith(ext) for ext in _ALLOWED_SYNC_EXT):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, output_root).replace("\\", "/")
            pairs.append((rel.lower(), rel))
    return pairs


def _match_output_relative_path(pairs: List[Tuple[str, str]], token: str) -> Optional[str]:
    if len(token) < 3:
        return None
    for rel_l, rel in pairs:
        if token in rel_l:
            return rel
    return None


def merge_inventory_lists(parts: List[List[InventoryItem]]) -> Tuple[List[InventoryItem], int]:
    seen: Set[str] = set()
    merged: List[InventoryItem] = []
    dup = 0
    for group in parts:
        for it in group:
            k = it.canonical_id.strip().lower()
            if k in seen:
                dup += 1
                continue
            seen.add(k)
            merged.append(it)
    return merged, dup


class DocumentInventoryService:
    """Fachada async para construir ``DocumentInventory``."""

    @staticmethod
    async def build_from_bases_text(
        text: str,
        *,
        session_id: str,
        source_file: str,
        use_llm: bool,
        correlation_id: str = "",
    ) -> DocumentInventory:
        """
        Construye el inventario desde texto de bases (completo o agregado).

        Args:
            text: Contenido UTF-8 (bases legibles, OCR concatenado, etc.).
            session_id: Id de sesión para el contenedor de salida.
            source_file: Etiqueta de procedencia (nombre lógico).
            use_llm: Si True, Paso B semántico vía ``ResilientLLMClient``; si False,
                heurística de líneas numeradas + filtro anti-solape.
            correlation_id: Trazabilidad LLM.

        Returns:
            ``DocumentInventory`` validado (stats recalculados).
        """
        rev = bases_revision_hash(text)
        tier_a = paso_a_regex_items(text, rev, source_file)
        chunk = slice_chapters_678(text)
        if not chunk.strip():
            chunk = text

        existing_ids = {it.canonical_id.lower() for it in tier_a}
        if use_llm:
            tier_b = await paso_b_llm_items(
                chunk, rev, source_file, set(existing_ids), correlation_id
            )
        else:
            tier_b = paso_b_heuristic_items(chunk, rev, source_file, tier_a)

        merged, _dup_n = merge_inventory_lists([tier_a, tier_b])
        inv = DocumentInventory(session_id=session_id, revision=1, items=merged)
        logger.info(
            "document_inventory_built",
            session_id=session_id,
            tier_a=len(tier_a),
            tier_b=len(tier_b),
            total=len(merged),
            use_llm=use_llm,
        )
        return inv

    @staticmethod
    async def build_for_session(
        session_id: str,
        *,
        use_llm: bool | None = None,
        correlation_id: str = "",
    ) -> DocumentInventory:
        """
        Agrega texto desde Chroma (mismas consultas que ``document_inventory_merge``)
        y delega en ``build_from_bases_text``.
        """
        if use_llm is None:
            use_llm = bool(getattr(settings, "DOCUMENT_INVENTORY_SERVICE_USE_LLM", False))
        max_chars = max(8000, int(settings.DOCUMENT_INVENTORY_CONTEXT_CHARS))
        ctx = _collect_rag_context(session_id, max_chars)
        if len(ctx) < 80:
            logger.info("document_inventory_session_short_context", session_id=session_id, n=len(ctx))
        return await DocumentInventoryService.build_from_bases_text(
            ctx,
            session_id=session_id,
            source_file="session_rag_aggregate",
            use_llm=use_llm,
            correlation_id=correlation_id,
        )

    @staticmethod
    def sync_inventory_status_from_disk(
        inv: DocumentInventory,
        session_id: str,
        output_root: Optional[str] = None,
    ) -> DocumentInventory:
        """
        Marca ``GENERATED`` y ``relative_output_path`` cuando el token del
        ``canonical_id`` aparece en la ruta de un archivo bajo ``/data/outputs/<session>``.

        Solo muta ítems en ``PENDING``; no altera ``external_input``, ``na``, etc.
        """
        root = output_root or os.path.join("/data", "outputs", session_id)
        pairs = _walk_output_file_pairs(root)
        new_items: List[InventoryItem] = []
        for it in inv.items:
            if it.status != InventoryItemStatus.PENDING:
                new_items.append(it)
                continue
            tok = _canonical_token_for_filename(it.canonical_id)
            hit = _match_output_relative_path(pairs, tok)
            if hit:
                new_items.append(
                    it.model_copy(
                        update={
                            "status": InventoryItemStatus.GENERATED,
                            "relative_output_path": hit,
                        }
                    )
                )
            else:
                new_items.append(it)
        return DocumentInventory(
            session_id=inv.session_id,
            schema_version=inv.schema_version,
            revision=inv.revision,
            items=new_items,
            updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def sync_inventory_payload_to_dict(
        inventory_payload: Union[DocumentInventory, Dict[str, Any]],
        *,
        session_id: str,
        output_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Valida payload, sincroniza con disco y devuelve dict JSON-ready (stats recalculados).
        """
        inv = (
            inventory_payload
            if isinstance(inventory_payload, DocumentInventory)
            else DocumentInventory.model_validate(inventory_payload)
        )
        synced = DocumentInventoryService.sync_inventory_status_from_disk(
            inv, session_id, output_root=output_root
        )
        return synced.model_dump(mode="json")

    @staticmethod
    async def sync_inventory_to_session_memory(
        memory: Any,
        session_id: str,
        inventory_payload: Dict[str, Any],
        *,
        output_root: Optional[str] = None,
    ) -> DocumentInventory:
        """
        Sincroniza inventario con disco y persiste ``document_inventory`` en la sesión.

        Usa lectura/escritura atómica del estado de sesión (merge de claves).
        """
        dump = DocumentInventoryService.sync_inventory_payload_to_dict(
            inventory_payload,
            session_id=session_id,
            output_root=output_root,
        )
        fresh = await memory.get_session(session_id) or {}
        fresh["document_inventory"] = dump
        await memory.save_session(session_id, fresh)
        return DocumentInventory.model_validate(dump)
