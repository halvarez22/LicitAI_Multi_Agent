from app.services.cronograma_enrichment_service import (
    cronograma_improved,
    cronograma_needs_enrichment,
    enrich_cronograma_from_rag,
    is_placeholder_cronograma_value,
)


def test_is_placeholder_cronograma_value():
    assert is_placeholder_cronograma_value("...")
    assert is_placeholder_cronograma_value("No especificado")
    assert not is_placeholder_cronograma_value(
        "12 de febrero de 2024 a las 14:00 horas"
    )


def test_cronograma_needs_enrichment_majority_placeholders():
    cron = {k: "..." for k in (
        "publicacion_convocatoria",
        "visita_instalaciones",
        "junta_aclaraciones",
        "presentacion_proposiciones",
        "fallo",
        "firma_contrato",
    )}
    assert cronograma_needs_enrichment(cron) is True


def test_enrich_cronograma_from_rag_uses_bases_pages(monkeypatch):
    bases_text = (
        "Las visitas se llevarán a cabo los días 06 y 07 de febrero de 2024, en horario de 09:00 a 15:00 hrs. "
        "Junta (s) de Aclaraciones Se llevará a cabo el día 12 de febrero de 2024, a las 14:00 horas. "
        "Presentación y apertura de proposiciones Los sobres deberán entregarse a más tardar el día 19 de febrero de 2024 a las 11:00 horas. "
        "Fallo Se llevará a cabo el día 28 de febrero de 2024 a las 14:00 horas. "
        "firmar el contrato el día 14 de marzo de 2024, de las 09:00 a las 14:00 hrs."
    )

    class FakeVdb:
        def query_texts(self, session_id, query, n_results=8):
            return {"documents": [], "distances": []}

        def fetch_page_documents(self, session_id, src, pg):
            if pg == 5 and "bases" in src.lower():
                return [bases_text]
            return []

    before = {k: "..." for k in (
        "publicacion_convocatoria",
        "visita_instalaciones",
        "junta_aclaraciones",
        "presentacion_proposiciones",
        "fallo",
        "firma_contrato",
    )}
    out = enrich_cronograma_from_rag("sess_demo", before, vector_db=FakeVdb())
    assert cronograma_improved(before, out)
    assert "06 y 07 de febrero de 2024" in out["visita_instalaciones"]
    assert "12 de febrero de 2024" in out["junta_aclaraciones"]
    assert "19 de febrero de 2024" in out["presentacion_proposiciones"]
    assert "28 de febrero de 2024" in out["fallo"]
    assert "14 de marzo de 2024" in out["firma_contrato"]
