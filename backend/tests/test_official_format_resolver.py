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
        master_profile={"representante_legal": "Ana López", "razon_social": "DEMO SA"},
        utilidad_rate=0.08,
        req_snippet=_E3E_TEMPLATE,
        obra_descripcion="OBRA DEMO",
    )
    assert is_official_obra_e3e_mirror_content(body)
    assert "8.00%" in body or "8%" in body


def test_session_slug_not_used_as_concurso_or_obra():
    from app.services.obra_economic_annex_clauses import (
        looks_like_session_slug,
        resolve_obra_concurso_label,
        resolve_obra_objeto,
    )

    sid = "barda_primaria_lopez_rayon"
    assert looks_like_session_slug("BARDA PRIMARIA LOPEZ RAYON", sid)
    label = resolve_obra_concurso_label(
        session_state={},
        session_id=sid,
        corpus="LICITACIÓN PÚBLICA NUM. D/080/2025 CONSTRUCCIÓN DE BARDA",
    )
    assert "D/080/2025" in label
    obra = resolve_obra_objeto(
        session_state={"name": "barda_primaria_lopez_rayon"},
        session_id=sid,
        corpus="ADJUDICAR EL CONTRATO RELATIVO A LA REALIZACIÓN DE LA OBRA: CONSTRUCCIÓN DE BARDA PERIMETRAL",
    )
    assert "BARDA PERIMETRAL" in obra.upper()
    assert "LOPEZ RAYON" not in obra.upper()


def test_extract_licitacion_rejects_consignar_placeholder():
    from app.services.obra_economic_annex_clauses import _extract_licitacion_numero

    num = _extract_licitacion_numero(
        "[Consignar — número de licitación]",
        "",
        session_id="barda_primaria_lopez_rayon",
    )
    assert num == "[Consignar]"


def test_e3e_fill_strips_session_slug_when_corpus_has_d080():
    body = fill_obra_e3e_official_format(
        _E3E_TEMPLATE.replace("_______________", "BARDA PRIMARIA LOPEZ RAYON"),
        concurso="BARDA PRIMARIA LOPEZ RAYON",
        corpus="LICITACIÓN PÚBLICA NUM. D/080/2025 " + _E3E_TEMPLATE,
        obra_descripcion="CONSTRUCCIÓN DE BARDA PERIMETRAL",
        master_profile={
            "razon_social": "CONSTRUCTORA DEMO SA",
            "representante_legal": "Juan Pérez",
        },
        utilidad_rate=0.0,
        session_id="barda_primaria_lopez_rayon",
    )
    up = body.upper()
    assert "D/080/2025" in up
    assert "BARDA PRIMARIA LOPEZ RAYON" not in up
    assert "Consignar" in body or "[CONSIGNAR" in up


def test_e3e_fill_repairs_prefilled_consignar_placeholders():
    bad = (
        "ANEXO E-3 E\n"
        "LA UTILIDAD PROPUESTA PARA EL CONCURSO No:[Consignar — número de licitación]\n"
        "RELACIONADO CON LA OBRA:[CONSIGNAR — OBJETO DE LA OBRA EN BASES]  ES DEL 5.00%\n"
        "LA CUAL EN CUMPLIMIENTO A LOS ESTABLECIDO EN EL ART. 63 FRACCIÓN IV FIRMA"
    )
    corpus = (
        "LICITACIÓN PÚBLICA NUM. D/080/2025 "
        "ADJUDICAR EL CONTRATO RELATIVO A LA REALIZACIÓN DE LA OBRA: "
        "CONSTRUCCIÓN DE BARDA PERIMETRAL EN PRIMARIA LÓPEZ RAYÓN"
    )
    body = fill_obra_e3e_official_format(
        bad,
        concurso="[Consignar — número de licitación]",
        corpus=corpus,
        obra_descripcion="",
        master_profile={
            "razon_social": "CONSTRUCTORA DEMO SA",
            "representante_legal": "Juan Pérez",
        },
        utilidad_rate=0.0,
        session_id="barda_primaria_lopez_rayon",
        session_state={"session_hint": "D/080/2025"},
    )
    up = body.upper()
    assert "D/080/2025" in up
    assert "BARDA PERIMETRAL" in up
    assert "5.00%" not in body
    assert "Consignar" in body


def test_e3e_utilidad_requires_user_confirmation():
    from app.services.official_format_resolver import resolve_e3e_utilidad_rate_for_fill

    assert (
        resolve_e3e_utilidad_rate_for_fill(
            {},
            {"utilidad_rate": 0.05},
            {"utilidad_rate": 0.05},
        )
        == 0.0
    )
    assert (
        resolve_e3e_utilidad_rate_for_fill(
            {"economic_user_inputs": {"utilidad_rate": 0.08}},
            {"utilidad_rate": 0.05},
            {},
        )
        == 0.08
    )
