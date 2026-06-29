"""Tests fail-closed: página verificada vs alucinación semántica."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.forensic_risk_evidence_service import (
    _best_vector_hit,
    verify_forensic_risk_evidence,
)

LITERAL = "El presupuesto debe ser de $1,000,000.00 o más"
PAGE30_TEXT = (
    "El licitante deberá presentar propuesta económica no menor a $1,000,000.00 MXN "
    "conforme al anexo técnico."
)
PAGE1_TEXT = "Convocatoria pública nacional — índice general del pliego."


def test_best_vector_hit_does_not_assign_page_without_literal_match():
    vdb = MagicMock()
    vdb.query_texts_filtered.return_value = {
        "documents": [[PAGE1_TEXT]],
        "metadatas": [[{"page": 1, "source": "bases.pdf"}]],
        "distances": [[0.05]],
    }
    hit = _best_vector_hit(vdb, "sess", LITERAL, source_filter="bases.pdf")
    assert hit.get("page") is None
    assert hit.get("match_confidence") == "media"


def test_verify_drops_unverified_page_and_finds_correct_one():
    vdb = MagicMock()
    vdb.get_sources.return_value = ["bases.pdf"]

    def _fetch(session_id, source, page):
        if str(page) in ("30", "30"):
            return [PAGE30_TEXT]
        return [PAGE1_TEXT]

    vdb.fetch_page_documents.side_effect = _fetch
    vdb.get_full_pages.return_value = ""
    vdb.query_texts.return_value = {
        "documents": [[PAGE30_TEXT]],
        "metadatas": [[{"page": 30, "source": "bases.pdf"}]],
        "distances": [[0.2]],
    }
    vdb.query_texts_filtered.return_value = vdb.query_texts.return_value

    raw = {"page": 1, "snippet": PAGE1_TEXT, "source": "bases.pdf", "match_confidence": "media"}
    verified = verify_forensic_risk_evidence(vdb, "sess", LITERAL, raw)
    assert verified.get("page") == 30
    assert "$1,000,000.00" in str(verified.get("snippet") or "")


def test_amount_match_across_mexican_formats():
    literal = "El presupuesto debe ser de $1,000,000.00 o más"
    doc = "propuesta económica no menor a $1,000,000 M.N."
    from app.services.forensic_risk_evidence_service import _literal_matches_doc

    assert _literal_matches_doc(literal, doc) is True


def test_verify_without_index_keeps_no_page():
    vdb = MagicMock()
    vdb.get_sources.return_value = []
    vdb.fetch_page_documents.return_value = []
    vdb.query_texts.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    verified = verify_forensic_risk_evidence(
        vdb,
        "sess",
        LITERAL,
        {"page": 1, "snippet": LITERAL},
    )
    assert verified.get("page") is None
