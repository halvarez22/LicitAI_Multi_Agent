"""SubmissionChecklist: mapeo de cronograma, merge y API de persistencia (memoria mock)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.checklist.hito_scheduler import (
    aplicar_estados_vencido,
    build_hitos_from_cronograma,
    calcular_porcentaje,
    merge_hitos_preservar_completados,
    parse_fecha_hito,
)
from app.checklist.models import MarkHitoPayload
from app.checklist.submission_checklist_service import (
    ensure_session_cronograma_and_checklist,
    get_submission_checklist,
    mark_hito,
    upsert_checklist_from_cronograma,
)


def test_parse_fecha_hito_basico():
    assert parse_fecha_hito("11/01/2024 11:00 hrs") == datetime(2024, 1, 11, 11, 0, 0)
    assert parse_fecha_hito("No especificado") is None


def test_build_hitos_incluye_seis_claves_canonicas():
    cron = {
        "visita_instalaciones": "11/01/2024 11:00",
        "junta_aclaraciones": "12/01/2024 12:00",
    }
    hitos = build_hitos_from_cronograma(cron)
    ids = [h["id"] for h in hitos]
    assert len(hitos) == 6
    assert "visita_instalaciones" in ids
    assert "junta_aclaraciones" in ids


def test_merge_preserva_completado():
    nuevos = build_hitos_from_cronograma({"visita_instalaciones": "15/02/2025 10:00"})
    prev = [
        {
            "id": "visita_instalaciones",
            "nombre": "Visita",
            "fecha_texto_raw": "viejo",
            "fecha_hora": None,
            "obligatorio": True,
            "estado": "completado",
            "evidencia": "c.pdf",
            "notificado": False,
        }
    ]
    merged = merge_hitos_preservar_completados(nuevos, prev)
    vis = next(h for h in merged if h["id"] == "visita_instalaciones")
    assert vis["estado"] == "completado"
    assert vis["evidencia"] == "c.pdf"
    assert "2025" in vis["fecha_texto_raw"] or "15/02" in vis["fecha_texto_raw"]


def test_aplicar_vencido():
    past = datetime.utcnow() - timedelta(days=1)
    hitos = [
        {
            "id": "x",
            "estado": "pendiente",
            "fecha_hora": past,
        }
    ]
    aplicar_estados_vencido(hitos, ahora=datetime.utcnow())
    assert hitos[0]["estado"] == "vencido"


def test_calcular_porcentaje():
    hitos = [
        {"estado": "completado"},
        {"estado": "pendiente"},
    ]
    assert calcular_porcentaje(hitos) == 50.0


@pytest.mark.asyncio
async def test_upsert_y_mark_hito():
    store: dict = {}

    class Mem:
        def __init__(self):
            self.get_session = AsyncMock(side_effect=lambda sid: store.get(sid))
            self.save_session = AsyncMock(side_effect=lambda sid, data: store.update({sid: data}) or True)

    mem = Mem()
    sid = "sess_chk"
    await mem.save_session(sid, {"name": "Licitación demo"})

    await upsert_checklist_from_cronograma(
        mem,
        sid,
        {"presentacion_proposiciones": "22/12/2099 11:00"},
        merge=False,
    )
    assert "submission_checklist" in store[sid]
    assert len(store[sid]["submission_checklist"]["hitos"]) == 6

    updated = await mark_hito(
        mem,
        sid,
        "presentacion_proposiciones",
        MarkHitoPayload(estado="completado", evidencia="acuse.pdf"),
    )
    assert updated is not None
    assert updated.porcentaje_completado > 0
    h = next(x for x in updated.hitos if x.id == "presentacion_proposiciones")
    assert h.estado == "completado"
    assert h.evidencia == "acuse.pdf"

    undone = await mark_hito(
        mem,
        sid,
        "presentacion_proposiciones",
        MarkHitoPayload(estado="pendiente"),
    )
    assert undone is not None
    h2 = next(x for x in undone.hitos if x.id == "presentacion_proposiciones")
    assert h2.estado == "pendiente"
    assert h2.evidencia is None


@pytest.mark.asyncio
async def test_ensure_checklist_sin_cronograma_analysis_no_recursion():
    """Checklist persistido sin cronograma en stage_completed:analysis no debe reentrar infinitamente."""
    store: dict = {}

    class Mem:
        def __init__(self):
            self.get_session = AsyncMock(side_effect=lambda sid: store.get(sid))
            self.save_session = AsyncMock(side_effect=lambda sid, data: store.update({sid: data}) or True)
            self.get_documents = AsyncMock(return_value=[])

    mem = Mem()
    sid = "sess_no_cron_recursion"
    await mem.save_session(
        sid,
        {
            "name": "Demo",
            "tasks_completed": [
                {
                    "task": "stage_completed:analysis",
                    "result": {"data": {"cronograma": None}},
                }
            ],
            "submission_checklist": {
                "licitation_id": "Demo",
                "hitos": [
                    {
                        "id": "junta_aclaraciones",
                        "nombre": "Junta de aclaraciones",
                        "fecha_texto_raw": "No especificado",
                        "fecha_hora": None,
                        "obligatorio": True,
                        "estado": "pendiente",
                        "evidencia": None,
                        "notificado": False,
                    }
                ],
                "ultima_actualizacion": "2026-01-01T00:00:00",
                "porcentaje_completado": 0.0,
            },
        },
    )

    model = await ensure_session_cronograma_and_checklist(mem, sid)
    assert model is not None
    assert len(model.hitos) == 1

    again = await get_submission_checklist(mem, sid, auto_sync=False)
    assert again is not None
    assert len(again.hitos) == 1


@pytest.mark.asyncio
async def test_checklist_ready_without_enrichment():
    from app.checklist.submission_checklist_service import checklist_ready_without_enrichment

    session = {
        "submission_checklist": {
            "hitos": [
                {
                    "id": "junta_aclaraciones",
                    "fecha_texto_raw": "12 de enero de 2026 10:00 hrs",
                }
            ]
        }
    }
    assert checklist_ready_without_enrichment(session) is True
    session_bad = {
        "submission_checklist": {
            "hitos": [
                {"id": "a", "fecha_texto_raw": "No especificado"},
                {"id": "b", "fecha_texto_raw": "No especificado"},
            ]
        }
    }
    assert checklist_ready_without_enrichment(session_bad) is False


@pytest.mark.asyncio
async def test_cronograma_enrichment_timeout_returns_cached_checklist(monkeypatch):
    """Si RAG excede el tope, devolver checklist cacheado sin bloquear el worker."""
    import asyncio

    store: dict = {}

    class Mem:
        def __init__(self):
            self.get_session = AsyncMock(side_effect=lambda sid: store.get(sid))
            self.save_session = AsyncMock(side_effect=lambda sid, data: store.update({sid: data}) or True)
            self.get_documents = AsyncMock(return_value=[])

    mem = Mem()
    sid = "sess_timeout"
    cron = {
        "publicacion_convocatoria": "No especificado",
        "visita_instalaciones": "No especificado",
        "junta_aclaraciones": "No especificado",
        "presentacion_proposiciones": "No especificado",
        "fallo": "No especificado",
        "firma_contrato": "No especificado",
    }
    await mem.save_session(
        sid,
        {
            "name": "Timeout demo",
            "tasks_completed": [
                {
                    "task": "stage_completed:analysis",
                    "result": {"data": {"cronograma": cron}},
                }
            ],
            "submission_checklist": {
                "licitation_id": "Timeout demo",
                "hitos": [
                    {
                        "id": "junta_aclaraciones",
                        "nombre": "Junta",
                        "fecha_texto_raw": "15 de marzo de 2026",
                        "fecha_hora": None,
                        "obligatorio": True,
                        "estado": "pendiente",
                        "evidencia": None,
                        "notificado": False,
                    }
                ],
                "ultima_actualizacion": "2026-01-01T00:00:00",
                "porcentaje_completado": 0.0,
            },
        },
    )

    async def slow_rag(*args, **kwargs):
        await asyncio.sleep(60)
        return cron

    monkeypatch.setattr(
        "app.services.cronograma_enrichment_service.enrich_cronograma_from_rag",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("sync path")),
    )

    async def slow_thread(fn, *args, **kwargs):
        await asyncio.sleep(60)
        return cron

    monkeypatch.setattr(asyncio, "to_thread", slow_thread)
    monkeypatch.setattr(
        "app.config.settings.settings.CRONOGRAMA_ENRICHMENT_TIMEOUT_S",
        0.05,
    )

    model = await ensure_session_cronograma_and_checklist(mem, sid)
    assert model is not None
    assert len(model.hitos) == 1
    assert model.hitos[0].fecha_texto_raw == "15 de marzo de 2026"
