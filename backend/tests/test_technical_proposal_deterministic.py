"""Propuesta técnica TE-01 determinista y normalización de fechas."""
from app.services.document_date_resolver import normalize_body_spanish_dates
from app.services.technical_proposal_deterministic import (
    build_propuesta_tecnica_body,
    is_primary_technical_proposal,
)


def test_is_primary_technical_proposal_te01():
    assert is_primary_technical_proposal("TE-01", "Propuesta Tecnica", "")
    assert is_primary_technical_proposal("02_TE-01_Propuesta_Tecnica.docx", "desc", "")
    assert not is_primary_technical_proposal("TE-12", "Puntuacion", "")


def test_build_propuesta_tecnica_sin_evaluador():
    text = build_propuesta_tecnica_body(
        razon_social="Empresa SA",
        rfc="RFC123",
        representante="Rep Legal",
        domicilio="Querétaro",
        tender_name="LICITACION DEMO",
        req_nombre="TE-01 Propuesta",
        req_desc="Sistema solar",
        req_context="Especificaciones del sistema fotovoltaico.",
    )
    low = text.lower()
    assert "criterios de evaluación" not in low
    assert "evaluar la propuesta" not in low
    assert "sistema solar" in low


def test_normalize_body_spanish_dates_replaces_server_date():
    canon = "23 de abril de 2026"
    raw = "En México, a 3 de junio de 2026, presentamos la propuesta."
    out = normalize_body_spanish_dates(raw, canon)
    assert "3 de junio" not in out
    assert canon in out
