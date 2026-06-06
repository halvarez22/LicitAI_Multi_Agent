"""Capa de intención conversacional (SUPER ISSUE S.1–S.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.chat_stop_reason_map import assert_user_visible_clean, sanitize_user_visible_text
from app.services.chat_user_intent import (
    UserChatIntent,
    is_bare_generar_ambiguous,
    is_economic_generation_command,
    is_expediente_generation_command,
    is_status_query,
    resolve_user_intent,
)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("generar", UserChatIntent.DESAMBIGUAR_GENERAR),
        ("adelante", UserChatIntent.DESAMBIGUAR_GENERAR),
        ("listo", UserChatIntent.DESAMBIGUAR_GENERAR),
        ("generar propuesta económica", UserChatIntent.COTIZAR),
        ("generar documentos", UserChatIntent.GENERAR_EXPEDIENTE),
        ("generar expediente", UserChatIntent.GENERAR_EXPEDIENTE),
        ("cómo vamos", UserChatIntent.VER_ESTADO),
        ("como vamos", UserChatIntent.VER_ESTADO),
        ("qué sigue", UserChatIntent.VER_ESTADO),
        ("no entiendo qué necesitas", UserChatIntent.AYUDA),
        ("¿Qué dice el Anexo III sobre muestras en las bases?", UserChatIntent.PREGUNTAR_BASES),
    ],
)
def test_resolve_user_intent_core(query: str, expected: UserChatIntent):
    got = resolve_user_intent(query)
    assert got.intent == expected


def test_bare_generar_not_ambiguous_with_target():
    assert not is_bare_generar_ambiguous("generar propuesta económica")
    assert not is_bare_generar_ambiguous("generar documentos finales")
    assert is_bare_generar_ambiguous("generar")


def test_economic_pending_prioritizes_responder():
    got = resolve_user_intent(
        "45250",
        has_economic_pending=True,
        has_any_pending=True,
        current_pending_type="economic_price",
    )
    assert got.intent == UserChatIntent.RESPONDER_PENDIENTE


def test_explicit_gen_command_skips_disambiguation():
    got = resolve_user_intent(
        "generar propuesta",
        is_explicit_gen_command=True,
    )
    assert got.intent == UserChatIntent.COTIZAR


def test_sanitize_removes_internal_codes():
    raw = "Gate 12.1 bloqueó MISSING_ECONOMIC_PROPOSAL y COMPLIANCE_GATE_BLOCKING"
    clean = sanitize_user_visible_text(raw)
    assert "Gate 12.1" not in clean
    assert "MISSING_" not in clean
    assert "COMPLIANCE_GATE" not in clean


def test_assert_user_visible_clean_raises():
    with pytest.raises(AssertionError):
        assert_user_visible_clean("Error Gate 12.1 still visible to user")


def test_utterance_battery_no_crude_codes():
    """Batería mínima S.6: frases reales no deben quedar con códigos internos tras sanitizar."""
    fixtures_path = Path(__file__).parent / "fixtures" / "chat_intent_utterances.json"
    utterances = json.loads(fixtures_path.read_text(encoding="utf-8"))
    for row in utterances:
        msg = sanitize_user_visible_text(row.get("sample_bad_response", ""))
        if msg:
            assert_user_visible_clean(msg)


def test_generation_command_helpers():
    assert is_economic_generation_command("generar propuesta económica")
    assert is_expediente_generation_command("generar documentos")
    assert is_status_query("como vamos con la licitacion")
