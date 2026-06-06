"""Tests del generador determinista de APU."""
from app.services.apu_document_builder import build_apu_markdown


def test_apu_markdown_concursante_sin_evaluador():
    text = build_apu_markdown(
        razon_social="Comercializadora Mayo y Torres, S.A. de C.V.",
        rfc="CMT160107S83",
        representante="ENRIQUE TADEO TORRES DORANTES",
        domicilio="Avenida La Reserva 3, Querétaro",
        fecha_es="24 de abril de 2026",
        procedimiento="001-IR ejemplo",
        subtotal=2586233.0,
        iva=413797.28,
        total=3000030.28,
        line_items=[{"descripcion": "Sistema solar", "importe": 2586233.0}],
    )
    low = text.lower()
    assert "someto a su consideración" in low
    assert "evaluar la propuesta" not in low
    assert "criterios de evaluación" not in low
    assert "2,586,233" in text
