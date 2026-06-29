"""Tests HRU procedencia económica en chat."""

from __future__ import annotations

from app.services.chat_economic_provenance_service import (
    build_economic_provenance_message,
    collect_economic_provenance_facts,
    detect_economic_provenance_intent,
)
from app.services.chat_gate5_formatter import count_visible_lines
from app.services.chat_stop_reason_map import sanitize_user_visible_text


def test_detect_catalog_question():
    assert detect_economic_provenance_intent(
        "me refiero a los precios que te proporcione en mi catalogo de conceptos"
    ) in ("catalog", "general")


def test_detect_total_question():
    assert detect_economic_provenance_intent(
        "de donde sacaste este total Total de la proposicion $3,278,289.63"
    ) == "total"


def test_detect_como_viste_precios():
    assert detect_economic_provenance_intent("como viste mis precios del catalogo") == "catalog"


def test_build_message_with_snapshot():
    state = {
        "master_profile": {"razon_social": "Constructora Demo"},
        "tasks_completed": [
            {
                "task": "economic_proposal",
                "result": {
                    "grand_total": 3278289.63,
                    "total_base": 2826100.0,
                    "iva_amount": 452189.63,
                    "currency": "MXN",
                    "items": [
                        {
                            "concepto": "Limpieza final de obra",
                            "cantidad": 1600,
                            "precio_unitario": 65.0,
                            "subtotal": 104000.0,
                        },
                        {
                            "concepto": "Muro de block",
                            "cantidad": 100,
                            "precio_unitario": 1200.0,
                            "subtotal": 120000.0,
                        },
                    ],
                },
            }
        ],
        "capture_matrix_blocks": [
            {"source_filename": "CATALOGO DE CONCEPTOS CONSTRUCTORA.pdf", "matrix_rows": []}
        ],
    }
    facts = collect_economic_provenance_facts(state, session_id="demo")
    assert facts.has_snapshot
    assert facts.grand_total == 3278289.63
    assert facts.catalog_sources
    msg = build_economic_provenance_message(state, session_id="demo", mode="total")
    assert count_visible_lines(msg) <= 3
    assert "3,278,289.63" in msg
    assert "CATALOGO" in msg.upper() or "catálogo" in msg.lower() or "motor económico" in msg.lower()
    assert "MONEDA REQUERIDA" not in msg


def test_sanitize_strips_prompt_leak():
    dirty = (
        "**RESPUESTA DIRECTA AL USUARIO** La propuesta...\n"
        "**ALERTA DE BRECHA ECONÓMICA:** foo\n"
        "[FUENTE: CATÁLOGO.pdf | PÁGINA: 2]"
    )
    clean = sanitize_user_visible_text(dirty)
    assert "RESPUESTA DIRECTA" not in clean
    assert "BRECHA ECON" not in clean.upper()
    assert "[FUENTE:" not in clean


def test_build_message_resolves_anexo_from_panel():
    state = {
        "master_profile": {"razon_social": "Constructora Demo"},
        "document_candidates_consolidated": {
            "sobre_2_economico": [
                {
                    "nombre_canonico": "Anexo AE — Proposición económica",
                    "snippet_representativo": "Carta compromiso proposición económica",
                    "sobre_clasificado": "sobre_2_economico",
                }
            ],
            "sobre_1_tecnico": [],
            "requisitos_legales": [],
            "otros_requisitos_criticos": [],
        },
        "tasks_completed": [
            {
                "task": "economic_proposal",
                "result": {
                    "grand_total": 100000.0,
                    "currency": "MXN",
                    "items": [
                        {
                            "concepto": "Partida demo",
                            "cantidad": 1,
                            "precio_unitario": 100000.0,
                            "subtotal": 100000.0,
                        },
                    ],
                },
            }
        ],
    }
    msg = build_economic_provenance_message(
        state,
        session_id="demo",
        mode="total",
        user_query="de donde sacaste el total del ANEXO AE",
    )
    assert count_visible_lines(msg) <= 3
    assert "AE" in msg.upper() or "proposición" in msg.lower()
