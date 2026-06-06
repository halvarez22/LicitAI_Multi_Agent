"""
Descubrimiento determinista de temas para junta a partir del corpus de bases (universal).

No usa LLM: reglas sobre texto indexado + patrones normativos recurrentes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.contracts.junta_aclaraciones_questions import (
    JuntaQuestionPrioridad,
    JuntaQuestionSource,
    JuntaQuestionTipo,
)
from app.services.junta_bases_corpus import (
    BasesCorpus,
    find_cross_jurisdiction_template_hints,
    find_experience_year_conflict,
    find_placeholder_brackets,
    find_unresolved_attachment_reference,
)


def discover_thematic_questions(corpus: BasesCorpus) -> List[Dict[str, Any]]:
    """
    Devuelve dicts con pregunta, motivo, source_ref, provenance_ui para integrar en junta.
    """
    if not corpus.segments:
        return []

    out: List[Dict[str, Any]] = []

    conflict = find_experience_year_conflict(corpus)
    if conflict:
        ta, tb, years = conflict
        out.append(
            {
                "pregunta": (
                    f"Con respecto a los requisitos de experiencia en las bases, donde en un apartado "
                    f"se menciona «{ta[:120]}» y en otro «{tb[:120]}», "
                    f"¿cuál es el periodo mínimo de años de experiencia acreditable ({years}) "
                    f"que aplicará la convocante al evaluar las proposiciones?"
                ),
                "motivo": "Conflicto de plazos de experiencia detectado en el texto de bases.",
                "source_ref": "thematic_experience_years_conflict",
                "tipo": JuntaQuestionTipo.ADMINISTRATIVA,
                "prioridad": JuntaQuestionPrioridad.ALTA,
                "provenance_ui": {
                    "source": "thematic_bases",
                    "pattern": "experience_years_conflict",
                    "citation_quality": "solo_documento",
                },
            }
        )

    adj = find_unresolved_attachment_reference(corpus)
    if adj:
        out.append(
            {
                "pregunta": (
                    "Con respecto al apartado que indica que un proyecto, anexo o documento técnico "
                    "«se adjunta» a las bases, sin que conste completo en el expediente de consulta, "
                    "¿podrá la convocante publicar o entregar en junta el documento referido "
                    "(planos, especificaciones, presupuesto base o programa), indicando plazo y medio?"
                ),
                "motivo": "Referencia a documento adjunto no materializado en el paquete indexado.",
                "source_ref": "thematic_missing_attached_project",
                "tipo": JuntaQuestionTipo.TECNICA,
                "prioridad": JuntaQuestionPrioridad.ALTA,
                "provenance_ui": {
                    "source": "thematic_bases",
                    "pattern": "unresolved_se_adjunta",
                    "citation_quality": "solo_documento",
                },
            }
        )

    placeholders = find_placeholder_brackets(corpus)
    if placeholders:
        sample = ", ".join(placeholders[:3])
        out.append(
            {
                "pregunta": (
                    f"Con respecto a los formatos y anexos de las bases que contienen campos sin definir "
                    f"(por ejemplo: {sample}), ¿podrá la convocante publicar versiones editables definitivas "
                    f"o indicar los valores que deben sustituir dichos marcadores en la proposición?"
                ),
                "motivo": "Placeholders detectados en plantillas integradas en las bases.",
                "source_ref": "thematic_format_placeholders",
                "tipo": JuntaQuestionTipo.ADMINISTRATIVA,
                "prioridad": JuntaQuestionPrioridad.MEDIA,
                "provenance_ui": {
                    "source": "thematic_bases",
                    "pattern": "format_placeholders",
                    "citation_quality": "solo_documento",
                },
            }
        )

    cross_hints = find_cross_jurisdiction_template_hints(corpus)
    if cross_hints:
        codes = ", ".join(
            dict.fromkeys(str(h.get("template_code") or "") for h in cross_hints if h.get("template_code"))
        )
        sample = next((h for h in cross_hints if h.get("foreign_city")), cross_hints[0])
        foreign = sample.get("foreign_city") or ""
        fstate = sample.get("foreign_state") or ""
        loc = f"{foreign}, {fstate}".strip(", ") if foreign or fstate else fstate
        pmuni = sample.get("primary_municipality") or "la convocación"
        out.append(
            {
                "pregunta": (
                    f"Con respecto a los formatos integrados en las bases "
                    f"({codes or 'plantillas detectadas'}), cuyo pie o encabezado "
                    f"refiere a «{loc}» mientras la convocatoria es del municipio de "
                    f"«{pmuni}», ¿se confirma la versión oficial aplicable "
                    f"a esta licitación o se publicará la plantilla corregida?"
                ),
                "motivo": "Plantilla(s) con referencia geográfica distinta a la entidad convocante.",
                "source_ref": "thematic_cross_jurisdiction_template",
                "tipo": JuntaQuestionTipo.ADMINISTRATIVA,
                "prioridad": JuntaQuestionPrioridad.ALTA,
                "provenance_ui": {
                    "source": "thematic_bases",
                    "pattern": "cross_jurisdiction_template",
                    "template_codes": [h.get("template_code") for h in cross_hints],
                    "citation_quality": "solo_documento",
                },
            }
        )

    if _corpus_mentions_certification_cluster(corpus) and not any(
        q.get("source_ref") == "thematic_certification_scope" for q in out
    ):
        out.append(
            {
                "pregunta": (
                    "Con respecto a los requisitos de certificación, pruebas de laboratorio acreditado "
                    "y constancias (NOM, eficiencia energética u otras citadas en bases), "
                    "¿deben acreditarse por cada modelo o lote ofertado, por partida, "
                    "o basta una constancia por fabricante para todo el suministro?"
                ),
                "motivo": "Cluster de certificaciones técnicas en bases sin alcance explícito por unidad.",
                "source_ref": "thematic_certification_scope",
                "tipo": JuntaQuestionTipo.TECNICA,
                "prioridad": JuntaQuestionPrioridad.ALTA,
                "provenance_ui": {
                    "source": "thematic_bases",
                    "pattern": "certification_cluster",
                    "citation_quality": "solo_documento",
                },
            }
        )

    return out


def _corpus_mentions_certification_cluster(corpus: BasesCorpus) -> bool:
    blob = corpus.combined_norm
    has_norm = "nom-" in blob or "nmx-" in blob
    has_lab = "laboratorio" in blob and "acredit" in blob
    has_energy = "fide" in blob or "paese" in blob or "ener" in blob
    return has_norm and (has_lab or has_energy)
