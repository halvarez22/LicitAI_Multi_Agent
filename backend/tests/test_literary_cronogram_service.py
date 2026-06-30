"""Citas literales de cronograma alineadas al submission_checklist."""
from unittest.mock import MagicMock

from app.services.literary_cronogram_service import (
    build_canonical_literary_cronogram,
    enrich_checklist_hitos_literary,
    _literal_needs_repolish,
    _polish_hito_literal,
    _trim_at_sentence_boundary,
    _trim_procedural_act_sentence,
)
from tests.test_cronograma_bases_extract import BARDA_GUANAJUATO_SNIPPET

BARDA_PRESENTACION_NOISE = (
    "Obra Pública ubicada en el Blvd. Juan José Torres Landa No.1701-B Ote. "
    "El día 19 de diciembre del 2025, a las 9:30 horas. A la hora señalada para la licitación, l"
)


def _mock_vdb(blob: str):
    vdb = MagicMock()
    vdb.scan_session_chunks.return_value = [
        (blob[:500], {"source": "BASES.pdf", "page": 29}),
        (blob[500:], {"source": "BASES.pdf", "page": 30}),
    ]
    vdb.fetch_page_documents.side_effect = lambda _sid, _src, pg: (
        [blob[:500]] if int(str(pg)) == 29 else [blob[500:]]
    )
    return vdb


def test_build_canonical_literary_cronogram_aligns_with_checklist(monkeypatch):
    session_state = {
        "submission_checklist": {
            "hitos": [
                {
                    "id": "visita_instalaciones",
                    "nombre": "Visita a instalaciones",
                    "fecha_texto_raw": "10 de diciembre del año 2025, a las 10:00 horas.",
                },
                {
                    "id": "junta_aclaraciones",
                    "nombre": "Junta de aclaraciones",
                    "fecha_texto_raw": "10 de diciembre del año 2025, a las 10:30 hrs",
                },
                {
                    "id": "presentacion_proposiciones",
                    "nombre": "Presentación y apertura de proposiciones",
                    "fecha_texto_raw": "19 de diciembre de 2025",
                },
                {
                    "id": "fallo",
                    "nombre": "Fallo",
                    "fecha_texto_raw": "26 de diciembre de 2025",
                },
            ]
        }
    }
    vdb = _mock_vdb(BARDA_GUANAJUATO_SNIPPET)
    monkeypatch.setattr(
        "app.services.vector_service.VectorDbServiceClient",
        lambda: vdb,
    )
    bullets, top = build_canonical_literary_cronogram(
        session_state, "sess-barda", "BASES.pdf"
    )
    assert len(bullets) >= 4
    joined = "\n".join(bullets).lower()
    assert "junta" in joined
    assert "10 de diciembre" in joined
    assert "19 de diciembre" in joined
    assert "26 de diciembre" in joined
    assert top is not None
    assert top.get("hito_id") == "visita_instalaciones"
    assert not top.get("checklist_only")
    for line in bullets:
        body = line.split("\n")[0].lstrip("- ").strip()
        if body and not body.startswith("Publicación") and not body.startswith("Firma"):
            assert body.endswith("."), body[:80]


def test_trim_at_sentence_boundary_ends_on_period():
    raw = "A" * 100 + ". " + "B" * 200
    out = _trim_at_sentence_boundary(raw, max_len=150)
    assert out.endswith(".")
    assert "BBBB" not in out


def test_polish_junta_completes_sentence():
    blob = BARDA_GUANAJUATO_SNIPPET.strip()
    truncated = (
        "JUNTA DE ACLARACIONES Para tratar lo relacionado con el objeto del mismo "
        "procedimiento de adjudicación, se convoca a todos los participantes para su "
        "desahogo el día 10 de diciembre del año 2025 a las 10:30 hrs en la Dirección de Costos y Presupuestos de la"
    )
    hito = {"nombre": "Junta de aclaraciones", "fecha_texto_raw": "10 de diciembre del año 2025, a las 10:30 hrs"}
    out = _polish_hito_literal("junta_aclaraciones", truncated, hito["fecha_texto_raw"], blob, hito)
    assert out.endswith(".")
    assert "10:30" in out
    assert "Presupuestos" in out
    assert "Blvd" not in out
    assert not out.endswith("de la")


