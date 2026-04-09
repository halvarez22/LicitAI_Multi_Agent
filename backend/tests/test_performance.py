from __future__ import annotations

import asyncio
import time
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
@pytest.mark.asyncio
async def test_chunk_cache_improves_second_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLIANCE_CHUNK_CACHE_ENABLED", "true")
    monkeypatch.setenv("COMPLIANCE_CHUNK_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("COMPLIANCE_MAX_CONCURRENT_CHUNKS", "1")
    monkeypatch.setenv("COMPLIANCE_BLOCK_EXTRA_RETRIES", "0")
    monkeypatch.setenv("COMPLIANCE_BLOCK_RETRY_DELAY_SEC", "0")

    agent = ComplianceAgent(SimpleNamespace())

    async def fake_extract(*_args, **_kwargs):
        await asyncio.sleep(0.02)
        return ([{"nombre": "x", "descripcion": "y", "snippet": "z", "categoria_orig": "tecnico"}], None, False)

    monkeypatch.setattr(agent, "_extract_zone_chunk", fake_extract)

    chunks = ["abc " * 3000, "def " * 2800]
    t0 = time.perf_counter()
    items_1, _events_1 = await agent._map_zone_chunks("TÉCNICO/OPERATIVO", chunks, 150)
    t1 = time.perf_counter()
    items_2, _events_2 = await agent._map_zone_chunks("TÉCNICO/OPERATIVO", chunks, 150)
    t2 = time.perf_counter()

    first_ms = (t1 - t0) * 1000
    second_ms = (t2 - t1) * 1000
    assert len(items_1) == len(items_2) == 2
    assert second_ms < first_ms * 0.6
