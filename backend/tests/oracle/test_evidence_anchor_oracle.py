"""Oracle F12.1: calidad de anclas evidence_anchor_v1 (fail-closed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.evidence_anchor_service import (
    claim_quality_for_ux,
    format_claim_locus,
    is_claim_locus_visible,
    normalize_evidence_anchor,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "evidence_anchor" / "oracle_cases.json"


@pytest.mark.parametrize(
    "case",
    json.loads(_FIXTURE.read_text(encoding="utf-8")),
    ids=lambda c: c["case_id"],
)
def test_evidence_anchor_oracle(case):
    anchor = normalize_evidence_anchor(case.get("raw") or {}, claim_id=case["case_id"])
    assert anchor.get("schema_version", "").startswith("evidence-anchor-v1")
    assert anchor.get("anchor_quality") == case["expect_quality"]
    assert is_claim_locus_visible(anchor) is bool(case.get("expect_visible"))
    if case.get("expect_ux_quality"):
        assert claim_quality_for_ux(anchor) == case["expect_ux_quality"]
    locus = format_claim_locus(anchor).lower()
    for token in case.get("expect_locus_contains") or []:
        assert token.lower() in locus, f"{case['case_id']}: missing {token} in {locus!r}"
    if case["expect_quality"] == "synthetic":
        assert "p. 1" not in locus
        assert not is_claim_locus_visible(anchor)
