from app.agents.analyst import build_sector_classification


def test_sector_clasifica_obra_publica_con_evidencia():
    context = """
    === SECCIÓN ECONÓMICA Y PARTIDAS ===
    El licitante deberá presentar análisis de precios unitarios y catálogo de conceptos.
    Además, incluir programa de obra y maquinaria y equipo disponible.
    """
    out = build_sector_classification(context, llm_data={})
    assert out["sector_id"] == "obra_publica"
    assert out["confidence"] >= 0.55
    assert any(e["signal_code"].startswith("OP_") for e in out["evidence"])


def test_sector_detecta_senales_salud_recomendadas():
    context = """
    === SECCIÓN PARTICIPACIÓN ===
    Se solicita registro sanitario vigente, carta de apoyo del fabricante
    y aviso de funcionamiento emitido por autoridad competente.
    """
    out = build_sector_classification(context, llm_data={})
    assert out["sector_id"] == "salud"
    codes = {e["signal_code"] for e in out["evidence"]}
    assert "SALUD_CARTA_APOYO_FABRICANTE" in codes
    assert "SALUD_AVISO_FUNCIONAMIENTO" in codes


def test_sector_marca_mixto_cuando_diferencia_es_baja():
    context = """
    === SECCIÓN ECONÓMICA Y PARTIDAS ===
    Se solicita análisis de precios unitarios y catálogo de conceptos.
    === SECCIÓN PARTICIPACIÓN ===
    Se requiere registro sanitario y carta de apoyo del fabricante.
    """
    out = build_sector_classification(context, llm_data={})
    assert out["sector_id"] == "mixto"


def test_sector_marca_indeterminado_sin_senales():
    out = build_sector_classification("Texto administrativo sin señales sectoriales.", llm_data={})
    assert out["sector_id"] == "indeterminado"
    assert out["confidence"] < 0.55
