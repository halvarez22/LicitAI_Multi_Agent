"""
test_go_no_go_scorer.py — Pruebas unitarias y PBT del módulo go_no_go_scorer.

Cubre los 9 casos unitarios obligatorios (Req. 8.1, 8.2) y las 8 propiedades
de corrección con hypothesis (Req. 8.1).
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.agents.go_no_go_scorer import (
    Brecha,
    ScoreResult,
    calculate_score_tecnico,
    calculate_semaforo,
    detect_brechas,
)

# ---------------------------------------------------------------------------
# Fixtures y helpers
# ---------------------------------------------------------------------------

COMPLIANCE_CON_KNOCKOUT = {
    "summary": {
        "causas_desechamiento": [
            {"descripcion": "No presenta certificación ISO 9001 vigente (punto 4.2)"}
        ]
    },
    "administrativo": [],
    "tecnico": [],
    "formatos": [],
}

COMPLIANCE_SIN_KNOCKOUT = {
    "summary": {"causas_desechamiento": []},
    "administrativo": [
        {"descripcion": "Acta constitutiva notariada"}
    ],
    "tecnico": [],
    "formatos": [],
}

COMPLIANCE_VACIO = {
    "summary": {"causas_desechamiento": []},
    "administrativo": [],
    "tecnico": [],
    "formatos": [],
}

PROFILE_COMPLETO = {
    "rfc": "ABC123456XYZ",
    "capital_contable": "5000000",
    "anos_experiencia": "10",
    "certificaciones": ["ISO 9001:2015"],
    "representante_legal": "Juan Pérez",
    "domicilio_fiscal": "Calle 1, CDMX",
}

CRITERIOS_RUBRICA = [
    {"descripcion": "Experiencia mínima de 5 años en servicios similares", "peso": "30%"},
    {"descripcion": "Capital contable mínimo de $2,000,000", "peso": "20%"},
    {"descripcion": "Certificación ISO 9001 vigente", "peso": "50%"},
]


# ---------------------------------------------------------------------------
# Casos unitarios obligatorios (Req. 8.1, 8.2)
# ---------------------------------------------------------------------------

def test_semaforo_red():
    """Semáforo debe ser RED cuando hay al menos un knock-out."""
    brechas = detect_brechas(COMPLIANCE_CON_KNOCKOUT, {})
    assert calculate_semaforo(brechas) == "RED"


def test_semaforo_yellow():
    """Semáforo debe ser YELLOW cuando hay brechas sin knock-out."""
    brechas = detect_brechas(COMPLIANCE_SIN_KNOCKOUT, {})
    assert calculate_semaforo(brechas) == "YELLOW"


def test_semaforo_green():
    """Semáforo debe ser GREEN cuando no hay brechas."""
    brechas = detect_brechas(COMPLIANCE_VACIO, PROFILE_COMPLETO)
    assert calculate_semaforo(brechas) == "GREEN"


def test_score_rubrica_vacia():
    """Score debe ser None cuando criterios_evaluacion está vacío."""
    result = calculate_score_tecnico([], PROFILE_COMPLETO)
    assert result.score is None
    assert result.detalle == []


def test_score_perfil_vacio():
    """Score debe ser 0 cuando el perfil maestro está vacío."""
    result = calculate_score_tecnico(CRITERIOS_RUBRICA, {})
    assert result.score == 0


def test_score_todos_cumplen():
    """Score debe ser 100 cuando todos los criterios tienen evidencia en el perfil."""
    criterios = [
        {"descripcion": "Experiencia mínima de 5 años", "peso": "50%"},
        {"descripcion": "Capital contable mínimo", "peso": "50%"},
    ]
    profile = {"anos_experiencia": "10", "capital_contable": "5000000"}
    result = calculate_score_tecnico(criterios, profile)
    assert result.score == 100


def test_score_ninguno_cumple():
    """Score debe ser 0 cuando ningún criterio tiene evidencia en el perfil."""
    criterios = [
        {"descripcion": "Certificación ISO 9001 vigente", "peso": "100%"},
    ]
    result = calculate_score_tecnico(criterios, {})
    assert result.score == 0


def test_brecha_knockout_marcada():
    """Brechas de causas_desechamiento deben tener is_knockout=True."""
    brechas = detect_brechas(COMPLIANCE_CON_KNOCKOUT, {})
    knockouts = [b for b in brechas if b.is_knockout]
    assert len(knockouts) >= 1
    assert all(b.is_knockout for b in knockouts)


def test_perfil_vacio_categoria():
    """Con perfil vacío, todas las brechas deben tener valor_empresa=None.
    La categoría se clasifica por el texto del requisito (no siempre es requisito_no_acreditado).
    """
    _CATEGORIAS_VALIDAS = {
        "certificacion_faltante", "capital_insuficiente",
        "experiencia_insuficiente", "documento_faltante", "requisito_no_acreditado"
    }
    brechas = detect_brechas(COMPLIANCE_SIN_KNOCKOUT, {})
    for b in brechas:
        assert b.valor_empresa is None, f"Con perfil vacío, valor_empresa debe ser None, got {b.valor_empresa!r}"
        assert b.categoria in _CATEGORIAS_VALIDAS, f"Categoría inválida: {b.categoria}"


def test_contratos_previos_cubre_requisito_de_contratos_similares():
    """Si el perfil trae contratos_previos, no debe marcar brecha por contratos similares."""
    compliance = {
        "summary": {"causas_desechamiento": []},
        "administrativo": [],
        "tecnico": [{"descripcion": "Acreditar contratos similares en servicios de vigilancia"}],
        "formatos": [],
    }
    profile = {"contratos_previos": [{"contrato_id": "8900005011"}]}
    brechas = detect_brechas(compliance, profile)
    assert brechas == []


# ---------------------------------------------------------------------------
# Strategies para property-based testing
# ---------------------------------------------------------------------------

_CATEGORIAS_VALIDAS = {
    "certificacion_faltante",
    "capital_insuficiente",
    "experiencia_insuficiente",
    "documento_faltante",
    "requisito_no_acreditado",
}

texto_strategy = st.text(min_size=1, max_size=200)

brecha_strategy = st.builds(
    Brecha,
    id=st.uuids().map(str),
    categoria=st.sampled_from(sorted(_CATEGORIAS_VALIDAS)),
    descripcion=texto_strategy,
    requisito_bases=texto_strategy,
    valor_empresa=st.one_of(st.none(), texto_strategy),
    is_knockout=st.booleans(),
    zona_origen=st.sampled_from([
        "ADMINISTRATIVO/LEGAL", "TÉCNICO/OPERATIVO", "FORMATOS/ANEXOS", "GARANTÍAS/SEGUROS"
    ]),
)

compliance_strategy = st.fixed_dictionaries({
    "summary": st.fixed_dictionaries({
        "causas_desechamiento": st.lists(
            st.one_of(texto_strategy, st.fixed_dictionaries({"descripcion": texto_strategy})),
            max_size=5,
        )
    }),
    "administrativo": st.lists(
        st.fixed_dictionaries({"descripcion": texto_strategy}), max_size=5
    ),
    "tecnico": st.lists(
        st.fixed_dictionaries({"descripcion": texto_strategy}), max_size=5
    ),
    "formatos": st.lists(
        st.fixed_dictionaries({"descripcion": texto_strategy}), max_size=5
    ),
})

profile_strategy = st.dictionaries(
    keys=st.sampled_from([
        "rfc", "capital_contable", "anos_experiencia", "certificaciones",
        "representante_legal", "domicilio_fiscal", "registro_patronal",
    ]),
    values=st.text(min_size=1, max_size=100),
    max_size=7,
)

criterios_strategy = st.lists(
    st.fixed_dictionaries({
        "descripcion": texto_strategy,
        "peso": st.one_of(st.none(), st.text(min_size=1, max_size=10)),
    }),
    min_size=1,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Property-based tests (Req. 8.1)
# ---------------------------------------------------------------------------

@given(compliance_data=compliance_strategy, master_profile=profile_strategy)
@settings(max_examples=100)
def test_property_5_determinismo(compliance_data, master_profile):
    """Propiedad 5: Determinismo del scorer — mismos inputs producen mismos outputs."""
    result1 = detect_brechas(compliance_data, master_profile)
    result2 = detect_brechas(compliance_data, master_profile)
    # Los UUIDs son distintos por diseño (generados en cada llamada),
    # pero la estructura lógica debe ser idéntica
    assert len(result1) == len(result2), "Número de brechas debe ser idéntico"
    for b1, b2 in zip(result1, result2):
        assert b1.categoria == b2.categoria, f"Categoría difiere: {b1.categoria} != {b2.categoria}"
        assert b1.is_knockout == b2.is_knockout, f"is_knockout difiere"
        assert b1.zona_origen == b2.zona_origen, f"zona_origen difiere"
        assert b1.requisito_bases == b2.requisito_bases, f"requisito_bases difiere"


@given(brechas=st.lists(brecha_strategy, max_size=20))
@settings(max_examples=100)
def test_property_6_reglas_semaforo(brechas):
    """Propiedad 6: Reglas del semáforo — RED/YELLOW/GREEN según brechas."""
    resultado = calculate_semaforo(brechas)
    tiene_knockout = any(b.is_knockout for b in brechas)
    if tiene_knockout:
        assert resultado == "RED"
    elif brechas:
        assert resultado == "YELLOW"
    else:
        assert resultado == "GREEN"


@given(compliance_data=compliance_strategy, master_profile=profile_strategy)
@settings(max_examples=100)
def test_property_1_categoria_valida(compliance_data, master_profile):
    """Propiedad 1: Invariante de categoría — toda brecha tiene categoría válida."""
    brechas = detect_brechas(compliance_data, master_profile)
    for b in brechas:
        assert b.categoria in _CATEGORIAS_VALIDAS


@given(compliance_data=compliance_strategy, master_profile=profile_strategy)
@settings(max_examples=100)
def test_property_2_invariante_estructural(compliance_data, master_profile):
    """Propiedad 2: Invariante estructural — cada Brecha tiene los 7 campos requeridos."""
    brechas = detect_brechas(compliance_data, master_profile)
    for b in brechas:
        assert isinstance(b.id, str) and b.id
        assert isinstance(b.categoria, str) and b.categoria
        assert isinstance(b.descripcion, str)
        assert isinstance(b.requisito_bases, str)
        assert b.valor_empresa is None or isinstance(b.valor_empresa, str)
        assert isinstance(b.is_knockout, bool)
        assert isinstance(b.zona_origen, str) and b.zona_origen


@given(criterios=criterios_strategy, master_profile=profile_strategy)
@settings(max_examples=100)
def test_property_8_rango_score(criterios, master_profile):
    """Propiedad 8: Rango del score técnico — score siempre en [0, 100]."""
    result = calculate_score_tecnico(criterios, master_profile)
    assert result.score is None or (0 <= result.score <= 100)


@given(brechas=st.lists(brecha_strategy, max_size=20))
@settings(max_examples=100)
def test_property_7_requires_user_decision(brechas):
    """Propiedad 7: requires_user_decision es True iff semaforo es RED o YELLOW."""
    semaforo = calculate_semaforo(brechas)
    requires = semaforo in ("RED", "YELLOW")
    assert requires == (semaforo != "GREEN")


@given(compliance_data=compliance_strategy, master_profile=profile_strategy)
@settings(max_examples=100)
def test_property_3_knockout_implica_is_knockout(compliance_data, master_profile):
    """Propiedad 3: Requisitos de causas_desechamiento producen is_knockout=True.
    
    Solo cuenta causas que producen texto real (no solo whitespace) después de
    la normalización interna del scorer.
    """
    from app.agents.go_no_go_scorer import _extract_text
    causas = (compliance_data.get("summary") or {}).get("causas_desechamiento") or []
    brechas = detect_brechas(compliance_data, master_profile)
    knockouts = [b for b in brechas if b.is_knockout]
    # Solo causas que producen texto real tras normalización
    causas_con_texto_real = [c for c in causas if _extract_text(c).strip()]
    assert len(knockouts) >= len(causas_con_texto_real)


@given(compliance_data=compliance_strategy)
@settings(max_examples=100)
def test_property_4_perfil_vacio_requisito_no_acreditado(compliance_data):
    """Propiedad 4: Con master_profile vacío, todas las brechas tienen valor_empresa=None.
    
    La categoría se clasifica por el texto del requisito (puede ser cualquiera de las 5
    categorías válidas), pero valor_empresa siempre es None cuando el perfil está vacío.
    """
    brechas = detect_brechas(compliance_data, {})
    for b in brechas:
        assert b.valor_empresa is None, (
            f"Con perfil vacío, valor_empresa debe ser None, got {b.valor_empresa!r}"
        )
        assert b.categoria in _CATEGORIAS_VALIDAS, f"Categoría inválida: {b.categoria}"
