"""Oráculo CI — machotes oficiales obra/adquisiciones (Fase 1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.obra_economic_annex_clauses import (
    is_official_obra_e1_mirror_content,
    is_official_obra_e3e_mirror_content,
)
from app.services.official_format_delivery_gate import validate_official_mirror_delivery
from app.services.official_format_resolver import resolve_official_deliverable

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "official_format" / "oracle_cases.json"


def _load_cases():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return data.get("cases") or []


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["case_id"])
def test_official_format_oracle_case(case: dict):
    dedupe = str(case["dedupe_key"])
    mp = dict(case.get("master_profile") or {})
    resumen = dict(case.get("resumen") or {})
    snippet = str(case.get("corpus_snippet") or "")
    session_state = {
        "bases_corpus_hint": snippet,
        "objeto_obra": case.get("obra_descripcion") or "",
        "name": case.get("case_id", ""),
        "concurso_label": case.get("concurso") or "",
    }
    if case.get("plazo"):
        session_state["_obra_plazo_hint"] = case["plazo"]

    result = resolve_official_deliverable(
        dedupe,
        session_id="oracle_session",
        session_state=session_state,
        master_profile=mp,
        resumen=resumen,
        snippets_by_key={dedupe: snippet},
    )
    expect = case.get("expect") or {}
    body = result.content
    low = body.lower()

    if expect.get("official_bases_mirror") is True:
        assert result.official_bases_mirror is True
    if expect.get("official_bases_mirror") is False:
        assert result.official_bases_mirror is False

    for token in expect.get("must_contain") or []:
        assert token.lower() in low or token in body, f"falta {token!r} en cuerpo"

    for token in expect.get("must_not_contain") or []:
        assert token.lower() not in low, f"no debe aparecer {token!r}"

    if dedupe == "obra|E1":
        assert is_official_obra_e1_mirror_content(body) == result.official_bases_mirror
    if dedupe == "obra|E3E":
        assert is_official_obra_e3e_mirror_content(body) == result.official_bases_mirror


def test_delivery_gate_blocks_missing_mirror():
    gate = validate_official_mirror_delivery(
        stage="economic",
        generated_documents=[
            {
                "nombre": "Carta E-1",
                "dedupe_key": "obra|E1",
                "official_template_expected": True,
                "official_bases_mirror": False,
            }
        ],
    )
    assert gate["validation_passed"] is False
    assert gate["blocking_count"] == 1


def test_delivery_gate_passes_verified_mirror():
    gate = validate_official_mirror_delivery(
        stage="economic",
        generated_documents=[
            {
                "nombre": "Carta E-1",
                "dedupe_key": "obra|E1",
                "official_template_expected": True,
                "official_bases_mirror": True,
            }
        ],
    )
    assert gate["validation_passed"] is True
