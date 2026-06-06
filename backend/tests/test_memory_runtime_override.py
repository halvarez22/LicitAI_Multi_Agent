"""Tests del override de memoria por contexto (jobs aislados)."""
from unittest.mock import MagicMock

import pytest

from app.memory.factory import MemoryAdapterFactory
from app.memory.runtime import reset_memory_override, set_memory_override


@pytest.fixture(autouse=True)
def _clear_factory_singleton():
    MemoryAdapterFactory.reset_instance()
    yield
    MemoryAdapterFactory.reset_instance()


def test_create_adapter_prefers_context_override():
    sentinel = MagicMock(name="job_thread_adapter")
    token = set_memory_override(sentinel)
    try:
        assert MemoryAdapterFactory.create_adapter() is sentinel
    finally:
        reset_memory_override(token)


def test_create_adapter_without_override_uses_singleton():
    first = MagicMock(name="main_adapter")
    MemoryAdapterFactory._instance = first
    assert MemoryAdapterFactory.create_adapter() is first
