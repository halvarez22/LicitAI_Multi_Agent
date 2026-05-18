"""
Tests del quality gate consciente del tipo de licitación.

Cubre el bug donde licitaciones de obra pública (LOPSRM / categoría OBRA)
eran bloqueadas por el quality gate porque generar_count = 0, aunque ese
sea el comportamiento correcto para ese tipo de licitación (los requisitos
técnicos son formas predefinidas AT/AE que se presentan físicamente).

Spec: .kiro/specs/tender-router-quality-gate/
"""
import pytest
from typing import Any, Dict, Optional
from unittest.mock import patch

from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

# Importar la función desde ambos agentes para verificar consistencia
from app.agents.technical_writer import _should_block_by_quality_gate as tw_gate
from app.agents.formats import _should_block_by_quality_gate as fmt_gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obra_triage() -> Dict[str, Any]:
    return {
        "law": "LOPSRM",
        "jurisdiction": "FEDERAL",
        "tender_category": "OBRA",
        "confidence": 0.85,
        "signals_detected": ["Ley de Obras Públicas", "Forma AT-13"],
    }


def _servicios_triage() -> Dict[str, Any]:
    return {
        "law": "LAASSP",
        "jurisdiction": "FEDERAL",
        "tender_category": "BIENES",
        "confidence": 0.9,
        "signals_detected": [],
    }


# ---------------------------------------------------------------------------
# Tarea 6.2: OBRA + generar=0 + presentar_fisico>0 → no bloquea
# ---------------------------------------------------------------------------

class TestObraExceptionTechnicalWriter:
    """Tests del quality gate en TechnicalWriterAgent para categoría OBRA."""

    def test_obra_no_block_when_all_presentar_fisico(self):
        """Req 1.1: OBRA con generar=0 y presentar_fisico>0 no debe bloquear."""
        result = tw_gate(
            total_items=8,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.3,  # Bajo — normalmente bloquearía
            presentar_fisico_count=8,
            triage_context=_obra_triage(),
        )
        assert result["block"] is False
        assert result["reason"] == "obra_category_no_generate_items_expected"
        assert result["metrics"]["tender_category"] == "OBRA"
        assert result["metrics"]["presentar_fisico_count"] == 8

    def test_obra_no_block_empty_list(self):
        """Req 1.2: OBRA con lista vacía no debe bloquear."""
        result = tw_gate(
            total_items=0,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=1.0,
            presentar_fisico_count=0,
            triage_context=_obra_triage(),
        )
        assert result["block"] is False

    def test_obra_applies_normal_thresholds_when_has_generar(self):
        """Req 1.1: OBRA con generar>0 aplica umbrales normales."""
        # evidence_match_ratio bajo → debe bloquear aunque sea OBRA
        result = tw_gate(
            total_items=10,
            generar_count=3,
            unknown_count=0,
            evidence_match_ratio=0.1,  # Muy bajo → bloquea por evidence
            presentar_fisico_count=7,
            triage_context=_obra_triage(),
        )
        assert result["block"] is True
        assert result["reason"] == "evidence_match_ratio_below_threshold"

    def test_obra_applies_normal_thresholds_high_unknown(self):
        """OBRA con generar>0 y unknown_ratio alto → bloquea normalmente."""
        result = tw_gate(
            total_items=10,
            generar_count=2,
            unknown_count=8,  # 80% unknown → supera umbral 60%
            evidence_match_ratio=0.8,
            presentar_fisico_count=0,
            triage_context=_obra_triage(),
        )
        assert result["block"] is True
        assert result["reason"] == "unknown_ratio_above_threshold"


# ---------------------------------------------------------------------------
# Tarea 6.3: OBRA en FormatsAgent — misma lógica
# ---------------------------------------------------------------------------

class TestObraExceptionFormatsAgent:
    """Tests del quality gate en FormatsAgent para categoría OBRA."""

    def test_obra_no_block_when_all_presentar_fisico(self):
        """Req 1.5: FormatsAgent con OBRA + generar=0 + presentar_fisico>0 no bloquea."""
        result = fmt_gate(
            total_items=5,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.2,
            presentar_fisico_count=5,
            triage_context=_obra_triage(),
        )
        assert result["block"] is False
        assert result["reason"] == "obra_category_no_generate_items_expected"

    def test_obra_no_block_empty_list(self):
        """FormatsAgent: OBRA con lista vacía no bloquea."""
        result = fmt_gate(
            total_items=0,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=1.0,
            presentar_fisico_count=0,
            triage_context=_obra_triage(),
        )
        assert result["block"] is False


# ---------------------------------------------------------------------------
# Tarea 6.4: SERVICIOS/BIENES con generar=0 → sí bloquea
# ---------------------------------------------------------------------------