def test_trim_procedural_act_closes_at_hora_not_blvd():
    raw = (
        "visita al sitio el día 10 de diciembre del año 2025, siendo el lugar de la cita en: "
        "en la Dirección de Costos y Presupuestos de la Dirección General de Obra Pública "
        "ubicada en el Blvd. Juan José Torres a las 10:00 horas."
    )
    out = _trim_procedural_act_sentence(raw)
    assert "10:00" in out
    assert out.endswith(".")
    assert "Blvd" not in out
    assert "Presupuestos" in out


def test_literal_needs_repolish_detects_blvd_and_caps_junta():
    assert _literal_needs_repolish(
        "visita_instalaciones",
        "visita al sitio Blvd a las 10:00 horas.",
    )
    assert _literal_needs_repolish(
        "junta_aclaraciones",
        "JUNTA DE ACLARACIONES Para tratar lo relacionado.",
    )


def test_polish_visita_labels_and_trims_blvd():
    blob = BARDA_GUANAJUATO_SNIPPET.strip()
    hito = {
        "nombre": "Visita a instalaciones",
        "fecha_texto_raw": "10 de diciembre de 2025, 10:00",
    }
    noisy = (
        "visita al sitio donde se ejecutará la obra, misma que será el día 10 de diciembre "
        "del año 2025, siendo el lugar de la cita en: en la Dirección de Costos y Presupuestos "
        "de la Dirección General de Obra Pública ubicada en el Blvd a las 10:00 horas."
    )
    out = _polish_hito_literal("visita_instalaciones", noisy, hito["fecha_texto_raw"], blob, hito)
    assert out.startswith("Visita a instalaciones")
    assert "Blvd" not in out
    assert "10:00" in out


def test_polish_presentacion_labels_act_and_date_sentence():
    blob = BARDA_GUANAJUATO_SNIPPET.strip() + " " + BARDA_PRESENTACION_NOISE
    hito = {
        "nombre": "Presentación y apertura de proposiciones",
        "fecha_texto_raw": "19 de diciembre de 2025",
    }
    out = _polish_hito_literal(
        "presentacion_proposiciones",
        BARDA_PRESENTACION_NOISE,
        hito["fecha_texto_raw"],
        blob,
        hito,
    )
    assert out.startswith("Presentación y apertura de proposiciones")
    assert "19 de diciembre" in out
    assert out.endswith(".")
    assert "Obra Pública ubicada" not in out


def test_enrich_checklist_hitos_literary_junta_and_display(monkeypatch):
    junta_narrative = (
        "de adjudicación, se convoca a todos los participantes para su desahogo "
        "el día 10 de diciembre del año 2025 a las 10:30 hrs en la Dirección de Costos"
    )
    hitos = [
        {
            "id": "junta_aclaraciones",
            "nombre": "Junta de aclaraciones",
            "fecha_texto_raw": junta_narrative,
            "estado": "pendiente",
        }
    ]
    vdb = _mock_vdb(BARDA_GUANAJUATO_SNIPPET)
    monkeypatch.setattr(
        "app.services.vector_service.VectorDbServiceClient",
        lambda: vdb,
    )
    out = enrich_checklist_hitos_literary(
        hitos,
        "sess-barda",
        {},
        cronograma={"junta_aclaraciones": junta_narrative},
    )
    assert len(out) == 1
    assert "10 de diciembre de 2025" in out[0]["fecha_texto_raw"]
    assert "junta" in out[0]["bases_literal"].lower()
    assert "10:30" in out[0]["bases_literal"]
    assert out[0]["provenance_ui"]["anchor_kind"] == "indexed"
    assert out[0]["provenance_ui"]["page"] is not None
