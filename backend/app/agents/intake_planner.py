from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.agents.base_agent import BaseAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _sim_key(field_target: str, question: str) -> str:
    base = _norm(field_target) or _norm(question)
    base = re.sub(r"[^a-z0-9_ ]", "", base)
    return base[:180]


# ---------------------------------------------------------------------------
# Mapa global de equivalencias: field_target del LLM → clave del master_profile
# Resuelve el desajuste entre namespaces dinámicos y claves planas de la BD.
# ---------------------------------------------------------------------------
FIELD_MAPPING: Dict[str, str] = {
    # Solvencia Legal → Claves del master_profile
    "solvencia_legal.comprobante_de_domicilio_fiscal": "domicilio_fiscal",
    "solvencia_legal.comprobante_de_domicilio": "domicilio_fiscal",
    "solvencia_legal.domicilio_fiscal": "domicilio_fiscal",
    "solvencia_legal.domicilio": "domicilio_fiscal",
    "solvencia_legal.rfc": "rfc",
    "solvencia_legal.registro_federal_de_contribuyentes": "rfc",
    "solvencia_legal.acta_constitutiva": "razon_social",
    "solvencia_legal.razon_social": "razon_social",
    "solvencia_legal.representante_legal": "representante_legal",
    "solvencia_legal.identificacion_oficial_del_representante": "representante_legal",
    "solvencia_legal.poder_notarial": "representante_legal",
    "solvencia_legal.registro_patronal": "registro_patronal",
    "solvencia_legal.imss": "registro_patronal",
    "solvencia_legal.numero_de_empleados": "numero_empleados",
    "solvencia_legal.plantilla_de_personal": "numero_empleados",
    # Solvencia Económica → Claves del master_profile
    "solvencia_economica.capital_contable_minimo": "capital_contable",
    "solvencia_economica.capital_contable": "capital_contable",
    "solvencia_economica.estados_financieros": "capital_contable",
    "solvencia_economica.anos_de_experiencia": "anos_experiencia",
    "solvencia_economica.anos_experiencia": "anos_experiencia",
    # Condiciones Contractuales → Claves del master_profile
    "condiciones_contractuales.anos_experiencia": "anos_experiencia",
    "condiciones_contractuales.experiencia_minima": "anos_experiencia",
    "condiciones_contractuales.contratos_previos": "contratos_previos",
    "condiciones_contractuales.contratos_similares": "contratos_previos",
}

def _priority_weight(p: str) -> int:
    order = {"BLOQUEANTE": 4, "CRITICO": 3, "IMPORTANTE": 2, "COMPLEMENTARIO": 1}
    return order.get(str(p or "").upper(), 1)


