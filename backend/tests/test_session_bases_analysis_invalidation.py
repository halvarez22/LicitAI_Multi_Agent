"""Tests de invalidación universal al cambiar bases."""
from __future__ import annotations

import pytest

from app.services.session_bases_analysis_invalidation import (
    apply_analysis_invalidation,
    bases_fingerprint_matches_stored,
    collect_bases_documents,
    commit_bases_analysis_snapshot,
    compute_bases_fingerprint,
    is_bases_pliego_document,
    should_hard_reset_session_artifacts,
    should_invalidate_analysis_artifacts,
    strip_analysis_artifacts,
    bases_analysis_committed,
)


def _bases_doc(doc_id: str = "d1", *, text_len: int = 12000, filename: str = "BASES CONVOCATORIA.pdf") -> dict:
    return {
        "id": doc_id,
        "content": {
            "filename": filename,
            "status": "ANALYZED",
            "extracted_text": "x" * text_len,
            "file_path": f"/data/uploads/{doc_id}_{filename.replace(' ', '_').lower()}",
        },
    }


def test_is_bases_pliego_by_catalog_role() -> None:
    state = {
        "document_catalog": {
            "items": [{"doc_id": "abc", "role": "tender_bases"}],
        }
    }
    assert is_bases_pliego_document({"id": "abc", "content": {"filename": "x.pdf"}}, state)


def test_fingerprint_changes_when_doc_changes() -> None:
    d1 = _bases_doc("a", text_len=1000)
    d2 = _bases_doc("b", text_len=1000)
    fp1 = compute_bases_fingerprint([d1], {})
    fp2 = compute_bases_fingerprint([d2], {})
    assert fp1 != fp2


def test_should_invalidate_when_artifacts_and_fingerprint_differs() -> None:
    docs = [_bases_doc()]
    state = {
        "compliance_master_list": {"administrativo": [{"x": 1}]},
        "bases_analysis_snapshot": {"fingerprint": "old_fingerprint_not_matching_anything"},
        "tasks_completed": [{"task": "stage_completed:analysis", "result": {}}],
    }
    assert should_invalidate_analysis_artifacts(state, docs) is True


def test_no_invalidate_when_fingerprint_matches() -> None:
    docs = [_bases_doc()]
    fp = compute_bases_fingerprint(docs, {})
    state = {
        "compliance_master_list": {"administrativo": [{"x": 1}]},
        "bases_analysis_snapshot": {"fingerprint": fp},
    }
    assert should_invalidate_analysis_artifacts(state, docs) is False
    assert bases_fingerprint_matches_stored(state, docs) is True


def test_strip_analysis_artifacts_preserves_economic_hitl() -> None:
    """Invalidación de bases no debe borrar capturas económicas ni generación."""
    state = {
        "compliance_master_list": {"administrativo": [1]},
        "economic_user_inputs": {"price_te_1": 100.0},
        "generation_state": {"status": "running", "jobs": []},
        "tasks_completed": [{"task": "stage_completed:analysis", "result": {}}],
    }
    cleaned, audit = strip_analysis_artifacts(state)
    assert cleaned.get("economic_user_inputs") == {"price_te_1": 100.0}
    assert cleaned.get("generation_state", {}).get("status") == "running"
    assert "economic_user_inputs" not in audit["keys_cleared"]
    assert "generation_state" not in audit["keys_cleared"]


def test_should_hard_reset_only_when_bases_changed() -> None:
    docs = [_bases_doc()]
    fp = compute_bases_fingerprint(docs, {})
    state = {
        "bases_analysis_snapshot": {"fingerprint": fp, "pending_reanalysis": False},
        "economic_user_inputs": {"price_x": 1.0},
    }
    assert should_hard_reset_session_artifacts(
        mode="full",
        resume_generation=False,
        session_state=state,
        documents=docs,
    ) is False
    assert should_hard_reset_session_artifacts(
        mode="analysis_only",
        resume_generation=False,
        session_state=state,
        documents=docs,
    ) is False
    assert should_hard_reset_session_artifacts(
        mode="full",
        resume_generation=False,
        session_state={"bases_analysis_snapshot": {"fingerprint": "stale"}},
        documents=docs,
    ) is True


def test_strip_analysis_artifacts_removes_tasks_and_keys() -> None:
    state = {
        "compliance_master_list": {"administrativo": [1]},
        "go_no_go_result": {"semaforo": "verde"},
        "tasks_completed": [
            {"task": "stage_completed:analysis", "result": {}},
            {"task": "stage_completed:economic", "result": {}},
        ],
    }
    cleaned, audit = strip_analysis_artifacts(state)
    assert "compliance_master_list" not in cleaned
    assert "go_no_go_result" not in cleaned
    tasks = [t["task"] for t in cleaned["tasks_completed"]]
    assert "stage_completed:analysis" not in tasks
    assert "stage_completed:economic" in tasks
    assert "stage_completed:analysis" in audit["tasks_removed"]


def test_apply_analysis_invalidation_sets_pending() -> None:
    docs = [_bases_doc()]
    state = {"compliance_master_list": {"administrativo": [1]}}
    cleaned, audit = apply_analysis_invalidation(state, docs, reason="test")
    assert audit["invalidated"] is True
    snap = cleaned["bases_analysis_snapshot"]
    assert snap["pending_reanalysis"] is True
    assert snap["fingerprint"] == compute_bases_fingerprint(docs, {})


def test_commit_snapshot_clears_pending() -> None:
    docs = [_bases_doc()]
    state = {"bases_analysis_snapshot": {"pending_reanalysis": True}}
    snap = commit_bases_analysis_snapshot(state, docs)
    assert snap["pending_reanalysis"] is False
    assert snap["fingerprint"] == compute_bases_fingerprint(docs, {})


def test_bases_analysis_committed_requires_not_pending() -> None:
    assert not bases_analysis_committed(
        {"bases_analysis_snapshot": {"fingerprint": "abc", "pending_reanalysis": True}}
    )
    assert bases_analysis_committed(
        {"bases_analysis_snapshot": {"fingerprint": "abc", "pending_reanalysis": False}}
    )


def test_collect_bases_prefers_catalog_tag() -> None:
    state = {
        "document_catalog": {
            "items": [{"doc_id": "b1", "role": "tender_bases"}],
        }
    }
    docs = [
        _bases_doc("b1", text_len=5000),
        _bases_doc("other", text_len=90000, filename="otro.pdf"),
    ]
    picked = collect_bases_documents(docs, state)
    assert len(picked) == 1
    assert picked[0]["id"] == "b1"
