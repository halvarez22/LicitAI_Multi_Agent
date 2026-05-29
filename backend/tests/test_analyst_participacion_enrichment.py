"""
Tests de enriquecimiento determinista de requisitos_participacion (Analista).
"""
from app.services.analyst_participacion_enrichment import (
    enrich_analyst_participacion_output,
    extract_requisitos_from_rag_context,
    is_placeholder_analyst_text,
    merge_requisitos_participacion,
    sanitize_audit_report,
)

_SYNTHETIC_RAG = """
--- PÁGINA 18 (bases_convocatoria.pdf) ---
4. Requisitos para participar
a) Presentar declaración de integridad conforme al reglamento aplicable.
b) Acreditar personalidad jurídica y capacidad jurídica del licitante.
c) Contar con al menos 12 años de experiencia en servicios similares al objeto del contrato.
d) Exhibir RFC vigente y domicilio fiscal comprobable ante el SAT.
"""


def test_is_placeholder_rejects_punto_x_and_ellipsis():
    assert is_placeholder_analyst_text("Pregunta técnica para clarificar el punto X...")
    assert is_placeholder_analyst_text("...")
    assert not is_placeholder_analyst_text(
        "Contar con al menos 12 años de experiencia en servicios similares al objeto del contrato."
    )


def test_extract_requisitos_from_rag_context_incisos_y_pagina():
    items = extract_requisitos_from_rag_context(_SYNTHETIC_RAG)
    assert len(items) >= 3
    by_inc = {i.get("inciso"): i for i in items if i.get("inciso")}
    assert by_inc["c"]["pagina"] == "18"
    assert by_inc["c"]["archivo_fuente"] == "bases_convocatoria.pdf"
    assert "12 años" in by_inc["c"]["texto_literal"]


def test_merge_discards_placeholder_llm_and_keeps_rag():
    llm = [
        {
            "inciso": "a",
            "texto_literal": "...",
            "pagina": "...",
            "archivo_fuente": "",
        },
        {
            "inciso": "c",
            "texto_literal": "Experiencia mínima requerida",
            "pagina": "",
            "archivo_fuente": "",
        },
    ]
    rag = extract_requisitos_from_rag_context(_SYNTHETIC_RAG)
    merged = merge_requisitos_participacion(llm, rag_candidates=rag)
    texts = " ".join(r["texto_literal"] for r in merged).lower()
    assert "..." not in texts
    assert "integridad" in texts or "12 años" in texts
    hydrated_c = next((r for r in merged if r.get("inciso") == "c"), None)
    assert hydrated_c is not None
    assert hydrated_c.get("pagina") == "18"


def test_sanitize_audit_report_removes_placeholder_preguntas():
    ar = sanitize_audit_report(
        {
            "preguntas_junta_aclaraciones": [
                "Pregunta técnica para clarificar el punto X...",
                "Con respecto a la página 18, ¿cuál plazo de experiencia aplica?",
            ],
            "gap_analysis": [],
            "alertas_descalificacion": [],
        }
    )
    assert len(ar["preguntas_junta_aclaraciones"]) == 1
    assert "página 18" in ar["preguntas_junta_aclaraciones"][0]


def test_enrich_analyst_participacion_output_end_to_end():
    data = {
        "requisitos_participacion": [
            {"inciso": "", "texto_literal": "...", "pagina": "...", "archivo_fuente": ""},
        ],
        "audit_report": {
            "preguntas_junta_aclaraciones": ["Pregunta técnica para clarificar el punto X..."],
            "gap_analysis": [],
            "alertas_descalificacion": [],
        },
    }
    out = enrich_analyst_participacion_output(
        data,
        participacion_context=_SYNTHETIC_RAG,
        full_context="=== SECCIÓN PARTICIPACIÓN ===\n" + _SYNTHETIC_RAG,
    )
    assert len(out["requisitos_participacion"]) >= 3
    assert out["participacion_enrichment"]["rag_candidates"] >= 3
    assert out["audit_report"]["preguntas_junta_aclaraciones"] == []