class IntakePlannerAgent(BaseAgent):
    """
    Planner proactivo de intake.
    Consolida hallazgos multiagente en una lista priorizada de preguntas.
    """

    def __init__(self, context_manager: MCPContextManager):
        super().__init__(
            agent_id="intake_planner_001",
            name="Intake Planner Agent",
            description="Consolida y prioriza preguntas de intake por licitación.",
            context_manager=context_manager,
        )

    def _extract_stage_data(self, results: Dict[str, Any], stage: str) -> Dict[str, Any]:
        raw = results.get(stage) if isinstance(results, dict) else None
        if not isinstance(raw, dict):
            return {}
        data = raw.get("data")
        if isinstance(data, dict):
            return data
        return raw

    def _questions_from_go_no_go(self, gng: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        brechas = gng.get("brechas") if isinstance(gng.get("brechas"), list) else []
        for idx, b in enumerate(brechas, start=1):
            desc = str(b.get("descripcion") or b.get("brecha") or b.get("mensaje") or "").strip()
            if not desc or desc.isdigit():
                desc = f"Detalle de viabilidad {idx}"
            is_knockout = bool(b.get("is_knockout") or b.get("knockout"))
            pr = "BLOQUEANTE" if is_knockout else "CRITICO"
            out.append(
                {
                    "question_id": f"INTAKE-B-GNG-{idx:03d}",
                    "question_type": "B",
                    "priority": pr,
                    "blocking": is_knockout,
                    "question": f"He notado un detalle importante en la viabilidad: **{desc}**. ¿Cómo tienes pensado resolver este punto para asegurar que podamos participar?",
                    "field_target": str(b.get("field") or b.get("id") or f"gng_{idx}"),
                    "required_evidence": "evidencia_subsanacion",
                    "provenance_ui": {"source": "go_no_go", "confidence": 0.9, "reason": "brecha_detectada"},
                }
            )
        return out

    def _questions_from_analysis(
        self,
        analysis: Dict[str, Any],
        master_profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Genera preguntas de intake desde los resultados del análisis.

        Filtra preguntas cuyos datos ya están cubiertos en el master_profile
        para evitar pedir al usuario datos que la empresa ya tiene registrados.
        """
        out: List[Dict[str, Any]] = []
        profile = master_profile or {}

        def _profile_covers(field_target: str) -> bool:
            """True si el master_profile ya tiene un valor para este campo."""
            if not profile:
                return False
            # Mapeo de field_target a campos del master_profile
            _field_map = {
                "domicilio": "domicilio_fiscal",
                "fiscal": "domicilio_fiscal",
                "rfc": "rfc",
                "razon_social": "razon_social",
                "representante": "representante_legal",
                "capital": "capital_contable",
                "registro_patronal": "registro_patronal",
                "imss": "registro_patronal",
            }
            ft_lower = field_target.lower()
            for keyword, profile_key in _field_map.items():
                if keyword in ft_lower:
                    val = profile.get(profile_key)
                    if val and str(val).strip():
                        return True
            return False

        legal = analysis.get("requisitos_solvencia_legal")
        if isinstance(legal, list):
            for idx, it in enumerate(legal, start=1):
                titulo = str(it.get('titulo') or f'Requisito legal {idx}')
                field_target = f"solvencia_legal.{_norm(titulo).replace(' ', '_')}"
                # BISTURÍ EQUILIBRADO: Excluir requerimientos físicos del chat (van a la UI)
                # Basado en la taxonomía universal LEG_ / FIS_
                is_presencial = titulo.upper().startswith(("LEG_", "FIS_")) or field_target.startswith(("solvencia_legal.leg_", "solvencia_legal.fis_"))
                if is_presencial or _profile_covers(field_target):
                    continue
                out.append(
                    {
                        "question_id": f"INTAKE-B-LEG-{idx:03d}",
                        "question_type": "B",
                        "priority": "CRITICO",
                        "blocking": False,
                        "label": titulo,
                        "question": f"Para la solvencia legal, necesito confirmar si ya tienes listo tu **{titulo}** y si está vigente.",
                        "field_target": field_target,
                        "required_evidence": "documento_legal_vigente",
                        "provenance_ui": {"source": "analysis", "confidence": float(it.get("confidence", 0.75) or 0.75), "reason": "solvencia_legal"},
                    }
                )
        econ = analysis.get("requisitos_solvencia_economica")
        if isinstance(econ, list):
            for idx, it in enumerate(econ, start=1):
                crit = str(it.get("criticidad") or "critico").upper()
                pr = "BLOQUEANTE" if crit == "BLOQUEANTE" else "CRITICO"
                titulo = str(it.get('titulo') or f'Requisito económico {idx}')
                field_target = f"solvencia_economica.{_norm(titulo).replace(' ', '_')}"
                is_presencial = titulo.upper().startswith(("LEG_", "FIS_")) or field_target.startswith(("solvencia_economica.leg_", "solvencia_economica.fis_"))
                if is_presencial or _profile_covers(field_target):
                    continue
                out.append(
                    {
                        "question_id": f"INTAKE-B-ECO-{idx:03d}",
                        "question_type": "B",
                        "priority": pr,
                        "blocking": pr == "BLOQUEANTE",
                        "label": titulo,
                        "question": f"Respecto a la solvencia económica, por favor confírmame si tienes la capacidad para cubrir el requisito de **{titulo}**.",
                        "field_target": field_target,
                        "required_evidence": "documento_solvencia_economica",
                        "provenance_ui": {"source": "analysis", "confidence": float(it.get("confidence", 0.78) or 0.78), "reason": "solvencia_economica"},
                    }
                )
        cond = analysis.get("condiciones_contractuales")
        if isinstance(cond, dict):
            _cond_labels = {
                "penalizaciones": "Penalizaciones contractuales",
                "condiciones_pago": "Condiciones de pago",
                "garantia_vicios_ocultos": "Garantía por vicios ocultos",
            }
            for key in ("penalizaciones", "condiciones_pago", "garantia_vicios_ocultos"):
                v = cond.get(key)
                if v:
                    label = _cond_labels.get(key, key)
                    # Incluir el contenido real de la cláusula en la pregunta
                    # para que el asistente pueda explicársela al usuario en contexto.
                    clausula_texto = str(v).strip() if isinstance(v, str) else ""
                    if clausula_texto:
                        question_text = (
                            f"He notado una condición crítica sobre **{label.lower()}** que dice literalmente: \"{clausula_texto}\". "
                            f"Si estás de acuerdo, podré redactar e integrar el documento de aceptación que pide la licitación. "
                            f"¿Confirmas que la aceptas?"
                        )
                    else:
                        question_text = (
                            f"He detectado una condición sobre **{label.lower()}**. "
                            f"Para poder generar el manifiesto correspondiente, necesito saber si estás de acuerdo con este punto. "
                            f"¿Aceptas esta condición?"
                        )
                    out.append(
                        {
                            "question_id": f"INTAKE-B-CON-{key}",
                            "question_type": "B",
                            "priority": "IMPORTANTE",
                            "blocking": False,
                            "label": label,
                            "question": question_text,
                            "field_target": f"condiciones_contractuales.{key}",
                            "required_evidence": "aceptacion_condicion_contractual",
                            "provenance_ui": {
                                "source": "analysis",
                                "confidence": 0.75,
                                "reason": "condicion_contractual",
                                "clausula_texto": clausula_texto,
                            },
                        }
                    )

        # NUEVO: Integrar Checklist de Participación (Evidencia Directa)
        checklist = analysis.get("requisitos_participacion")
        if isinstance(checklist, list):
            for idx, it in enumerate(checklist, start=1):
                txt = str(it.get("texto_literal") or "").strip()
                if not txt: continue
                # Propagar metadatos de evidencia
                pg = it.get("pagina") or ""
                src = it.get("archivo_fuente") or ""
                snip = it.get("evidence_snippet") or txt
                
                out.append({
                    "question_id": f"INTAKE-CHECK-{idx:03d}",
                    "question_type": "B",
                    "priority": "CRITICO",
                    "blocking": False,
                    "label": f"Requisito: {txt[:40]}...",
                    "question": f"He encontrado este requisito en las bases: \"{txt[:200]}\". ¿Me confirmas que lo cumples y que integrarás el documento correspondiente?",
                    "field_target": f"participacion.check_{idx}",
                    "pagina": str(pg),
                    "archivo_fuente": str(src),
                    "evidence_snippet": str(snip),
                    "provenance_ui": {"source": "analysis", "confidence": 0.85, "reason": "checklist_participacion"}
                })

        # NUEVO: Integrar Gap Analysis (Análisis Estratégico)
        audit = analysis.get("audit_report") or {}
        gaps = audit.get("gap_analysis") if isinstance(audit, dict) else []
        if isinstance(gaps, list):
            for idx, g in enumerate(gaps, start=1):
                req = str(g.get("requisito") or "").strip()
                if not req or req.isdigit():
                    req = f"Requisito estratégico {idx}"
                # Solo procesamos Gaps reales (Faltantes o Vencidos)
                if str(g.get("estado_empresa")).upper() not in ["FALTANTE", "VENCIDO"]:
                    continue
                
                pg = g.get("pagina") or ""
                src = g.get("archivo_fuente") or ""
                snip = g.get("evidence_snippet") or req

                out.append({
                    "question_id": f"INTAKE-GAP-{idx:03d}",
                    "question_type": "B",
                    "priority": str(g.get("gravedad", "CRITICO")).upper(),
                    "blocking": str(g.get("gravedad")).upper() == "ALTA",
                    "label": f"Brecha: {req[:40]}...",
                    "question": f"Hay un punto estratégico que nos falta: **{req}**. {g.get('accion_requerida', '')} ¿Podemos avanzar con esto?",
                    "field_target": f"gap.{idx}",
                    "pagina": str(pg),
                    "archivo_fuente": str(src),
                    "evidence_snippet": str(snip),
                    "provenance_ui": {"source": "analysis", "confidence": 0.9, "reason": "gap_analysis"}
                })
        return out

    def _questions_from_compliance(self, compliance_list: Dict[str, Any], company_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extrae preguntas proactivas de la Lista Maestra de Compliance.
        Filtra requerimientos físicos y redundantes.
        """
        out: List[Dict[str, Any]] = []
        if not compliance_list or not isinstance(compliance_list, dict):
            return out

        for cat in ["administrativo", "tecnico", "formatos"]:
            items = compliance_list.get(cat) or []
            # Log corregido: items ya existe aquí
            logger.info(f"[FORENSE] Filtrando compliance '{cat}'. Items: {len(items)}")

            for idx, it in enumerate(items):
                if not it or not isinstance(it, dict):
                    continue

                tipo = str(it.get("tipo_accion") or "").lower()
                
                # === REFACTORIZACIÓN EQUILIBRADA ===
                # 1. Los documentos físicos NUNCA van al chat
                if tipo == "presentar_fisico":
                    continue

                # REGLA B: Los documentos para 'generar' van al checklist de la UI, NO al chat.
                # El chatbot solo debe preguntar por DATOS PUROS faltantes.
                if tipo == "generar":
                    continue
                
                # REGLA C: Solo permitimos GAPs de datos reales (requiere_datos_licitante)
                if tipo != "requiere_datos_licitante":
                    continue
                
                nombre = str(it.get("nombre") or "").strip()
                if not nombre or nombre.isdigit():
                    nombre = f"{cat.capitalize()} {idx}"
                pg = it.get("page") or ""
                src = it.get("archivo_fuente") or ""
                snip = it.get("snippet") or it.get("descripcion") or ""

                out.append({
                    "question_id": f"INTAKE-COMP-{cat[:3].upper()}-{idx:03d}",
                    "question_type": "B",
                    "priority": "CRITICO" if cat != "formatos" else "IMPORTANTE",
                    "blocking": cat == "administrativo",
                    "label": nombre,
                    "question": f"Respecto a la **{nombre}**, ¿ya cuentas con ella o prefieres que te ayude a proyectar el documento para la propuesta?",
                    "field_target": str(it.get("field_target") or f"compliance.{cat}.{idx}"),
                    "pagina": str(pg),
                    "archivo_fuente": str(src),
                    "evidence_snippet": str(snip),
                    "provenance_ui": {
                        "source": "compliance_audit",
                        "confidence": 0.95,
                        "reason": f"master_list_{cat}"
                    }
                })
        return out

    def _questions_from_pending(self, pending: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for idx, p in enumerate(pending or [], start=1):
            q = str(p.get("question") or p.get("label") or "").strip()
            if not q:
                continue
            out.append(
                {
                    "question_id": f"INTAKE-A-{idx:03d}",
                    "question_type": "A",
                    "priority": "COMPLEMENTARIO",
                    "blocking": bool(p.get("type") in {"profile_field_blocking", "economic_validation_blocking"}),
                    "question": q,
                    "field_target": str(p.get("field") or f"profile_field_{idx}"),
                    "required_evidence": str(p.get("document_hint") or "dato_perfil"),
                    "provenance_ui": {"source": "pending_questions", "confidence": 0.7, "reason": "perfil_incompleto"},
                }
            )
        return out

    def _questions_from_quality_hints(self, session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        q_hint = session_state.get("last_document_quality_waiting_hints")
        f_hint = session_state.get("last_document_fill_quality_waiting_hints")

        if isinstance(q_hint, dict):
            reason = str(q_hint.get("reason") or "").strip()
            out.append(
                {
                    "question_id": "INTAKE-Q-CLASS-001",
                    "question_type": "Q",
                    "priority": "BLOQUEANTE",
                    "blocking": True,
                    "label": "Clasificación de documentos",
                    "question": (
                        "Detecté algunos documentos con clasificación ambigua en las bases. "
                        "El sistema continuará con la mejor clasificación disponible. "
                        "Si notas algún documento mal clasificado en el expediente final, puedes indicármelo."
                    ),
                    "field_target": "quality.classification.review",
                    "required_evidence": "confirmacion_clasificacion_documental",
                    "provenance_ui": {
                        "source": "document_quality_gate",
                        "confidence": 0.9,
                        "reason": reason or "clasificacion_ambigua",
                    },
                }
            )

        if isinstance(f_hint, dict):
            blocking = int(f_hint.get("blocking_count", 0) or 0)
            warnings = int(f_hint.get("warning_count", 0) or 0)
            if blocking > 0 or warnings > 0:
                pr = "CRITICO" if blocking <= 0 else "BLOQUEANTE"
                out.append(
                    {
                        "question_id": "INTAKE-Q-FILL-001",
                        "question_type": "Q",
                        "priority": pr,
                        "blocking": blocking > 0,
                        "label": "Validación de datos de llenado",
                        "question": (
                            "Antes de generar, necesito confirmar datos clave de llenado en los documentos "
                            "(campos obligatorios y consistencia). ¿Me ayudas a validar esos datos críticos?"
                        ),
                        "field_target": "quality.fill.review",
                        "required_evidence": "confirmacion_datos_criticos_documentales",
                        "provenance_ui": {
                            "source": "document_fill_quality_gate",
                            "confidence": 0.85,
                            "reason": f"blocking={blocking},warnings={warnings}",
                        },
                    }
                )
        return out

    def _inventory_summary_from_inventory(self, session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Genera el resumen de inventario documental por categoría.

        A diferencia del método anterior (_questions_from_inventory), este método
        retorna los datos de inventario en un campo separado `inventory_summary`
        que NO se incluye en `questions`. Esto evita que los inventarios lleguen
        al flujo conversacional del ChatbotRAGAgent.

        El `table_data` con la tabla Markdown de documentos se preserva para
        que la UI pueda renderizarlo en el panel de estado de intake.
        """
        out: List[Dict[str, Any]] = []
        inventory_raw = session_state.get("document_inventory")
        if not isinstance(inventory_raw, dict):
            return out

        items = inventory_raw.get("items", [])
        # Normalización robusta para evitar el bug del Enum (pending vs InventoryItemStatus.PENDING)
        pending_items = [
            it for it in items
            if str(it.get("status", "")).lower().endswith("pending")
        ]

        if not pending_items:
            return out

        # Agrupar por categoría
        by_cat: Dict[str, List[Dict[str, Any]]] = {}
        for it in pending_items:
            cat = it.get("category", "legal_administrative")
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(it)

        cat_names = {
            "legal_administrative": "Administrativa/Legal",
            "technical": "Técnica",
            "economic": "Económica"
        }

        for cat, group in by_cat.items():
            cat_label = cat_names.get(cat, cat)
            count = len(group)

            # Construir la tabla Markdown para la UI
            table_lines = ["| Anexo | Descripción | Pág |", "| :--- | :--- | :--- |"]
            for it in group[:15]:
                anchors = it.get("anchors", [])
                page = anchors[0].get("page_index") if anchors else "N/A"
                table_lines.append(
                    f"| {it.get('display_name', '')} | {it.get('description', '')} | {page} |"
                )

            table_md = "\n".join(table_lines)

            out.append({
                "category": cat,
                "category_label": cat_label,
                "count": count,
                "priority": "BLOQUEANTE" if cat == "legal_administrative" else "CRITICO",
                "blocking": cat == "legal_administrative",
                "field_target": f"inventory.{cat}.completion",
                "table_data": table_md,
                "provenance_ui": {
                    "source": "document_inventory",
                    "confidence": 0.9,
                    "reason": f"inventory_pending_count={count}"
                }
            })

        return out

    def _dedupe(self, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        for q in questions:
            key = _sim_key(str(q.get("field_target", "")), str(q.get("question", "")))
            if key not in seen:
                seen[key] = q
                continue
            prev = seen[key]
            if _priority_weight(str(q.get("priority"))) > _priority_weight(str(prev.get("priority"))):
                seen[key] = q
        return list(seen.values())

    def _sort_questions(self, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            questions,
            key=lambda x: (
                -_priority_weight(str(x.get("priority"))),
                str(x.get("question_id", "")),
            ),
        )

    def _summary(
        self,
        questions: List[Dict[str, Any]],
        inventory_summary: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, int]:
        counts = {"BLOQUEANTE": 0, "CRITICO": 0, "IMPORTANTE": 0, "COMPLEMENTARIO": 0}
        for q in questions:
            p = str(q.get("priority") or "").upper()
            if p in counts:
                counts[p] += 1
        inventory_pending_count = sum(
            int(item.get("count") or 0) for item in (inventory_summary or [])
        )
        return {
            "blocking_count": counts["BLOQUEANTE"],
            "critical_count": counts["CRITICO"],
            "important_count": counts["IMPORTANTE"],
            "complementary_count": counts["COMPLEMENTARIO"],
            "inventory_pending_count": inventory_pending_count,
        }

    async def process(self, agent_input: AgentInput) -> AgentOutput:
        session_id = agent_input.session_id
        correlation_id = agent_input.correlation_id or "no-id"
        company_data = agent_input.company_data or {}
        results = company_data.get("results") if isinstance(company_data.get("results"), dict) else {}
        session_state = company_data.get("session_state") if isinstance(company_data.get("session_state"), dict) else {}
        master_profile = company_data.get("master_profile") if isinstance(company_data.get("master_profile"), dict) else {}

        analysis = self._extract_stage_data(results, "analysis")
        gng = self._extract_stage_data(results, "go_no_go")
        pending = list(session_state.get("pending_questions") or [])

        questions = []
        # Prioridad de incertidumbre: primero resolver clasificación documental, después llenado.
        questions.extend(self._questions_from_quality_hints(session_state))
        # NOTA: _inventory_summary_from_inventory ya NO agrega a questions —
        # el inventario va a un campo separado para no interrumpir el flujo conversacional.
        questions.extend(self._questions_from_go_no_go(gng))
        
        # NUEVO: Consumir la Lista Maestra de Compliance (Auditoría Forense)
        master_compliance = company_data.get("compliance_master_list") or results.get("compliance", {}).get("data") or {}
        questions.extend(self._questions_from_compliance(master_compliance, company_profile=master_profile))

        questions.extend(self._questions_from_analysis(analysis, master_profile=master_profile))
        questions.extend(self._questions_from_pending(pending))

        # --- FILTRADO POR CAMPOS YA LLENOS EN EL MASTER_PROFILE ---
        # Identifica qué campos reales del master_profile ya tienen información en el sistema.
        campos_perfil_llenos = {
            key for key, val in master_profile.items()
            if val and str(val).strip().lower() not in ("", "null", "none", "[]", "{}")
        }
        logger_fields = list(campos_perfil_llenos)[:15]
        from app.core.logging_config import get_logger as _get_logger
        _log = _get_logger(__name__)
        _log.info(
            "intake_planner_campos_llenos",
            session_id=session_id,
            campos_count=len(campos_perfil_llenos),
            campos_sample=logger_fields,
        )
        print(f"[DEBUG INTAKE] Campos detectados como YA LLENOS en la BD: {campos_perfil_llenos}")

        # Filtra preguntas cuyos datos ya existen y asigna el 'field' correcto para el chatbot.
        preguntas_validadas = []
        for q in questions:
            target = q.get("field_target") or ""
            field_mapped = FIELD_MAPPING.get(target)

            if field_mapped:
                # Si el dato ya existe en el sistema, omitir la pregunta
                if field_mapped in campos_perfil_llenos:
                    continue
                # Si no existe, inyectar la clave limpia para que el chatbot sepa dónde guardar
                q["field"] = field_mapped
            else:
                # Fallback robustecido: limpiar prefijos de namespace para comparar con master_profile
                # Convierte 'solvencia_legal.comprobante_de_domicilio_fiscal' → 'comprobante_de_domicilio_fiscal'
                target_clean = target
                for prefix in ("solvencia_legal.", "solvencia_economica.", "condiciones_contractuales."):
                    target_clean = target_clean.replace(prefix, "")

                if target_clean and target_clean in campos_perfil_llenos:
                    continue

                # Match por subcadenas clave para casos dinámicos del LLM
                if any(k in target_clean for k in ("domicilio", "fiscal")) and "domicilio_fiscal" in campos_perfil_llenos:
                    continue
                if "rfc" in target_clean and "rfc" in campos_perfil_llenos:
                    continue
                if any(k in target_clean for k in ("representante", "apoderado")) and "representante_legal" in campos_perfil_llenos:
                    continue
                if any(k in target_clean for k in ("capital", "patrimonio")) and "capital_contable" in campos_perfil_llenos:
                    continue
                if any(k in target_clean for k in ("razon_social", "razon social", "empresa")) and "razon_social" in campos_perfil_llenos:
                    continue

                if target_clean:
                    q["field"] = target_clean

            preguntas_validadas.append(q)

        questions = self._sort_questions(self._dedupe(preguntas_validadas))
        # --- FIN DE FILTRADO ---

        # --- BIFURCACIÓN ESTRATÉGICA (Checklist Corporativo) ---
        # Si el usuario ya firmó el Go/No-Go, silenciamos las alertas legales/administrativas
        # del Chatbot y las desviamos a un checklist estático.
        go_no_go_override = session_state.get("go_no_go_override") or {}
        already_authorized = go_no_go_override.get("authorized_by") == "user"
        
        checklist_corporativo = []
        if already_authorized:
            kept_questions = []
            for q in questions:
                target = str(q.get("field_target") or "").lower()
                
                # Identificamos documentos corporativos/legales para NO molestar al usuario en el chat
                is_legal = (
                    "legal" in target or "administrativ" in target or "rfc" in target or
                    "domicilio" in target or "acta" in target or "poder" in target or
                    "representante" in target or "imss" in target or "sat" in target or
                    "compliance.administrativo" in target
                )
                
                if is_legal:
                    checklist_corporativo.append(q)
                else:
                    kept_questions.append(q)
            questions = kept_questions
        # --- FIN DE BIFURCACIÓN ---

        # Inventario documental en campo separado (no conversacional)
        inventory_summary = self._inventory_summary_from_inventory(session_state)

        data = {
            "plan_version": "1.2.0",
            "summary": self._summary(questions, inventory_summary),
            "questions": questions,
            "inventory_summary": inventory_summary,
            "checklist_corporativo": checklist_corporativo,
        }
        return AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id=self.agent_id,
            session_id=session_id,
            data=data,
            correlation_id=correlation_id,
        )
