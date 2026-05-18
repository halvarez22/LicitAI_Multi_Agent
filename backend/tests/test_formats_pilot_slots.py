"""Unitarios puros: slots piloto Hito 4 (FormatsAgent / TechnicalWriter)."""
from app.core.formats_pilot_slots import (
    build_formats_pilot_missing_entries,
    list_missing_formats_pilot_slots,
)

_ALL_KEYS = [
    "razon_social",
    "rfc",
    "domicilio_fiscal",
    "representante_legal",
]


def test_list_missing_all_when_profile_empty():
    assert list_missing_formats_pilot_slots({}) == _ALL_KEYS
    assert list_missing_formats_pilot_slots(None) == _ALL_KEYS


def test_list_missing_partial():
    mp = {"rfc": "ABC123456XYZ", "domicilio_fiscal": "Calle 1"}
    assert list_missing_formats_pilot_slots(mp) == [
        "razon_social",
        "representante_legal",
    ]


def test_list_missing_none_when_complete():
    mp = {
        "razon_social": "Acme SA",
        "rfc": "ABC123456XYZ",
        "domicilio_fiscal": "Av. Siempre Viva 742",
        "representante_legal": "Juan Pérez",
    }
    assert list_missing_formats_pilot_slots(mp) == []


def test_build_missing_entries_includes_type_and_blocking_job_id():
    mp = {"razon_social": "X SA"}
    rows = build_formats_pilot_missing_entries(mp, blocking_job_id="job_123")
    assert len(rows) == 3
    assert all(r["type"] == "profile_field" for r in rows)
    assert all(r["blocking_job_id"] == "job_123" for r in rows)
    fields = {r["field"] for r in rows}
    assert fields == {"rfc", "domicilio_fiscal", "representante_legal"}


def test_whitespace_only_counts_as_missing():
    assert list_missing_formats_pilot_slots({"rfc": "   "}) == _ALL_KEYS


def test_placeholder_na_counts_as_missing():
    assert "domicilio_fiscal" in list_missing_formats_pilot_slots(
        {
            "razon_social": "Z SA",
            "rfc": "ZZZ010101ZZZ",
            "domicilio_fiscal": "N/A",
            "representante_legal": "Ana",
        }
    )
