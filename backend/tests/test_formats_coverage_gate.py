"""Tests para gates de completitud de formatos y entrega."""

from app.services.formats_coverage_gate import (
    count_panel_admin_generar,
    evaluate_delivery_completeness_before_final_ok,
    evaluate_formats_stage_completeness,
)


def test_count_panel_admin_generar_excludes_tecnico_modelo():
    panel = {
        "sobre_1_tecnico": [
            {"nombre": "Anexo IV - Modelo propuesta técnica", "tipo": "generar"},
            {"nombre": "Anexo II manifiesto conformidad", "tipo": "generar"},
        ],
        "requisitos_legales": [
            {"nombre": "Carta Declaración de Integridad", "tipo": "generar"},
        ],
        "sobre_2_economico": [],
        "otros_requisitos_criticos": [],
    }
    assert count_panel_admin_generar(panel) == 2


def test_formats_completeness_blocks_when_below_threshold():
    block = evaluate_formats_stage_completeness(
        generated_count=4,
        mirror_queue_size=0,
        llm_queue_size=6,
        generation_skipped=[{"nombre": "Anexo X", "reason": "shell"}],
        panel_expected=14,
    )
    assert block is not None
    assert block["code"] == "FORMATS_INCOMPLETE_DELIVERY"
    assert block["expected_count"] == 14
    assert block["generated_count"] == 4


def test_formats_completeness_passes_at_ratio():
    block = evaluate_formats_stage_completeness(
        generated_count=12,
        mirror_queue_size=0,
        llm_queue_size=14,
        generation_skipped=[],
        panel_expected=14,
    )
    assert block is None


def test_formats_completeness_passes_when_disk_coverage_high():
    """15 nuevos en corrida + 31 ya en disco = 46 generadas vs 39 esperadas."""
    block = evaluate_formats_stage_completeness(
        generated_count=46,
        mirror_queue_size=30,
        llm_queue_size=9,
        generation_skipped=[],
        panel_expected=39,
    )
    assert block is None


def test_delivery_completeness_blocks_low_coverage(monkeypatch):
    fake_report = {
        "summary": {
            "esperadas_generar": 14,
            "generadas": 5,
            "pendientes_generar": 9,
            "cobertura_generacion_pct": 35.7,
        },
        "rows": [
            {
                "estado_cobertura": "pendiente_generar",
                "accion_recomendada": "generar",
                "source_filename": "Anexo III.docx",
            }
        ],
        "manifest_files_count": 11,
    }

    def _fake_build(*_a, **_k):
        return fake_report

    monkeypatch.setattr(
        "app.services.delivery_coverage_report.build_delivery_coverage_report",
        _fake_build,
    )
    block = evaluate_delivery_completeness_before_final_ok({}, "sess-1")
    assert block is not None
    assert block["code"] == "DELIVERY_COVERAGE_GAP"
    assert block["pendientes_generar"] == 9


def test_delivery_completeness_passes_when_complete(monkeypatch):
    fake_report = {
        "summary": {
            "esperadas_generar": 10,
            "generadas": 10,
            "pendientes_generar": 0,
            "cobertura_generacion_pct": 100.0,
        },
        "rows": [],
        "manifest_files_count": 10,
    }

    monkeypatch.setattr(
        "app.services.delivery_coverage_report.build_delivery_coverage_report",
        lambda *_a, **_k: fake_report,
    )
    assert evaluate_delivery_completeness_before_final_ok({}, "sess-1") is None