class TestNonObraPreservesOriginalBehavior:
    """Req 4.1: Para categorías no-OBRA, el gate aplica umbrales originales."""

    def test_servicios_blocks_when_no_generar(self):
        """BIENES + generar=0 + presentar_fisico=5 → bloquea (comportamiento original)."""
        result = tw_gate(
            total_items=5,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.8,
            presentar_fisico_count=5,
            triage_context=_servicios_triage(),
        )
        assert result["block"] is True
        assert result["reason"] == "no_actionable_generate_items"

    def test_tecnologia_blocks_when_no_generar(self):
        """TECNOLOGIA + generar=0 → bloquea."""
        result = tw_gate(
            total_items=4,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.9,
            presentar_fisico_count=4,
            triage_context={"tender_category": "TECNOLOGIA"},
        )
        assert result["block"] is True
        assert result["reason"] == "no_actionable_generate_items"

    def test_servicios_blocks_low_evidence(self):
        """BIENES + generar>0 + evidence bajo → bloquea por evidence."""
        result = tw_gate(
            total_items=10,
            generar_count=5,
            unknown_count=0,
            evidence_match_ratio=0.2,  # Bajo
            presentar_fisico_count=5,
            triage_context=_servicios_triage(),
        )
        assert result["block"] is True
        assert result["reason"] == "evidence_match_ratio_below_threshold"

    def test_servicios_blocks_high_unknown(self):
        """BIENES + unknown_ratio alto → bloquea."""
        result = tw_gate(
            total_items=10,
            generar_count=2,
            unknown_count=7,  # 70% > 60% umbral
            evidence_match_ratio=0.8,
            presentar_fisico_count=1,
            triage_context=_servicios_triage(),
        )
        assert result["block"] is True
        assert result["reason"] == "unknown_ratio_above_threshold"

    def test_servicios_passes_good_quality(self):
        """BIENES con buena calidad → no bloquea."""
        result = tw_gate(
            total_items=10,
            generar_count=6,
            unknown_count=1,  # 10% < 60%
            evidence_match_ratio=0.7,  # > 50%
            presentar_fisico_count=3,
            triage_context=_servicios_triage(),
        )
        assert result["block"] is False


# ---------------------------------------------------------------------------
# Tarea 6.5: triage=None → comportamiento original preservado
# ---------------------------------------------------------------------------

class TestNullTriagePreservesOriginalBehavior:
    """Req 4.3: Sin triage_context, el gate aplica umbrales originales."""

    def test_none_triage_blocks_when_no_generar(self):
        """triage=None + generar=0 → bloquea (comportamiento original)."""
        result = tw_gate(
            total_items=5,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.8,
            presentar_fisico_count=5,
            triage_context=None,
        )
        assert result["block"] is True
        assert result["reason"] == "no_actionable_generate_items"

    def test_none_triage_passes_good_quality(self):
        """triage=None con buena calidad → no bloquea."""
        result = tw_gate(
            total_items=8,
            generar_count=5,
            unknown_count=1,
            evidence_match_ratio=0.75,
            presentar_fisico_count=2,
            triage_context=None,
        )
        assert result["block"] is False

    def test_empty_dict_triage_uses_original_thresholds(self):
        """triage={} (sin tender_category) → comportamiento original."""
        result = tw_gate(
            total_items=5,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.8,
            presentar_fisico_count=5,
            triage_context={},
        )
        assert result["block"] is True

    def test_unknown_category_uses_original_thresholds(self):
        """Categoría desconocida → comportamiento original."""
        result = tw_gate(
            total_items=5,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.8,
            presentar_fisico_count=5,
            triage_context={"tender_category": "SALUD"},
        )
        assert result["block"] is True


# ---------------------------------------------------------------------------
# Tarea 6.6: OBRA + lista vacía → no bloquea
# ---------------------------------------------------------------------------

def test_obra_empty_list_no_block():
    """Req 1.2: OBRA con total_items=0 no debe bloquear."""
    result = tw_gate(
        total_items=0,
        generar_count=0,
        unknown_count=0,
        evidence_match_ratio=1.0,
        presentar_fisico_count=0,
        triage_context=_obra_triage(),
    )
    assert result["block"] is False


# ---------------------------------------------------------------------------
# Tarea 6.7: Property test — OBRA nunca bloquea cuando todos son presentar_fisico
# ---------------------------------------------------------------------------

