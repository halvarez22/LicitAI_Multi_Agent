"""Tests HRU solvencia obra (capital contable / liquidez)."""
from app.services.obra_solvency_annex_clauses import (
    build_obra_tb_solvencia_markdown,
    is_official_obra_tb_solvencia_mirror_content,
    resolve_solvency_figures,
)


def test_resolve_solvency_figures_from_profile():
    fig = resolve_solvency_figures(
        master_profile={
            "capital_contable": "2_500_000",
            "contratos_obra": [
                {
                    "importe": "4_000_000",
                    "avance_financiero": "50",
                }
            ],
        },
        session_state={},
        corpus="capital contable comprometido veinticinco por ciento",
    )
    assert fig.capital_contable == 2_500_000.0
    assert fig.obras_pendientes == 2_000_000.0
    assert fig.capital_comprometido == 500_000.0
    assert "capital_contable" in fig.provenance


def test_resolve_solvency_no_invented_amounts():
    fig = resolve_solvency_figures(master_profile={}, session_state={}, corpus="")
    assert fig.capital_contable is None
    assert "capital_contable" in fig.slots_pending


def test_build_solvency_markdown_uses_consignar_without_data():
    body = build_obra_tb_solvencia_markdown(
        concurso="D/080/2025",
        master_profile={"razon_social": "DEMO SA"},
        session_state={},
        req_snippet="capital contable comprometido y liquidez mínima",
    )
    assert "Consignar" in body
    assert "OPM/MUN" not in body
    assert "Documentos físicos" in body


def test_build_solvency_with_user_inputs():
    body = build_obra_tb_solvencia_markdown(
        concurso="D/080/2025",
        master_profile={"razon_social": "DEMO SA"},
        session_state={
            "economic_user_inputs": {
                "capital_contable": 3000000,
                "liquidez": 800000,
            }
        },
        req_snippet="solvencia economica capital contable liquidez",
    )
    assert "$3,000,000.00" in body
    assert "$800,000.00" in body
    assert "user_economic_inputs" in body or "Procedencia" in body


def test_mirror_detector_rejects_contaminated_llm():
    bad = (
        "CONVOCATORIA PÚBLICA NACIONAL No. OPM/MUN/37/2025 capital contable "
        "liquidez bajo protesta"
    )
    assert is_official_obra_tb_solvencia_mirror_content(bad) is False


def test_mirror_detector_accepts_deterministic_body():
    good = (
        "**CAPITAL CONTABLE COMPROMETIDO**\n"
        "Bajo protesta de decir verdad capital contable liquidez anexo t-2"
    )
    assert is_official_obra_tb_solvencia_mirror_content(good) is True


def test_policy_loads_tb_solvencia():
    from app.services.official_format_resolver import policy_annex_entry

    entry = policy_annex_entry("obra|T_B_SOLVENCIA")
    assert entry is not None
    assert "CAPITAL CONTABLE" in str(entry.get("anchors"))


def test_clause_builder_registers_tb_solvencia():
    from app.services.administrative_letter_clauses import try_build_clause_markdown

    body = try_build_clause_markdown(
        req_label="Capital contable comprometido",
        master_profile={"razon_social": "DEMO SA", "rfc": "X"},
        doc_metadata={
            "session_id": "test",
            "session_state": {},
            "concurso_label": "D/080/2025",
            "req_snippet": "capital contable liquidez",
        },
        req_snippet="capital contable liquidez comprometida",
    )
    assert body
    assert "capital contable" in body.lower()
