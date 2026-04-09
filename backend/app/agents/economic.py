import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

try:
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # pragma: no cover - entornos sin rapidfuzz aún
    _rf_fuzz = None
from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import ResilientLLMClient
from app.services.vector_service import VectorDbServiceClient
from app.services.analyst_output_normalize import (
    normalize_alcance_operativo_list,
    normalize_reglas_economicas_dict,
)
from app.economic_validation.engine import validate_economic_proposal
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus

logger = logging.getLogger(__name__)

class EconomicAgent(BaseAgent):
    """
    Agente 5: Estratega Económico.
    Analiza los conceptos de la licitación y genera la propuesta financiera.
    Utiliza el catálogo de la empresa para calcular costos y márgenes.
    """
    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="economic_001",
            name="Estratega de Propuesta Económica",
            description="Motor de cálculo y cotización para licitaciones.",
            context_manager=context_manager
        )
        self.llm = ResilientLLMClient()
        self.vector_db = VectorDbServiceClient()

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        company_id = agent_input.company_id
        correlation_id = agent_input.correlation_id or "no-id"
        
        print(f"💰 [Económico] Iniciando Análisis Financiero para: {session_id} - correlation_id: {correlation_id}")

        # 1. Recuperar Hallazgos de Compliance (La Lista Maestra)
        context = await self.context_manager.get_global_context(session_id)
        session_state = context.get("session_state", {})
        
        master_list = agent_input.company_data.get("compliance_master_list")

        if not master_list:
            tasks = session_state.get("tasks_completed", [])
            for task in reversed(tasks):
                tname = task.get("task", "")
                if tname == "master_compliance_list":
                    master_list = task.get("result")
                    break
                if tname == "stage_completed:compliance":
                    res = task.get("result") or {}
                    master_list = res.get("data") if isinstance(res, dict) else None
                    if master_list:
                        break
        
        if not master_list:
            master_list = session_state.get("master_compliance_list", {})

        # 2. Recuperar Catálogo de Precios de la Empresa y partidas tabulares de la sesión (Excel)
        company_catalog = await self._get_company_catalog(company_id)
        session_line_items: List[Dict] = []
        try:
            session_line_items = await self.context_manager.memory.get_line_items_for_session(
                session_id
            )
        except Exception as e:
            logger.warning("[EconomicAgent] No se pudieron leer session_line_items: %s", e)
        tabular_catalog = self._tabular_rows_to_catalog_entries(session_line_items)

        analisis_bases = self._extract_analisis_bases_from_session(session_state)
        reglas_bases = normalize_reglas_economicas_dict(
            analisis_bases.get("reglas_economicas") if isinstance(analisis_bases, dict) else None
        )
        alcance_bases = normalize_alcance_operativo_list(
            analisis_bases.get("alcance_operativo") if isinstance(analisis_bases, dict) else None
        )
        datos_tab = (
            analisis_bases.get("datos_tabulares")
            if isinstance(analisis_bases, dict) and isinstance(analisis_bases.get("datos_tabulares"), dict)
            else {}
        )
        if datos_tab.get("alerta_faltante"):
            print(f"    [!] {str(datos_tab['alerta_faltante'])[:280]}", flush=True)

        bases_economic_context = self._format_bases_economic_context(
            reglas_bases, alcance_bases, datos_tab
        )
        alertas_contexto_bases = self._build_bases_economic_alertas(reglas_bases, datos_tab)
        alcance_catalog = self._alcance_rows_to_catalog_entries(alcance_bases)

        # 3. Identificar requerimientos que necesitan COTIZACIÓN
        tech_requirements = master_list.get("tecnico") or master_list.get("técnico") or []
        print(f"    [DEBUG] Técnico items count: {len(tech_requirements)}", flush=True)
        
        if not tech_requirements:
            print("    [-] No se detectaron ítems cotizables en la auditoría previa.", flush=True)
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id=self.agent_id,
                session_id=session_id,
                message="No hay requerimientos económicos detectables.",
                correlation_id=correlation_id
            )

        # HITO: Catálogo empresa + partidas Excel + filas de alcance operativo (bases) + RAG.
        print(f"    [*] Realizando búsqueda semántica de precios para {len(tech_requirements)} ítems...")
        enriched_catalog = list(company_catalog) + tabular_catalog + alcance_catalog
        for req in tech_requirements:
            label = (
                req.get("label")
                or req.get("descripcion")
                or req.get("titulo")
                or req.get("texto")
                or ""
            )
            label = str(label).strip()
            if not label:
                continue
            
            # Consultamos la base vectorial por este concepto
            rag_results = self.vector_db.query_texts(session_id, f"precio unitario de {label}", n_results=3)
            docs = rag_results.get("documents", [])
            if docs:
                # Añadimos un ítem "virtual" al catálogo basado en lo hallado en RAG
                context_str = " ".join(docs)
                # Este ítem virtual permitirá al LLM en _calculate_proposal tomar decisiones informadas
                enriched_catalog.append({
                    "name": f"REFERENCIA_RAG_{label}",
                    "description": f"Encontrado en documentos de la sesión: {context_str}",
                    "price": 0.0, # El LLM lo extraerá del texto de la descripción
                    "is_rag_reference": True
                })

        # 4. Cálculo de Propuesta (mapeo semántico con marco de bases del Analista)
        calculation_result = await self._calculate_proposal(
            tech_requirements,
            enriched_catalog,
            correlation_id,
            bases_economic_context=bases_economic_context,
        )
        
        if isinstance(calculation_result, dict) and calculation_result.get("status") == "error":
             return AgentOutput(
                status=AgentStatus.ERROR,
                agent_id=self.agent_id,
                session_id=session_id,
                error=calculation_result.get("message", "Error desconocido en cálculo"),
                correlation_id=correlation_id
             )
        
        if isinstance(calculation_result, list):
             proposal_draft = calculation_result
             alertas: List[Any] = []
        else:
             proposal_draft = calculation_result.get("items", []) or []
             alertas = calculation_result.get("alertas") or []

        proposal_draft = self._apply_tabular_prices_to_proposal(
            proposal_draft, tech_requirements, session_line_items
        )
        proposal_draft = self._ensure_supervisor_no_cost_item(
            proposal_draft, alcance_bases, tech_requirements
        )

        # 5. Detección de Gaps Económicos
        # El LLM a menudo devuelve "matched" con precio 0 o sin precio: eso NO es cotizable.
        economic_gaps: List[Dict] = []
        for item in proposal_draft:
            st = (item.get("status") or "").lower()
            pu = item.get("precio_unitario")
            try:
                # If explicitly missing, set to -1 to trigger gap
                pu_f = float(pu) if pu is not None and str(pu).strip() != "" else -1.0
            except (TypeError, ValueError):
                pu_f = -1.0 # Set to -1 so we can distinguish from a user typing 0
            if st == "price_missing" or pu_f < 0:
                economic_gaps.append(item)
        
        if economic_gaps:
            print(f"    🚨 GAP ECONÓMICO: Faltan {len(economic_gaps)} precios unitarios.")
            
            # --- Hito 6: Generar pending_questions econonómicas ---
            missing_fields = []
            for gap in economic_gaps:
                concepto = gap.get("concepto", "Concepto técnico")
                missing_fields.append({
                    "field": f"price_{gap.get('concepto_id', concepto)}", # ID virtual o nombre
                    "label": f"Precio de: {concepto}",
                    "question": f"¿Cuál es el **precio unitario** (sin IVA) para el concepto: **{concepto}**?",
                    "document_hint": "Catálogo de precios o cotización base",
                    "type": "economic_price",
                    "original_item": gap
                })
            
            await self._save_pending_questions(session_id, missing_fields)

            nombres_conceptos = [f"**{gap.get('concepto', 'Concepto técnico')}**" for gap in economic_gaps]
            conceptos_str = ", ".join(nombres_conceptos)
            
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=f"Necesito que proporciones los precios unitarios para {len(economic_gaps)} conceptos técnicos detectados: {conceptos_str}.",
                data={
                    "missing": missing_fields,
                    "alertas_contexto_bases": alertas_contexto_bases,
                    "contexto_bases_analista": {
                        "reglas_economicas": reglas_bases,
                        "alcance_operativo_filas": len(alcance_bases),
                        "datos_tabulares": dict(datos_tab),
                    },
                },
                correlation_id=correlation_id
            )

        # 6. Consolidación Final
        total_base = sum(item.get("subtotal", 0) for item in proposal_draft)
        alertas_merged = list(alertas if isinstance(alertas, list) else []) + alertas_contexto_bases
        validation_result = validate_economic_proposal(
            proposal_items=proposal_draft,
            currency="MXN",
            total_base=float(total_base),
            grand_total=float(total_base * 1.15),
            reglas_economicas=reglas_bases,
            session_name=str(session_state.get("name") or session_id),
        )
        if validation_result.blocking_issues:
            missing_fields = [
                {
                    "field": f"validation_rule_{i}",
                    "label": "Resolver validación económica bloqueante",
                    "question": issue,
                    "document_hint": "Bases, catálogo y anexos económicos",
                    "type": "economic_validation_blocking",
                }
                for i, issue in enumerate(validation_result.blocking_issues, start=1)
            ]
            await self._save_pending_questions(session_id, missing_fields)
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id=self.agent_id,
                session_id=session_id,
                message=(
                    "La propuesta económica requiere correcciones antes de cerrar: "
                    f"{len(validation_result.blocking_issues)} validaciones bloqueantes."
                ),
                data={
                    "missing": missing_fields,
                    "alertas_contexto_bases": alertas_contexto_bases,
                    "validation_result": validation_result.model_dump(mode="json"),
                    "contexto_bases_analista": {
                        "reglas_economicas": reglas_bases,
                        "alcance_operativo_filas": len(alcance_bases),
                        "datos_tabulares": dict(datos_tab),
                    },
                },
                correlation_id=correlation_id,
            )
        final_result = {
            "status": "complete",
            "currency": "MXN",
            "items": proposal_draft,
            "total_base": total_base,
            "margin_suggested": "15%",
            "grand_total": total_base * 1.15,
            "analisis_precios": {
                "alertas": alertas_merged,
            },
            "validation_result": validation_result.model_dump(mode="json"),
            "contexto_bases_analista": {
                "reglas_economicas": reglas_bases,
                "alcance_operativo_filas": len(alcance_bases),
                "datos_tabulares": dict(datos_tab),
            },
        }

        await self.context_manager.record_task_completion(session_id, "economic_proposal", final_result)
        print(f"💰 [Económico] Propuesta Calculada: ${final_result['grand_total']:.2f}")
        
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data=final_result,
            correlation_id=correlation_id
        )

    def _extract_analisis_bases_from_session(self, session_state: Dict[str, Any]) -> Dict[str, Any]:
        """Último resultado de `analisis_bases` en tasks_completed, o {}."""
        for task in reversed(session_state.get("tasks_completed") or []):
            if task.get("task") == "analisis_bases":
                res = task.get("result")
                return res if isinstance(res, dict) else {}
        return {}

    def _ensure_supervisor_no_cost_item(
        self,
        proposal_items: List[Dict[str, Any]],
        alcance: List[Dict[str, str]],
        tech_requirements: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Inyecta un renglón de supervisión sin costo cuando el alcance lo exige."""
        joined = " ".join(
            str(r.get("texto_literal_fila") or r.get("puesto_funcion_o_servicio") or "")
            for r in (alcance or [])
        )
        req_joined = " ".join(
            str(r.get("label") or r.get("descripcion") or r.get("texto") or "")
            for r in (tech_requirements or [])
            if isinstance(r, dict)
        )
        source = f"{joined} {req_joined}".strip()
        needs_supervisor = re.search(r"(?i)(supervisor|coordinador|jefe\s*de\s*turno|vigilancia|guardia|turno)", source)
        no_cost_signal = re.search(r"(?i)(sin\s*costo|0\.00|sin\s*cargo|costos?\s+indirectos?)", source)
        if not needs_supervisor:
            return proposal_items
        has_item = False
        for it in proposal_items:
            text = f"{it.get('concepto','')} {it.get('descripcion','')}"
            if re.search(r"(?i)(supervisor|coordinador|jefe\s*de\s*turno|vigilancia|guardia)", text):
                has_item = True
                if no_cost_signal or re.search(r"(?i)(sin\s*costo|0\.00|sin\s*cargo|costos?\s+indirectos?)", text):
                    it["precio_unitario"] = 0.0
                    it["subtotal"] = 0.0
                    it["supervisor_sin_costo"] = True
        if has_item:
            return proposal_items
        return proposal_items + [{
            "concepto": "Supervisor General (Sin costo)",
            "descripcion": "Supervisor General (Sin costo, incluido en costos indirectos)",
            "concepto_id": "AUTO-SUP-NC",
            "cantidad": 1,
            "precio_unitario": 0.0,
            "subtotal": 0.0,
            "status": "matched",
            "incluir_en_indirectos": True,
            "supervisor_sin_costo": True,
        }]

    def _format_bases_economic_context(
        self,
        reglas: Dict[str, str],
        alcance: List[Dict[str, str]],
        datos_tab: Dict[str, Any],
    ) -> str:
        """Texto para el LLM: reglas citadas, alcance tabular y estado de partidas en sesión."""
        lines: List[str] = ["=== REGLAS ECONÓMICAS (literal bases) ==="]
        _def = "No especificado"
        any_rule = False
        for k, v in reglas.items():
            if v and v != _def:
                lines.append(f"- {k}: {v}")
                any_rule = True
        if not any_rule:
            lines.append("(Sin reglas económicas explícitas distintas de 'No especificado'.)")

        lines.append("\n=== ALCANCE OPERATIVO (filas resumidas) ===")
        if not alcance:
            lines.append("(Sin filas de alcance operativo en el análisis de bases.)")
        else:
            for i, row in enumerate(alcance[:30]):
                frag = row.get("texto_literal_fila") or row.get("puesto_funcion_o_servicio") or ""
                lines.append(
                    f"Fila {i + 1}: área={row.get('ubicacion_o_area', '')!s} | "
                    f"puesto/servicio={row.get('puesto_funcion_o_servicio', '')!s} | "
                    f"cant={row.get('cantidad_o_elementos', '')!s} | turno={row.get('turno', '')!s} | "
                    f"literal={str(frag)[:220]}"
                )
            if len(alcance) > 30:
                lines.append(f"(... {len(alcance) - 30} filas más omitidas en el resumen.)")

        lines.append("\n=== DATOS TABULARES (sesión vs bases) ===")
        lines.append(f"line_items_count: {datos_tab.get('line_items_count', 'N/D')}")
        lines.append(
            f"texto_sugiere_partidas_o_anexo_tabular: "
            f"{datos_tab.get('texto_sugiere_partidas_o_anexo_tabular', False)}"
        )
        af = datos_tab.get("alerta_faltante")
        if isinstance(af, str) and af.strip():
            lines.append(f"ALERTA_TABULAR: {af.strip()}")
        return "\n".join(lines)

    def _build_bases_economic_alertas(
        self,
        reglas: Dict[str, str],
        datos_tab: Dict[str, Any],
    ) -> List[str]:
        """Alertas determinísticas para anexar a analisis_precios (y en WAITING_FOR_DATA)."""
        out: List[str] = []
        _def = "No especificado"
        af = datos_tab.get("alerta_faltante")
        if isinstance(af, str) and af.strip():
            out.append(f"[Partidas/sesión] {af.strip()}")
        for key in (
            "criterio_importe_minimo_o_plazo_inferior",
            "criterio_importe_maximo_o_plazo_superior",
            "meses_o_periodo_minimo_citado",
            "meses_o_periodo_maximo_citado",
            "vinculacion_presupuesto_partida",
            "referencia_partidas_anexos_citados",
            "modalidad_contratacion_observada",
            "otras_reglas_oferta_precio",
        ):
            val = reglas.get(key, _def)
            if val != _def:
                out.append(f"[Bases] {key}: {val} — revisar coherencia con totales y plazos.")
        return out

    def _alcance_rows_to_catalog_entries(self, rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Convierte filas de alcance_operativo en ítems guía (sin precio) para el mapeo del LLM."""
        out: List[Dict[str, Any]] = []
        for row in rows[:50]:
            name = (row.get("puesto_funcion_o_servicio") or row.get("texto_literal_fila") or "").strip()
            if len(name) < 3:
                continue
            qty = row.get("cantidad_o_elementos") or ""
            desc_parts = [
                row.get("ubicacion_o_area"),
                row.get("turno"),
                row.get("horario"),
                row.get("dias_aplicables"),
                row.get("texto_literal_fila"),
            ]
            desc = " | ".join(p for p in desc_parts if p)
            out.append(
                {
                    "name": name[:512],
                    "description": (
                        f"(Alcance operativo en bases) {desc[:1500]} "
                        f"Cantidad referida en bases: {qty}"
                    ).strip(),
                    "price": 0.0,
                    "is_alcance_operativo": True,
                }
            )
        return out

    def _tabular_rows_to_catalog_entries(self, rows: List[Dict]) -> List[Dict]:
        """Convierte filas de session_line_items en ítems de catálogo consumibles por el LLM."""
        out: List[Dict] = []
        for row in rows:
            out.append(
                {
                    "name": (row.get("concepto_norm") or "")[:512],
                    "description": (row.get("concepto_raw") or "")[:2000],
                    "price": float(row.get("precio_unitario") or 0),
                    "unidad": row.get("unidad"),
                    "is_session_tabular": True,
                }
            )
        return out

    def _normalize_econ_label(self, value: Any) -> str:
        t = re.sub(r"\s+", " ", str(value).strip().lower())
        return t[:2000] if len(t) > 2000 else t

    def _tabular_similarity(self, a: str, b: str) -> float:
        """
        Similitud en [0, 1] entre dos etiquetas ya normalizadas.
        Usa rapidfuzz (partial + token_sort) si está instalado; si no, difflib + orden de tokens.
        """
        if not a or not b:
            return 0.0
        if _rf_fuzz is not None:
            return max(
                _rf_fuzz.partial_ratio(a, b) / 100.0,
                _rf_fuzz.token_sort_ratio(a, b) / 100.0,
            )
        ta = " ".join(sorted(a.split()))
        tb = " ".join(sorted(b.split()))
        return max(
            SequenceMatcher(None, a, b).ratio(),
            SequenceMatcher(None, ta, tb).ratio(),
        )

    def _fuzzy_best_tabular_row(
        self,
        candidates: List[str],
        by_norm: Dict[str, Dict],
    ) -> Tuple[Optional[Dict], float]:
        """
        Elige la fila tabular cuya concepto_norm maximiza similitud frente a los candidatos.
        Umbral por defecto 0.68 (ECON_TABULAR_FUZZY_THRESHOLD).
        """
        if not candidates or not by_norm:
            return None, 0.0
        try:
            thr = float(os.getenv("ECON_TABULAR_FUZZY_THRESHOLD", "0.68"))
        except ValueError:
            thr = 0.68
        thr = max(0.5, min(0.95, thr))

        best_row: Optional[Dict] = None
        best_sc = 0.0
        for c in candidates:
            if not c or len(c) < 6:
                continue
            for tnorm, row in by_norm.items():
                if len(tnorm) < 3:
                    continue
                sc = self._tabular_similarity(c, tnorm)
                if sc > best_sc:
                    best_sc = sc
                    best_row = row
        if best_row is not None and best_sc >= thr:
            return best_row, best_sc
        return None, best_sc

    def _apply_tabular_prices_to_proposal(
        self,
        proposal_draft: List[Dict],
        tech_requirements: List[Dict],
        tabular_rows: List[Dict],
    ) -> List[Dict]:
        """
        Post-proceso: asigna precio_unitario desde partidas Excel si el LLM dejó gap.
        Orden: coincidencia exacta → subcadena (textos largos) → matching difuso (rapidfuzz/difflib).
        """
        if not tabular_rows or not proposal_draft:
            return proposal_draft
        by_norm = {r["concepto_norm"]: r for r in tabular_rows if r.get("concepto_norm")}
        req_by_id: Dict[str, Dict] = {}
        for r in tech_requirements:
            rid = r.get("id")
            if rid is not None:
                req_by_id[str(rid)] = r

        for item in proposal_draft:
            st = (item.get("status") or "").lower()
            pu = item.get("precio_unitario")
            try:
                pu_f = float(pu) if pu is not None and pu != "" else 0.0
            except (TypeError, ValueError):
                pu_f = 0.0
            need_fill = pu_f <= 0 or st == "price_missing"
            if not need_fill:
                continue

            candidates: List[str] = []
            if item.get("concepto"):
                candidates.append(self._normalize_econ_label(item["concepto"]))
            cid = item.get("concepto_id")
            if cid is not None and str(cid) in req_by_id:
                r0 = req_by_id[str(cid)]
                lbl = r0.get("label") or r0.get("descripcion") or r0.get("titulo") or r0.get("texto")
                if lbl:
                    candidates.append(self._normalize_econ_label(lbl))

            hit: Optional[Dict] = None
            for c in candidates:
                if c and c in by_norm:
                    hit = by_norm[c]
                    break
            if hit is None and candidates:
                n0 = candidates[0]
                if len(n0) >= 10:
                    for tnorm, row in by_norm.items():
                        if len(tnorm) >= 10 and (n0 in tnorm or tnorm in n0):
                            hit = row
                            break
            fuzzy_sc = 0.0
            if hit is None and candidates:
                hit, fuzzy_sc = self._fuzzy_best_tabular_row(candidates, by_norm)
            if not hit:
                continue

            qty = item.get("cantidad")
            try:
                qty_f = float(qty) if qty is not None and qty != "" else 1.0
            except (TypeError, ValueError):
                qty_f = 1.0
            price = float(hit["precio_unitario"])
            item["precio_unitario"] = price
            item["subtotal"] = qty_f * price
            item["status"] = "matched"
            if fuzzy_sc > 0:
                item["price_source"] = "session_line_items_fuzzy"
                item["tabular_match_score"] = round(fuzzy_sc, 3)
            else:
                item["price_source"] = "session_line_items"
        return proposal_draft

    async def _calculate_proposal(
        self,
        requirements: List[Dict],
        catalog: List[Dict],
        correlation_id: str = "",
        *,
        bases_economic_context: str = "",
    ) -> Dict:
        """Usa el LLM para mapear requerimientos a precios; incorpora marco económico del Analista de bases."""
        ctx_block = (bases_economic_context or "").strip()
        if not ctx_block:
            ctx_block = "(Sin contexto adicional del analista de bases.)"
        prompt = f"""
REQUERIMIENTOS: {json.dumps(requirements)}
CATALOGO: {json.dumps(catalog)}

CONTEXTO DEL ANALISTA DE BASES (usar para coherencia de cantidades, plazos y alertas; no inventar precios aquí):
{ctx_block}

Prioriza precios así: 1) ítems con "is_session_tabular": true (Excel de sesión), 2) catálogo de empresa sin flags,
3) "is_alcance_operativo": true como guía de descripción y cantidad si aplica al requerimiento,
4) "is_rag_reference" solo como apoyo textual.

Si el contexto cita importes/meses/plazos o alerta tabular, refleja advertencias en "alertas".
Genera un JSON ESTRICTO con la siguiente estructura:
{{
    "items": [
        {{
            "concepto": "nombre del requerimiento",
            "concepto_id": "id del requerimiento original",
            "cantidad": 1,
            "precio_unitario": 0.0,
            "subtotal": 0.0,
            "status": "matched" // (usa price_missing si no hallas precio exacto)
        }}
    ],
    "alertas": ["alerta 1"] // (opcional: alertas sobre monedas o condiciones deducidas)
}}
"""
        resp = await self.llm.generate(
            prompt=prompt, 
            system_prompt="Analista Financiero estricto. Responde única y exclusivamente con un JSON válido.", 
            format="json",
            correlation_id=correlation_id
        )
        if not resp.success:
            return {"status": "error", "message": resp.error}
        return self._robust_json_parse(resp.response or "{}")

    async def _get_company_catalog(self, company_id: str) -> List[Dict]:
        if not company_id: return []
        try:
            company = await self.context_manager.memory.get_company(company_id)
            return company.get("catalog", []) if company else []
        except Exception as e:
            logger.error(f"[EconomicAgent] Error obteniendo catalogo: {e}")
            return []

    def _robust_json_parse(self, text: str) -> Any:
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            # El prompt estricto pide un objeto JSON {...}
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
            return {}
        except Exception as e:
            logger.error(f"[EconomicAgent] Parser error: {e}")
            return {}

    async def _save_pending_questions(self, session_id: str, missing_fields: List[Dict]):
        """Persiste preguntas para el chatbot (Hito 6)."""
        try:
            session_state = await self.context_manager.memory.get_session(session_id)
            if session_state is None:
                session_state = {}
            # Merge con preguntas existentes si las hubiera
            existing = session_state.get("pending_questions", [])
            existing_fields = {q["field"] for q in existing}
            new_questions = [q for q in missing_fields if q["field"] not in existing_fields]

            session_state["pending_questions"] = existing + new_questions
            if "current_question_index" not in session_state:
                session_state["current_question_index"] = 0

            await self.context_manager.memory.save_session(session_id, session_state)
        except Exception as e:
            print(f"[EconomicAgent] ⚠️ Error guardando preguntas econ: {e}")
