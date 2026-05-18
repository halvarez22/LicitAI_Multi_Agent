"""
tender_router_service.py — Router de Peritaje Legal (Triage Normativo).

Pipeline de Dos Pasos:
  1. get_triage()       — Identificar la ley aplicable usando el modelo local.
  2. get_must_have_*()  — Recuperar la Matriz de Obligatorios para esa ley.

Rollback: ROUTER_PROMPT_VERSION=v1 en .env revierte a prompts v1 sin señales.
"""
import json
import asyncio
import unicodedata
from typing import Any, Dict, List, Optional

from app.core.observability import get_logger
from app.config.settings import settings
from app.services.vector_service import VectorDbServiceClient
from app.models.normative_policy import NormativePolicy
from sqlalchemy.future import select

logger = get_logger(__name__)


class TenderRouterService:
    """
    Servicio de Ruteo de Licitaciones.
    Encapsula Triage Normativo + Matriz de Obligatorios + Política de Enforcement.
    """

    # ------------------------------------------------------------------ #
    # 1. TRIAGE NORMATIVO                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def get_triage_text(session_id: str, vector_db: VectorDbServiceClient) -> str:
        """Obtiene los primeros fragmentos del documento para alimentar el triage."""
        try:
            res = await asyncio.to_thread(
                vector_db.query_texts,
                session_id=session_id,
                query="convocatoria objeto de la licitación bases de concurso ley aplicable",
                n_results=8,
            )
            docs = res.get("documents", [])
            return "\n\n".join(docs)
        except Exception as e:
            logger.error("failed_to_get_triage_text", error=str(e))
            return ""

    @staticmethod
    async def get_triage(session_id: str, vector_db: VectorDbServiceClient) -> Dict[str, Any]:
        """
        Paso 1 — Triage Normativo (Local LLM).
        Versión controlada por settings.ROUTER_PROMPT_VERSION (v1 | v2).
        Rollback instantáneo: ROUTER_PROMPT_VERSION=v1 en .env
        """
        from app.services.llm_service import LLMServiceClient
        from app.services.router_prompts import build_triage_prompt

        fallback: Dict[str, Any] = {
            "law": "LAASSP",
            "jurisdiction": "FEDERAL",
            "tender_category": "BIENES",
            "confidence": 0.0,
            "signals_detected": [],
        }

        first_pages_text = await TenderRouterService.get_triage_text(session_id, vector_db)
        if not first_pages_text:
            logger.warning("triage_no_text_available", session_id=session_id)
            return fallback

        prompt_version = getattr(settings, "ROUTER_PROMPT_VERSION", "v2")
        prompt = build_triage_prompt(first_pages_text, version=prompt_version)

        try:
            client = LLMServiceClient()
            llm_out = await client.generate(
                prompt=prompt,
                system_prompt=(
                    "Clasifica marco normativo de licitacion y responde solo JSON valido."
                ),
                model=None,
            )
            if llm_out.get("error"):
                raise RuntimeError(str(llm_out.get("error")))
            raw_text = str(llm_out.get("response", "")).strip()
            if not raw_text:
                raise RuntimeError("empty_llm_response")
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            triage: Dict[str, Any] = json.loads(raw_text)
            triage.setdefault("signals_detected", [])
            logger.info(
                "tender_triage_completed",
                session_id=session_id,
                prompt_version=prompt_version,
                law=triage.get("law"),
                confidence=triage.get("confidence"),
                signals_count=len(triage.get("signals_detected", [])),
            )
            return triage
        except Exception as e:
            logger.error("tender_triage_failed", session_id=session_id, error=str(e))
            return fallback

    # ------------------------------------------------------------------ #
    # 2. MATRIZ DE OBLIGATORIOS                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def get_normative_policy_record(law: str, category: str) -> Optional[NormativePolicy]:
        """Recupera la política normativa desde la base de datos."""
        from app.memory.factory import MemoryAdapterFactory
        adapter = MemoryAdapterFactory.get_instance()
        if not adapter or not hasattr(adapter, "async_session"):
            return None
            
        async with adapter.async_session() as session:
            stmt = select(NormativePolicy).filter_by(law=law, category=category, is_active=True)
            res = await session.execute(stmt)
            return res.scalars().first()

    @staticmethod
    async def get_must_have_list(law: str, category: str) -> List[str]:
        """Retorna etiquetas obligatorias por ley + sobrecarga de categoría (desde DB)."""
        policy = await TenderRouterService.get_normative_policy_record(law, category)
        if policy:
            return list(policy.mandatory_labels)
            
        # Fallback legacy si la DB falla o no hay registro
        matrix: Dict[str, List[str]] = {
            "LAASSP": [
                "LEG_ACTA_CONSTITUTIVA", "LEG_PODER_NOTARIAL", "LEG_IDENTIDAD_CANDIDATO",
                "FIS_SAT_OPINION", "FIS_ESTATAL_OPINION", "DECL_ART_50_51",
                "DECL_INTEGRIDAD", "DECL_MIPYME", "DECL_NACIONALIDAD",
                "TEC_PROPUESTA_DETALLADA", "ECO_PRECIOS_UNITARIOS",
            ],
            "LOPSRM": [
                "LEG_ACTA_CONSTITUTIVA", "FIS_SAT_OPINION", "TEC_EXPERIENCIA_CURRICULUM",
                "TEC_PLANTILLA_TECNICA", "ECO_PRECIOS_UNITARIOS", "ECO_EXPLOSION_INSUMOS",
            ],
        }
        return list(matrix.get(law, matrix.get("LAASSP", [])))

    @staticmethod
    async def get_must_have_policy(law: str, category: str) -> Dict[str, Dict[str, Any]]:
        """
        Política determinista por etiqueta: acción esperada + aliases de matching.
        Ahora lee aliases desde la DB si están disponibles.
        """
        must_have = await TenderRouterService.get_must_have_list(law, category)
        db_policy = await TenderRouterService.get_normative_policy_record(law, category)
        db_aliases = db_policy.alias_map if db_policy else {}

        _alias_map: Dict[str, List[str]] = {
            "LEG_ACTA_CONSTITUTIVA":          ["acta constitutiva", "constitucion de la sociedad"],
            "LEG_PODER_NOTARIAL":             ["poder notarial", "apoderado legal"],
            "LEG_IDENTIDAD_CANDIDATO":        ["anexo iii", "anexo 3", "anexo ii", "anexo 2", "datos generales", "identidad del licitante"],
            "FIS_SAT_OPINION":                ["opinion de cumplimiento sat", "32-d", "opinion sat"],
            "FIS_ESTATAL_OPINION":            ["opinion de cumplimiento estatal", "opinion estatal", "cadpe"],
            "DECL_MIPYME":                    ["mipyme", "estratificacion", "micro pequena mediana"],
            "DECL_INTEGRIDAD":                ["declaracion de integridad", "manifiesto de integridad"],
            "DECL_ART_50_51":                 ["articulo 50", "articulo 51", "impedimento legal"],
            "DECL_NACIONALIDAD":              ["nacionalidad mexicana", "licitante mexicano"],
            "ECO_PRECIOS_UNITARIOS":          ["precios unitarios", "analisis de precios unitarios"],
            "TEC_PROPUESTA_DETALLADA":        ["propuesta tecnica", "propuesta detallada"],
        }
        
        # Fusionar con aliases de DB
        for k, v in db_aliases.items():
            if k in _alias_map:
                _alias_map[k] = list(set(_alias_map[k] + v))
            else:
                _alias_map[k] = v

        policy: Dict[str, Dict[str, Any]] = {}
        for label in must_have:
            expected_action = "presentar_fisico" if label.startswith(("LEG_", "FIS_")) else "generar"
            policy[label] = {
                "expected_action": expected_action,
                "aliases": _alias_map.get(label, [label.split("_")[-1].lower()]),
            }
        return policy

    @staticmethod
    def normalize_text_for_policy_match(text: str) -> str:
        """Normaliza texto para matching determinista (aliases / compuestos)."""
        t = unicodedata.normalize("NFKD", text or "")
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
        return t.lower().strip()

    @staticmethod
    async def match_must_have_from_normalized_text(
        text_to_check: str, law: str, category: str
    ) -> Optional[Dict[str, Any]]:
        """
        Determina si el texto del ítem coincide con una etiqueta Must-Have.

        Orden: compuesto SAT (32-D / SAT) → compuesto estatal (Querétaro/CADPE/UNAQ + opinión)
        → barrido por aliases de la política.
        """
        policy = await TenderRouterService.get_must_have_policy(law, category)
        if not text_to_check.strip():
            return None

        def has_any(*subs: str) -> bool:
            return any(s in text_to_check for s in subs)

        opinion_like = has_any("opinion", "opini", "constancia", "cumplimiento")
        fiscal_like = has_any(
            "fiscal",
            "fiscales",
            "obligaciones fiscales",
            "recaudacion",
            "secretaria de finanzas",
            "finanzas del estado",
            "opinion de cumplimiento",
        )
        fiscal_negative = has_any(
            "fianza",
            "garantia",
            "multa",
            "pena convencional",
            "penalizacion",
            "sancion",
        )
        explicit_sat = has_any("32-d", "32 d", "32d", "32-d.", "articulo 32-d", "articulo 32 d")
        sat_ctx = explicit_sat or has_any(
            "servicio de administracion tributaria",
            " el sat",
            "del sat",
            "obligaciones fiscales federales",
            "hacienda federal",
        )
        est_ctx = has_any(
            "queretaro",
            "qro.",
            " qro ",
            "cadpe",
            "unaq",
            "uaq",
            "universidad autonoma de queretaro",
            "estado de queretaro",
            "comite estatal de adquisiciones",
        )

        if opinion_like and explicit_sat and "FIS_SAT_OPINION" in policy:
            return {
                "label": "FIS_SAT_OPINION",
                "matched_on": "composite_explicit_sat_opinion",
                "expected_action": policy["FIS_SAT_OPINION"]["expected_action"],
            }
        if (
            opinion_like
            and fiscal_like
            and not fiscal_negative
            and est_ctx
            and "FIS_ESTATAL_OPINION" in policy
            and not explicit_sat
        ):
            return {
                "label": "FIS_ESTATAL_OPINION",
                "matched_on": "composite_estatal_opinion",
                "expected_action": policy["FIS_ESTATAL_OPINION"]["expected_action"],
            }
        if opinion_like and sat_ctx and "FIS_SAT_OPINION" in policy:
            return {
                "label": "FIS_SAT_OPINION",
                "matched_on": "composite_sat_context_opinion",
                "expected_action": policy["FIS_SAT_OPINION"]["expected_action"],
            }

        for label, pol in policy.items():
            for alias in pol.get("aliases", []):
                norm_alias = TenderRouterService.normalize_text_for_policy_match(alias)
                if norm_alias and norm_alias in text_to_check:
                    return {
                        "label": label,
                        "matched_on": alias,
                        "expected_action": pol.get("expected_action", "generar"),
                    }
        return None

    @staticmethod
    async def get_taxonomy_allowlist(law: str, category: str) -> List[str]:
        """
        Vocabulario cerrado para label_taxonomica en Compliance (Must-Have + OTRO).
        """
        must_have = await TenderRouterService.get_must_have_list(law, category)
        labels = list(dict.fromkeys(must_have))
        if "OTRO" not in labels:
            labels.append("OTRO")
        return labels

    @staticmethod
    def taxonomy_anchor_hints_markdown() -> str:
        """Pistas de anclaje para el prompt (bases tipo convocatoria con anexos)."""
        return (
            "- Si el texto menciona **Anexo II / III / IV** o **Datos generales** del licitante "
            "(identidad, personalidad, CURP, identificación): prefiera **LEG_IDENTIDAD_CANDIDATO**.\n"
            "- Si menciona **Opinión de cumplimiento**, **32-D** o **SAT** / obligaciones fiscales **federales**: "
            "**FIS_SAT_OPINION**.\n"
            "- Si coexisten **Querétaro** (o **CADPE**, **UNAQ**, **UAQ**) y **opinión/cumplimiento** fiscal "
            "**sin** 32-D explícito: **FIS_ESTATAL_OPINION**.\n"
            "- Si ninguna etiqueta encaja con evidencia literal: **OTRO** (sin inventar códigos nuevos)."
        )

    # ------------------------------------------------------------------ #
    # 3. REGLAS CRÍTICAS                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def get_critical_rules(law: str) -> List[str]:
        """Reglas críticas penalizables por ley (desde DB)."""
        from app.memory.factory import MemoryAdapterFactory
        adapter = MemoryAdapterFactory.get_instance()
        if not adapter or not hasattr(adapter, "async_session"):
            return []
            
        async with adapter.async_session() as session:
            # Buscamos cualquier política de esta ley para obtener sus reglas
            stmt = select(NormativePolicy).filter_by(law=law, is_active=True)
            res = await session.execute(stmt)
            policy = res.scalars().first()
            return list(policy.critical_rules) if policy else []
