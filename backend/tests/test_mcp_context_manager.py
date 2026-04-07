"""MCPContextManager: política de tasks_completed (singleton por tarea de análisis)."""
from unittest.mock import AsyncMock

import pytest

from app.agents.mcp_context import MCPContextManager


def _memory_with_session(state: dict):
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value=state)
    mem.save_session = AsyncMock(return_value=True)
    return mem


@pytest.mark.asyncio
async def test_record_task_completion_analisis_bases_reemplaza_anteriores():
    prev = {
        "schema_version": 1,
        "tasks_completed": [
            {"task": "analisis_bases", "result": {"cronograma": {"fallo": "viejo"}}},
            {"task": "otra", "result": {}},
        ],
    }
    mem = _memory_with_session(prev)
    ctx = MCPContextManager(mem)

    ok = await ctx.record_task_completion("s1", "analisis_bases", {"cronograma": {"fallo": "nuevo"}})
    assert ok is True
    saved = mem.save_session.await_args[0][1]
    tasks = saved["tasks_completed"]
    assert len(tasks) == 2
    ab = [t for t in tasks if t["task"] == "analisis_bases"]
    assert len(ab) == 1
    assert ab[0]["result"]["cronograma"]["fallo"] == "nuevo"
    assert any(t["task"] == "otra" for t in tasks)


@pytest.mark.asyncio
async def test_record_task_completion_stage_analysis_reemplaza_anteriores():
    prev = {
        "schema_version": 1,
        "tasks_completed": [
            {"task": "stage_completed:analysis", "result": {"status": "success", "data": {"x": 1}}},
            {"task": "stage_completed:analysis", "result": {"status": "success", "data": {"x": 2}}},
        ],
    }
    mem = _memory_with_session(prev)
    ctx = MCPContextManager(mem)

    await ctx.record_task_completion("s2", "stage_completed:analysis", {"status": "success", "data": {"x": 3}})
    saved = mem.save_session.await_args[0][1]
    st = [t for t in saved["tasks_completed"] if t["task"] == "stage_completed:analysis"]
    assert len(st) == 1
    assert st[0]["result"]["data"]["x"] == 3


@pytest.mark.asyncio
async def test_record_task_completion_compliance_no_singleton_acumula():
    prev = {
        "schema_version": 1,
        "tasks_completed": [{"task": "stage_completed:compliance", "result": {"a": 1}}],
    }
    mem = _memory_with_session(prev)
    ctx = MCPContextManager(mem)

    await ctx.record_task_completion("s3", "stage_completed:compliance", {"b": 2})
    saved = mem.save_session.await_args[0][1]
    assert len(saved["tasks_completed"]) == 2
