"""Pruebas de la métrica brechas_atenuadas_por_evidencia_sesion (Go/No-Go)."""
from __future__ import annotations

from app.agents.go_no_go import _count_brechas_atenuadas_por_evidencia_sesion
from app.agents.go_no_go_scorer import detect_brechas

_COMPLIANCE_CONTRATOS = {
    "summary": {"causas_desechamiento": []},
    "administrativo": [],
    "tecnico": [
        {"descripcion": "Acreditar contratos similares en servicios de vigilancia"},
    ],
    "formatos": [],
}


def test_atenuadas_cero_sin_baseline() -> None:
    brechas = detect_brechas(
        _COMPLIANCE_CONTRATOS,
        {"contratos_previos": [{"contrato_id": "1"}]},
    )
    assert (
        _count_brechas_atenuadas_por_evidencia_sesion(
            compliance_data=_COMPLIANCE_CONTRATOS,
            brechas_efectivo=brechas,
            baseline_profile=None,
        )
        == 0
    )


def test_atenuadas_una_cuando_evidencia_cierra_requisito() -> None:
    brechas_efectivo = detect_brechas(
        _COMPLIANCE_CONTRATOS,
        {"contratos_previos": [{"contrato_id": "8900005011"}]},
    )
    assert len(brechas_efectivo) == 0
    n = _count_brechas_atenuadas_por_evidencia_sesion(
        compliance_data=_COMPLIANCE_CONTRATOS,
        brechas_efectivo=brechas_efectivo,
        baseline_profile={},
    )
    assert n == 1


def test_atenuadas_cero_cuando_maestro_ya_cubre() -> None:
    perfil = {"contratos_previos": [{"contrato_id": "1"}]}
    b = detect_brechas(_COMPLIANCE_CONTRATOS, perfil)
    assert len(b) == 0
    n = _count_brechas_atenuadas_por_evidencia_sesion(
        compliance_data=_COMPLIANCE_CONTRATOS,
        brechas_efectivo=b,
        baseline_profile=dict(perfil),
    )
    assert n == 0
