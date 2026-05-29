"""Supresión de alerta tabular obsoleta cuando ya hay session_line_items."""

from app.utils.audit_processor import (
    process_audit_results_backend,
    should_show_tabular_missing_alert,
    strip_stale_tabular_alert_from_dictamen,
)

_ALERTA = (
    "Las bases parecen remitir a partidas o anexos tabulares; no hay filas en "
    "session_line_items. Ingerir y reprocesar el Excel u hoja de partidas asociada."
)


def test_should_show_alert_only_when_zero_line_items():
    datos = {"alerta_faltante": _ALERTA, "line_items_count": 0}
    assert should_show_tabular_missing_alert(datos, None) is True
    assert should_show_tabular_missing_alert(datos, 2823) is False
    assert should_show_tabular_missing_alert(datos, 0) is True
    assert should_show_tabular_missing_alert({"line_items_count": 5}, None) is False


def test_process_audit_omits_alert_when_line_items_count_provided():
    payload = {
        "analysis": {
            "data": {
                "requisitos_participacion": [],
                "requisitos_filtro": [],
                "reglas_economicas": {},
                "alcance_operativo": [],
                "datos_tabulares": {
                    "alerta_faltante": _ALERTA,
                    "line_items_count": 0,
                },
            }
        },
        "compliance": {"data": {"administrativo": [], "tecnico": [], "formatos": []}},
        "economic": {"data": {}},
    }
    with_alert = process_audit_results_backend(payload, line_items_count=0)
    ids_with = {h.get("id") for h in with_alert.get("causales", [])}
    assert "base-tabular-alert" in ids_with

    without_alert = process_audit_results_backend(payload, line_items_count=100)
    ids_without = {h.get("id") for h in without_alert.get("causales", [])}
    assert "base-tabular-alert" not in ids_without


def test_strip_stale_from_persisted_dictamen():
    dictamen = {
        "causales": [
            {"id": "base-tabular-alert", "category": "bases_datos_tabulares", "texto": _ALERTA},
            {"id": "risk-1", "category": "risk", "texto": "Otro", "isRisk": True},
        ],
        "totalRequisitos": 2,
        "riesgos": 1,
    }
    out = strip_stale_tabular_alert_from_dictamen(dictamen, 50)
    assert len(out["causales"]) == 1
    assert out["causales"][0]["id"] == "risk-1"
    assert out["totalRequisitos"] == 1
    assert out["riesgos"] == 1
