"""Tests HRU OfficialFormatResolver — Fase 0 modo estricto."""
from app.services.official_format_resolver import (
    build_official_miss_shell,
    corpus_has_format_anchors,
    is_llm_blocked_obra_annex,
    load_official_format_policy,
    official_mirror_strict_enabled,
    should_use_miss_shell_instead_of_generic,
)
from app.services.obra_economic_annex_clauses import (
    build_obra_e3e_utilidad_markdown,
    extract_obra_e3e_official_format,
    fill_obra_e3e_official_format,
    is_official_obra_e3e_mirror_content,
)


def test_policy_loads():
    pol = load_official_format_policy()
    assert pol.get("policy_version")
    assert "obra|E1" in (pol.get("annexes") or {})


def test_llm_blocked_obra_annex_when_strict():
    assert official_mirror_strict_enabled() is True
    assert is_llm_blocked_obra_annex("obra|E1") is True
    assert is_llm_blocked_obra_annex("obra|T6") is True
    assert is_llm_blocked_obra_annex("pliego|ANEXO_VI") is False


def test_corpus_anchors_e1():
    corpus = (
        "ANEXO E-1 (FORMATO) CARTA COMPROMISO DE PROPOSICION "
        "HACEMOS REFERENCIA AL PROCEDIMIENTO DE ADJUDICACION PRESENTE"
    )
    assert corpus_has_format_anchors(corpus, "obra|E1") is True
    assert should_use_miss_shell_instead_of_generic(corpus, "obra|E1") is True


def test_miss_shell_not_generic_letter():
    body = build_official_miss_shell(
        "obra|E1",
        concurso="Licitación D/080/2025",
        req_line="Carta-compromiso en papel membretado.",
        master_profile={"razon_social": "DEMO SA"},
    )
    assert "[Consignar]" in body
    assert "formato oficial" in body.lower()
    assert "1. Presentamos" not in body


_E3E_TEMPLATE = """
ANEXO E-3 E
LA UTILIDAD PROPUESTA PARA EL CONCURSO No:______________ RELACIONADO CON LA OBRA:________________________ ES DEL _______% LA CUAL EN CUMPLIMIENTO A LOS ESTABLECIDO EN EL ART. 63 FRACCIÓN IV DE LA LEY DE OBRA PÚBLICA
________________________
FIRMA
"""


def test_obra_e3e_extract_and_fill():
    extracted = extract_obra_e3e_official_format(_E3E_TEMPLATE)
    assert extracted
    body = fill_obra_e3e_official_format(
        extracted,
        concurso="D/080/2025",
        corpus=_E3E_TEMPLATE,
        obra_descripcion="CONSTRUCCION DE BARDA",
        master_profile={"representante_legal": "Juan Pérez"},
        utilidad_rate=0.05,
    )
    assert is_official_obra_e3e_mirror_content(body)
    assert "5.00%" in body or "5%" in body
    assert "D/080/2025" in body
    assert "BARDA" in body.upper()


def test_obra_e3e_build_from_embedded_template():
    body = build_obra_e3e_utilidad_markdown(
        concurso="Licitación Pública Num. D/080/2025",
        master_profile={"representante_legal": "Ana López"},
        utilidad_rate=0.08,
        req_snippet=_E3E_TEMPLATE,
        obra_descripcion="OBRA DEMO",
    )
    assert is_official_obra_e3e_mirror_content(body)
    assert "8.00%" in body or "8%" in body
