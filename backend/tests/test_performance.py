from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.compliance import ComplianceAgent


@pytest.mark.regression
def test_adaptive_chunking_reduces_chunk_for_large_context() -> None:
    agent = ComplianceAgent(SimpleNamespace())
    base = 8000
    large = agent._adaptive_chunk_size(250_000, base)
    medium = agent._adaptive_chunk_size(80_000, base)
    assert large < medium <= base
    assert large >= 2200


@pytest.mark.regression
def test_adaptive_chunking_respects_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPLIANCE_ADAPTIVE_CHUNKING", "true")
    monkeypatch.setenv("COMPLIANCE_CHUNK_MIN", "3000")
    monkeypatch.setenv("COMPLIANCE_CHUNK_MAX", "8000")
    agent = ComplianceAgent(SimpleNamespace())

    for context_len in (10_000, 60_000, 140_000, 260_000):
        chunk = agent._adaptive_chunk_size(context_len, 8000)
        assert 3000 <= chunk <= 8000