@given(
    presentar_fisico_count=st.integers(min_value=1, max_value=50),
    total_items=st.integers(min_value=1, max_value=50),
    evidence_ratio=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    unknown_count=st.integers(min_value=0, max_value=20),
)
@h_settings(max_examples=200)
def test_obra_never_blocks_when_all_presentar_fisico(
    presentar_fisico_count, total_items, evidence_ratio, unknown_count
):
    """
    Property 1: Para cualquier combinación de parámetros, OBRA con generar=0
    y presentar_fisico>0 nunca debe bloquear la generación.
    """
    result = tw_gate(
        total_items=total_items,
        generar_count=0,
        unknown_count=unknown_count,
        evidence_match_ratio=evidence_ratio,
        presentar_fisico_count=presentar_fisico_count,
        triage_context={"tender_category": "OBRA"},
    )
    assert result["block"] is False, (
        f"OBRA con generar=0 y presentar_fisico={presentar_fisico_count} "
        f"no debe bloquear. Got: {result}"
    )


# ---------------------------------------------------------------------------
# Tarea 6.8: Property test — categorías no-OBRA preservan comportamiento original
# ---------------------------------------------------------------------------

def _gate_original(
    *,
    total_items: int,
    generar_count: int,
    unknown_count: int,
    evidence_match_ratio: float,
) -> Dict[str, Any]:
    """Implementación de referencia del gate original (sin triage_context)."""
    from app.config.settings import settings as app_settings
    if not bool(app_settings.DOCUMENT_QUALITY_HARD_GATE_ENABLED):
        return {"block": False, "reason": "", "metrics": {}}
    min_items = max(1, int(getattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_ITEMS", 3) or 3))
    max_unknown = float(getattr(app_settings, "DOCUMENT_QUALITY_GATE_MAX_UNKNOWN_RATIO", 0.6) or 0.6)
    min_evidence = float(getattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_EVIDENCE_MATCH_RATIO", 0.5) or 0.5)
    if total_items < min_items:
        return {"block": False, "reason": "", "metrics": {}}
    unknown_ratio = (unknown_count / total_items) if total_items else 0.0
    if generar_count == 0:
        return {"block": True, "reason": "no_actionable_generate_items", "metrics": {}}
    if unknown_ratio > max_unknown:
        return {"block": True, "reason": "unknown_ratio_above_threshold", "metrics": {}}
    if evidence_match_ratio < min_evidence:
        return {"block": True, "reason": "evidence_match_ratio_below_threshold", "metrics": {}}
    return {"block": False, "reason": "", "metrics": {}}


@given(
    generar_count=st.integers(min_value=0, max_value=20),
    unknown_count=st.integers(min_value=0, max_value=20),
    presentar_fisico_count=st.integers(min_value=0, max_value=20),
    evidence_ratio=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    category=st.sampled_from(["BIENES", "SERVICIOS", "TECNOLOGIA", "SALUD", None]),
)
@h_settings(max_examples=200)
def test_non_obra_preserves_original_behavior(
    generar_count, unknown_count, presentar_fisico_count, evidence_ratio, category
):
    """
    Property 2: Para categorías no-OBRA (o triage=None), el resultado del gate
    es idéntico al comportamiento original (sin triage_context).
    """
    triage = {"tender_category": category} if category else None
    total = generar_count + unknown_count + presentar_fisico_count

    result_new = tw_gate(
        total_items=total,
        generar_count=generar_count,
        unknown_count=unknown_count,
        evidence_match_ratio=evidence_ratio,
        presentar_fisico_count=presentar_fisico_count,
        triage_context=triage,
    )
    result_original = _gate_original(
        total_items=total,
        generar_count=generar_count,
        unknown_count=unknown_count,
        evidence_match_ratio=evidence_ratio,
    )
    assert result_new["block"] == result_original["block"], (
        f"Para category={category}, el resultado debe ser idéntico al original. "
        f"New: {result_new['block']}, Original: {result_original['block']}, "
        f"generar={generar_count}, unknown={unknown_count}, total={total}, "
        f"evidence={evidence_ratio:.2f}"
    )


# ---------------------------------------------------------------------------
# Consistencia entre TechnicalWriter y FormatsAgent
# ---------------------------------------------------------------------------

class TestGateConsistencyBetweenAgents:
    """Los dos agentes deben tener el mismo comportamiento para OBRA."""

    def test_obra_consistent_between_tw_and_fmt(self):
        """TechnicalWriter y FormatsAgent deben coincidir para OBRA."""
        kwargs = dict(
            total_items=6,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.2,
            presentar_fisico_count=6,
            triage_context=_obra_triage(),
        )
        assert tw_gate(**kwargs)["block"] == fmt_gate(**kwargs)["block"] is False

    def test_servicios_consistent_between_tw_and_fmt(self):
        """TechnicalWriter y FormatsAgent deben coincidir para BIENES."""
        kwargs = dict(
            total_items=6,
            generar_count=0,
            unknown_count=0,
            evidence_match_ratio=0.8,
            presentar_fisico_count=6,
            triage_context=_servicios_triage(),
        )
        assert tw_gate(**kwargs)["block"] == fmt_gate(**kwargs)["block"] is True
