"""Tests P2-03: validadores del smoke HTTP UI."""
from __future__ import annotations

from scripts.smoke_ui_artifacts import (
    _check_dictamen,
    _check_formats_panel,
    _check_junta,
    _check_submission_checklist,
    _parse_generic,
)


def test_parse_generic_success():
    ok, data, err = _parse_generic({"success": True, "data": {"x": 1}})
    assert ok is True
    assert data == {"x": 1}
    assert err == ""


def test_check_submission_checklist_against_mins():
    ok, detail = _check_submission_checklist(
        {"submission_checklist": {"hitos": [{}] * 6}},
        {"hitos": 6},
    )
    assert ok is True
    assert "hitos=6" in detail

    ok2, _ = _check_submission_checklist(
        {"submission_checklist": {"hitos": [{}]}},
        {"hitos": 6},
    )
    assert ok2 is False


def test_check_junta_and_formats():
    ok_j, _ = _check_junta(
        {"junta_aclaraciones_questions": {"items": [{}, {}], "summary": {"total": 2}}},
        {"junta_items": 2},
    )
    assert ok_j is True

    ok_f, _ = _check_formats_panel(
        {"pliego_formats_panel": {"sobre_1_tecnico": [{}] * 10}},
        {"sobre_1_tecnico": 9},
    )
    assert ok_f is True


def test_check_dictamen_minimal():
    ok, detail = _check_dictamen(
        {"dictamen": {"zones": [{}], "totalRequisitos": 10}},
        {"has_dictamen": True},
    )
    assert ok is True
    assert "zones=1" in detail
