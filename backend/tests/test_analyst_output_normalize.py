"""Normalización y señales tabulares del analista (sin expediente fijo)."""
from app.services.analyst_output_normalize import (
    detect_tabular_reference_signals,
    normalize_alcance_operativo_list,
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
