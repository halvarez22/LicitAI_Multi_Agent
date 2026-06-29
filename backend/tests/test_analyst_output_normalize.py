"""Normalización y señales tabulares del analista (sin expediente fijo)."""
from app.services.analyst_output_normalize import (
    detect_tabular_reference_signals,
    normalize_alcance_operativo_list,
    normalize_regla_economica_anchor,
    normalize_reglas_economicas_anchored,
    normalize_reglas_economicas_dict,
)


def test_detect_tabular_reference_signals_anexo_generico():
    t = "Las cantidades establecidas en el anexo número 1 de la convocatoria serán vinculantes."
    s = detect_tabular_reference_signals(t)
    assert s["texto_sugiere_partidas_o_anexo_tabular"] is True
    assert s["coincidencias_aproximadas"] >= 1


def test_detect_tabular_vacio():
    s = detect_tabular_reference_signals("")
    assert s["texto_sugiere_partidas_o_anexo_tabular"] is False


def test_normalize_reglas_economicas_rellena_defaults():
    raw = {"importe_minimo": "Suma seis meses", "meses_maximo": "11"}
    out = normalize_reglas_economicas_dict(raw)
    assert out["criterio_importe_minimo_o_plazo_inferior"] == "Suma seis meses"
    assert out["meses_o_periodo_maximo_citado"] == "11"
    assert out["modalidad_contratacion_observada"] == "No especificado"


def test_normalize_regla_economica_anchor_object():
    raw = {
        "value": "Propuesta no menor a $5,100,000.00",
        "page": 12,
        "snippet": "MONTOS DE OBRA EJECUTADA MÍNIMO A $5,100,000.00",
        "source": "bases.pdf",
    }
    out = normalize_regla_economica_anchor(raw)
    assert out["value"] == "Propuesta no menor a $5,100,000.00"
    assert out["page"] == 12
    assert "5,100,000" in out["snippet"]
    assert out["source"] == "bases.pdf"


def test_normalize_reglas_economicas_anchored_aliases():
    raw = {
        "importe_minimo": {
            "value": "Seis meses de experiencia",
            "pagina": "39",
            "evidence_snippet": "experiencia mínima de seis meses",
            "archivo_fuente": "convocatoria.pdf",
        }
    }
    out = normalize_reglas_economicas_anchored(raw)
    assert "criterio_importe_minimo_o_plazo_inferior" in out
    assert out["criterio_importe_minimo_o_plazo_inferior"]["page"] == 39


def test_normalize_reglas_dict_from_anchored():
    anchored = {
        "criterio_importe_minimo_o_plazo_inferior": {
            "value": "$500,000",
            "page": 5,
            "snippet": "importe mínimo",
            "source": "bases.pdf",
        }
    }
    flat = normalize_reglas_economicas_dict(anchored)
    assert flat["criterio_importe_minimo_o_plazo_inferior"] == "$500,000"


def test_normalize_alcance_operativo_alias():
    raw = [
        {
            "area": "Zona A",
            "turno": "24h",
            "texto_literal": "fila completa",
        }
    ]
    out = normalize_alcance_operativo_list(raw)
    assert len(out) == 1
    assert out[0]["ubicacion_o_area"] == "Zona A"
    assert out[0]["turno"] == "24h"
