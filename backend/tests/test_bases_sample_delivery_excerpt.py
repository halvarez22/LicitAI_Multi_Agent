"""HRU: entrega/recepción de muestras en chat (extracción determinista)."""
from __future__ import annotations

from app.services.bases_sample_delivery_excerpt_service import (
    compose_sample_delivery_chat_response,
    detect_sample_delivery_intent,
    extract_sample_delivery_sections,
)

ISAPEG_PAGE6_7 = """
--- PÁGINA 6 (bases_0001.pdf) ---
c) Características de Muestras

Para el Anexo III partida 2 (limpieza) los licitantes deberán entregar invariablemente una muestra física de los siguientes insumos:

• 1 rollo de papel higiénico en bobina
• 1 litro de alcohol en gel

Dichas muestras deberán estar debidamente identificadas mediante etiqueta adherida.

d) Entrega y Recepción de Muestras de los Licitantes

La recepción de las muestras físicas presentadas por los licitantes participantes será a más tardar el día 19 de febrero de 2024, en el Almacén Central del ISAPEG ubicado en Carretera Guanajuato – Juventino Rosas km. 9.5, Colonia Yerbabuena, Guanajuato, Gto., en un horario de lunes a viernes de las 9:00 a las 13:30 horas.

El licitante deberá de presentar sus muestras acompañadas con original y 2 copias del recibo de muestras (Anexo L).

--- PÁGINA 7 (bases_0001.pdf) ---
los demás licitantes, deberán pasar por sus muestras a la Dirección del Almacén Central del ISAPEG en la semana del 04 al 08 de marzo del 2024.

e) Evaluación de Muestras

La evaluación de las muestras presentadas por los licitantes consistirá en la verificación de la muestra física de conformidad a lo solicitado en las presentes bases y anexos. Se podrán realizar pruebas destructivas.

f) Presentación y apertura de proposiciones

Los sobres de las proposiciones Técnicas y Económicas deberán entregarse a más tardar el día 19 de febrero de 2024 a las 11:00 horas.
"""

PAGE16_SNIPPET = """
--- PÁGINA 16 (bases_0001.pdf) ---
31. Copia simple del recibo de muestras con el sello del Almacén Estatal del Instituto de Salud Pública del Estado de Guanajuato (Anexo L Comprobante de entrega de muestra para revisión), que evidencie la entrega total de las muestras requeridas en el inciso c) Características de muestras del Apartado III. En caso de no presentar el total de las muestras se dará como no presentado el requisito. Aplica para la partida 2.
"""


def test_detect_sample_delivery_intent_user_question():
    q = "¿Qué especifican las bases referente a la entrega recepción de muestras?"
    assert detect_sample_delivery_intent(q) is True


def test_extract_sections_pages_c_d_e():
    payload = extract_sample_delivery_sections(ISAPEG_PAGE6_7 + PAGE16_SNIPPET, source="bases_0001.pdf")
    assert payload["ready"] is True
    ids = [s["section_id"] for s in payload["sections"]]
    assert "c" in ids and "d" in ids and "e" in ids
    d = next(s for s in payload["sections"] if s["section_id"] == "d")
    assert d.get("pagina_label") in ("6-7", "6", "7", "6, 7")
    c = next(s for s in payload["sections"] if s["section_id"] == "c")
    assert c.get("pagina_label") == "6"
    e = next(s for s in payload["sections"] if s["section_id"] == "e")
    assert e.get("pagina_label") == "7"
    anexo = next(s for s in payload["sections"] if s["section_id"] == "anexo_l")
    assert anexo.get("pagina_label") == "16"
    out = compose_sample_delivery_chat_response(payload)
    assert "Características de Muestras" in out
    assert "Entrega y Recepción" in out
    assert "Evaluación de Muestras" in out
    assert "19 de febrero de 2024" in out
    assert "Anexo L" in out
    assert "BIODEGRADABILIDAD" not in out
    assert "RPBI" not in out
    assert "apertura de proposiciones" in out.lower()


def test_broad_supplies_query_not_sample_delivery_only():
    q = (
        "NO pregunto por formato de propuesta económica. Solo insumos Partida 2: "
        "biodegradabilidad, envase, RPBI y muestras."
    )
    assert detect_sample_delivery_intent(q) is False
