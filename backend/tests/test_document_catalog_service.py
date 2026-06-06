"""Tests para Document Catalog Service."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contracts.document_catalog import DocumentCatalogRole, DocumentCatalogUseCase
from app.services.document_catalog_service import (
    build_session_document_catalog,
    classify_document_entry,
    classify_and_persist_catalog_entry,
    experience_client_refs_from_catalog,
    get_entries_by_use_case,
)


def test_classify_experience_pdf():
    entry = classify_document_entry(
        "doc-1",
        {
            "filename": "experiencia_previa.pdf",
            "status": "ANALYZED",
            "extracted_text": (
                "Constancia de contrato número ABC-123 para servicio de limpieza "
                "para las Unidades de este Organismo Demo, con domicilio en Calle Falsa 123 "
                "C.P. 64000. Tel. 8181234567."
            ),
            "total_pages": 8,
        },
    )
    assert entry.doc_role == DocumentCatalogRole.COMPANY_EXPERIENCE
    assert DocumentCatalogUseCase.FILL_TE03_CLIENTS in entry.use_cases
    assert entry.entities.get("client_ref_count", 0) >= 1
    assert entry.provenance_ui.get("badge") == "company_experience"


def test_classify_bases_pdf():
    entry = classify_document_entry(
        "doc-2",
        {
            "filename": "Bases_Licitacion_2024.pdf",
            "status": "ANALYZED",
            "extracted_text": "Convocatoria pública nacional...",
        },
    )
    assert entry.doc_role in (
        DocumentCatalogRole.TENDER_BASES,
        DocumentCatalogRole.TENDER_ANNEX,
        DocumentCatalogRole.SUPPORTING,
    )
    assert DocumentCatalogUseCase.INDEX_FOR_RAG in entry.use_cases


def test_classify_fiscal_by_content():
    entry = classify_document_entry(
        "doc-3",
        {
            "filename": "anexo_sat.pdf",
            "status": "ANALYZED",
            "extracted_text": "Opinión del cumplimiento de obligaciones fiscales positiva.",
        },
    )
    assert entry.doc_role == DocumentCatalogRole.COMPANY_FISCAL
    assert DocumentCatalogUseCase.PRESENT_PHYSICAL in entry.use_cases


def test_build_session_catalog_and_query():
    docs = [
        {
            "id": "d1",
            "content": {
                "filename": "referencias_clientes.pdf",
                "status": "ANALYZED",
                "extracted_text": (
                    "Contrato número XYZ-99 para las Unidades de Cliente Demo."
                ),
            },
        },
        {
            "id": "d2",
            "content": {
                "filename": "bases_convocatoria.pdf",
                "status": "ANALYZED",
                "extracted_text": "Bases de la licitación pública.",
            },
        },
    ]
    catalog = build_session_document_catalog("sess-x", docs)
    assert catalog.stats.total_entries == 2
    assert catalog.stats.experience_client_refs >= 1

    session_state = {"document_catalog": catalog.model_dump(mode="json")}
    exp = get_entries_by_use_case(session_state, DocumentCatalogUseCase.FILL_TE03_CLIENTS.value)
    assert len(exp) >= 1
    refs = experience_client_refs_from_catalog(session_state)
    assert refs


@pytest.mark.asyncio
async def test_classify_and_persist_merges_session():
    memory = MagicMock()
    memory.get_session = AsyncMock(return_value={"name": "Test"})
    memory.save_session = AsyncMock(return_value=True)

    content = {
        "filename": "curriculum_empresa.pdf",
        "status": "ANALYZED",
        "extracted_text": "Trayectoria de la empresa con contrato número C-001.",
    }
    result = await classify_and_persist_catalog_entry(memory, "sess-1", "doc-a", content)
    assert result["doc_role"] == "company_experience"
    memory.save_session.assert_called_once()
    saved = memory.save_session.call_args[0][1]
    assert "document_catalog" in saved
    assert "doc-a" in saved["document_catalog"]["entries"]
