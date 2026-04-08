from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.agents.formats import FormatsAgent
from app.core.template_engine import LegalTemplateEngine


def _load_real_fixture() -> dict:
    path = Path(__file__).parent / "fixtures" / "real_sessions" / "template_lock_data.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_render_anexo_7_with_real_anonymized_data() -> None:
    fx = _load_real_fixture()
    engine = LegalTemplateEngine()
    data = {
        "razon_social": fx["master_profile"]["razon_social"],
        "rfc": fx["master_profile"]["rfc"],
        "numero_licitacion": fx["session_id"],
        "servicio": "Servicio integral de vigilancia",
        "nombre_representante": fx["master_profile"]["representante_legal"],
        "lugar": fx["master_profile"]["ciudad"],
        "fecha": fx["doc_metadata"]["fecha"],
        "tipo_licitacion": "Licitacion Publica",
        "autoridad_convocante": "Convocante"
    }
    rendered = engine.render("anexo_7", data)
    assert "BAJO PROTESTA DE DECIR VERDAD" in rendered
    assert fx["master_profile"]["razon_social"] in rendered
    assert fx["session_id"] in rendered
    assert engine.verify_integrity(rendered, "anexo_7") is True


def test_verify_integrity_blocks_tampered_text() -> None:
    fx = _load_real_fixture()
    engine = LegalTemplateEngine()
    rendered = engine.render(
        "anexo_11",
        {
            "razon_social": fx["master_profile"]["razon_social"],
            "rfc": fx["master_profile"]["rfc"],
            "numero_licitacion": fx["session_id"],
            "servicio": "Servicio integral de vigilancia",
            "nombre_representante": fx["master_profile"]["representante_legal"],
            "lugar": fx["master_profile"]["ciudad"],
            "fecha": fx["doc_metadata"]["fecha"],
            "tipo_licitacion": "Licitacion Publica",
            "autoridad_convocante": "Convocante"
        },
    )
    tampered = rendered.replace("bajo protesta de decir verdad", "texto alterado")
    assert engine.verify_integrity(tampered, "anexo_11") is False


def test_formats_agent_maps_legal_templates() -> None:
    req7 = {"id": "ANEXO 7", "nombre": "Personalidad juridica", "descripcion": ""}
    req11 = {"id": "x", "nombre": "Carta de conformidad", "descripcion": "anexo 11"}
    req15 = {"id": "ANEXO 15", "nombre": "Manifestacion", "descripcion": "art 50 y 60"}
    assert FormatsAgent._template_id_for_requirement(req7) == "anexo_7"
    assert FormatsAgent._template_id_for_requirement(req11) == "anexo_11"
    assert FormatsAgent._template_id_for_requirement(req15) == "anexo_15"


@pytest.mark.regression
def test_regression_template_lock_real_session_2026_04_08() -> None:
    """Regresión real anonimizada derivada de sesión la-51-gyn-051gyn025-n-8-2024."""
    fx = _load_real_fixture()
    engine = LegalTemplateEngine()
    rendered = engine.render(
        "anexo_15",
        {
            "razon_social": fx["master_profile"]["razon_social"],
            "rfc": fx["master_profile"]["rfc"],
            "numero_licitacion": fx["session_id"],
            "servicio": "Servicio integral de vigilancia",
            "nombre_representante": fx["master_profile"]["representante_legal"],
            "lugar": fx["master_profile"]["ciudad"],
            "fecha": fx["doc_metadata"]["fecha"],
            "tipo_licitacion": "Licitacion Publica",
            "autoridad_convocante": "Convocante"
        },
    )
    assert engine.verify_integrity(rendered, "anexo_15") is True


def test_template_render_performance_under_100ms_each() -> None:
    fx = _load_real_fixture()
    engine = LegalTemplateEngine()
    data = {
        "razon_social": fx["master_profile"]["razon_social"],
        "rfc": fx["master_profile"]["rfc"],
        "numero_licitacion": fx["session_id"],
        "servicio": "Servicio integral de vigilancia",
        "nombre_representante": fx["master_profile"]["representante_legal"],
        "lugar": fx["master_profile"]["ciudad"],
        "fecha": fx["doc_metadata"]["fecha"],
        "tipo_licitacion": "Licitacion Publica",
        "autoridad_convocante": "Convocante"
    }
    t0 = time.perf_counter()
    for _ in range(50):
        engine.render("anexo_7", data)
    ms_each = ((time.perf_counter() - t0) * 1000) / 50.0
    assert ms_each < 100.0
