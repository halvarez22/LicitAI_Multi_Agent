from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.post_clarification.acta_extractor_service import ActaExtractionResult
from app.post_clarification.models import TipoJunta
from app.post_clarification.service import (
    generate_carta_33_bis,
    get_post_clarification_context,
    process_acta_document,
)


@pytest.mark.asyncio
async def test_process_acta_document_happy_path(monkeypatch):
    store = {
        "s1": {"name": "Licitación Test"},
        "doc1": {
            "id": "doc1",
            "content": {"filename": "acta_junta.pdf", "file_path": "/tmp/acta.pdf"},
            "metadata": {},
        },
    }

    class Mem:
        async def get_document(self, did):
            return store.get(did)

        async def get_session(self, sid):
            return store.get(sid)

        async def save_session(self, sid, data):
            store[sid] = data
            return True

    async def _extract_acta_text(**kwargs):
        return ActaExtractionResult(
            text="Acta de junta con aclaraciones técnicas y legales.",
            confidence=0.88,
            method="digital",
            needs_fallback_template=False,
        )

    async def _questions(*args, **kwargs):
        return [{"tipo": "tecnica", "pregunta": "¿Se confirma el alcance?"}]

    async def _carta(*args, **kwargs):
        return "Carta 33 bis de prueba."

    monkeypatch.setattr(
        "app.post_clarification.service.extract_acta_text", _extract_acta_text
    )
    monkeypatch.setattr(
        "app.post_clarification.service.build_questions_anexo10_from_text", _questions
    )
    monkeypatch.setattr(
        "app.post_clarification.service.build_carta_33_bis_text", _carta
    )
    monkeypatch.setattr(
        "app.post_clarification.service.write_carta_docx", lambda p, t: p
    )

    out = await process_acta_document(
        Mem(), "s1", "doc1", tipo_junta=TipoJunta.PRIMERA, correlation_id="x"
    )
    assert out.estado == "borrador_listo"
    assert out.confianza_extraccion == 0.88
    assert out.carta_33_bis_draft == "Carta 33 bis de prueba."
    assert len(out.preguntas_aclaracion) == 1
    assert "post_clarification_context" in store["s1"]


@pytest.mark.asyncio
async def test_process_acta_document_fallback_low_confidence(monkeypatch):
    store = {
        "s2": {"name": "Licitación Test 2"},
        "doc2": {
            "id": "doc2",
            "content": {"filename": "archivo.pdf", "file_path": "/tmp/acta.pdf"},
            "metadata": {},
        },
    }

    class Mem:
        async def get_document(self, did):
            return store.get(did)

        async def get_session(self, sid):
            return store.get(sid)

        async def save_session(self, sid, data):
            store[sid] = data
            return True

    async def _extract_acta_text(**kwargs):
        return ActaExtractionResult(
            text="texto corto",
            confidence=0.55,
            method="vision",
            needs_fallback_template=True,
        )

    monkeypatch.setattr(
        "app.post_clarification.service.extract_acta_text", _extract_acta_text
    )
    monkeypatch.setattr(
        "app.post_clarification.service.write_carta_docx", lambda p, t: p
    )

    out = await process_acta_document(
        Mem(), "s2", "doc2", tipo_junta=TipoJunta.SEGUNDA, correlation_id="y"
    )
    assert out.estado == "extraida"
    assert out.confianza_extraccion < 0.7
    assert "Fallback" in (out.carta_33_bis_draft or "")


@pytest.mark.asyncio
async def test_generate_and_get_context(monkeypatch):
    store = {
        "s3": {
            "name": "Licitación Test 3",
            "post_clarification_context": {
                "acta_id": "d3",
                "tipo_junta": "primera",
                "archivo_original": "acta.pdf",
                "texto_extraido": "contenido",
                "confianza_extraccion": 0.8,
                "preguntas_aclaracion": [],
                "carta_33_bis_draft": None,
                "estado": "extraida",
            },
        }
    }

    class Mem:
        async def get_document(self, did):
            return None

        async def get_session(self, sid):
            return store.get(sid)

        async def save_session(self, sid, data):
            store[sid] = data
            return True

    async def _carta(*args, **kwargs):
        return "Carta regenerada"

    monkeypatch.setattr(
        "app.post_clarification.service.build_carta_33_bis_text", _carta
    )
    monkeypatch.setattr(
        "app.post_clarification.service.write_carta_docx", lambda p, t: p
    )

    updated = await generate_carta_33_bis(Mem(), "s3", force_regenerate=True)
    assert updated.carta_33_bis_draft == "Carta regenerada"
    ctx = await get_post_clarification_context(Mem(), "s3")
    assert ctx is not None
    assert ctx.acta_id == "d3"
