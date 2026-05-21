"""Pruebas de helpers de acknowledgment Go/No-Go."""
from app.services.go_no_go_session_bridges import (
    build_silent_go_no_go_override,
    is_go_no_go_acknowledged,
)


def test_is_go_no_go_acknowledged_user_and_system():
    assert is_go_no_go_acknowledged({"authorized_by": "user"})
    assert is_go_no_go_acknowledged({"authorized_by": "system_auto"})
    assert not is_go_no_go_acknowledged({})
    assert not is_go_no_go_acknowledged({"authorized_by": "unknown"})


def test_build_silent_go_no_go_override_auditable():
    gng = {
        "semaforo": "YELLOW",
        "brechas": [{"id": "b1"}, {"id": "b2"}],
    }
    rec = build_silent_go_no_go_override(gng, mode="analysis_only")
    assert rec["authorized_by"] == "system_auto"
    assert rec["semaforo"] == "YELLOW"
    assert rec["brechas_registradas"] == 2
    assert rec["brechas_autorizadas"] == ["b1", "b2"]
    assert rec["policy"] == "silent_analysis"
    assert rec.get("timestamp")
