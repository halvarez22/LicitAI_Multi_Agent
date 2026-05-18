"""
Test suite for enhanced_consolidator module.

Validates:
- Requirements 14.1, 14.2, 14.3 (checklist ordering)
- Requirements 18.1, 18.2, 18.3, 18.4 (checklist structure)
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.agents.enhanced_consolidator import (
    consolidate_checklist,
    _sort_requirements,
    _get_classification_priority,
    _get_category_priority,
)
from app.agents.enhanced_models import (
    SolvenciaTecnica,
    CondicionesContractuales,
    RequisitoChecklist,
    Categoria,
    Subcategoria,
    Clasificacion,
    ExperienciaMinima,
    GarantiaCumplimiento,
    CurriculumEmpresa,
    TipoContrato,
    Penalizaciones,
    PenalizacionAtraso,
    Pagos,
    Anticipo,
    Estimaciones,
    GarantiaViciosOcultos,
    Referencias
)


# ---------------------------------------------------------------------------
# Property-Based Tests con Hypothesis
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["obligatorio", "deseable", "condicional"]),
            st.sampled_from([
                Subcategoria.GARANTÍAS,
                Subcategoria.EXPERIENCIA,
                Subcategoria.PERSONAL,
                Subcategoria.EQUIPAMIENTO,
                Subcategoria.TIPO_CONTRATO,
                Subcategoria.PENALIZACIONES,
                Subcategoria.PAGOS
            ])
        ),
        min_size=1,
        max_size=20
    )
)
def test_property_17_checklist_ordering_by_classification(req_data) -> None:
    """Property 17: Checklist ordering by classification.
    
    Validates: Requirements 14.1, 14.2
    """
    reqs = []
    for i, (clas, cat) in enumerate(req_data):
        req = RequisitoChecklist(
            id=f"req_{i:03d}",
            categoría=Categoria.SOLVENCIA_TÉCNICA,
            subcategoria=cat,
            descripción="test",
            clasificación=Clasificacion(clas),
            página="1",
            cláusula="1",
            orden_entrega=0,
            clasificación_incierta=False
        )
        reqs.append(req)
        
    sorted_reqs = _sort_requirements(reqs)
    
    assert [r.orden_entrega for r in sorted_reqs] == list(range(1, len(reqs) + 1))
    
    for i in range(len(sorted_reqs) - 1):
        r1 = sorted_reqs[i]
        r2 = sorted_reqs[i+1]
        
        prio1 = _get_classification_priority(r1.clasificación.value)
        prio2 = _get_classification_priority(r2.clasificación.value)
        
        cat_prio1 = _get_category_priority(r1.subcategoria.value)
        cat_prio2 = _get_category_priority(r2.subcategoria.value)
        
        assert prio1 <= prio2
        if prio1 == prio2:
            assert cat_prio1 <= cat_prio2


@settings(max_examples=50)
@given(
    anios_exp=st.text(min_size=1, max_size=5),
    monto_garantia=st.text(min_size=1, max_size=5)
)
def test_property_21_consolidated_checklist_structure(anios_exp: str, monto_garantia: str) -> None:
    """Property 21: Consolidated checklist structure and ordering.
    
    Validates: Requirements 18.1, 18.2, 18.3, 18.4
    """
    solvencia = SolvenciaTecnica(
        experiencia_mínima=ExperienciaMinima(años_experiencia=anios_exp, monto_minimo="No especificado", numero_contratos="No especificado", unidad_monetaria="No especificado", confianza=1.0, fuente=""),
        curriculum=CurriculumEmpresa(empresa_requerido=False, descripcion="No especificado", personal_clave=[]),
        plantilla_personal=[],
        equipamiento=[],
        infraestructura=[],
        normas_certificaciones=[],
        referencias=Referencias(contratos_minimos="No especificado", antigüedad_maxima_meses="No especificado", cartas_referencia_aceptadas=False, requisitos_adicionales="No especificado")
    )
    
    condiciones = CondicionesContractuales(
        tipo_contrato=TipoContrato(tipo="No especificado", modalidad="No especificado", fuente="explícito"),
        penalizaciones=Penalizaciones(atraso=PenalizacionAtraso(porcentaje="No especificado", período="No especificado"), deducciones=[], limite_maximo="No especificado", condiciones_aplicación="No especificado"),
        pagos=Pagos(anticipo=Anticipo(porcentaje="No especificado", garantia_porcentaje="No especificado"), estimaciones=Estimaciones(periodicidad="No especificado", proceso_aprobación="No especificado"), retenciones_finiquito="No especificado"),
        garantía_cumplimiento=GarantiaCumplimiento(monto_porcentaje=monto_garantia, tipo="No especificado", plazo_presentación="No especificado", vigencia_meses="No especificado"),
        garantía_vicios_ocultos=GarantiaViciosOcultos(monto_porcentaje="No especificado", tipo="No especificado", periodo_meses="No especificado")
    )
    
    consolidated = consolidate_checklist(solvencia, condiciones)
    
    assert len(consolidated) >= 2
    
    for req in consolidated:
        assert isinstance(req, RequisitoChecklist)
        assert req.orden_entrega > 0
        assert req.id.startswith("req_")


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestConsolidateChecklist:
    def test_consolidate_checklist_flow(self):
        solvencia = SolvenciaTecnica(
            experiencia_mínima=ExperienciaMinima(años_experiencia="10", monto_minimo="No especificado", numero_contratos="No especificado", unidad_monetaria="No especificado", confianza=1.0, fuente=""),
            curriculum=CurriculumEmpresa(empresa_requerido=False, descripcion="No especificado", personal_clave=[]),
            plantilla_personal=[],
            equipamiento=[],
            infraestructura=[],
            normas_certificaciones=[],
            referencias=Referencias(contratos_minimos="No especificado", antigüedad_maxima_meses="No especificado", cartas_referencia_aceptadas=False, requisitos_adicionales="No especificado")
        )
        
        condiciones = CondicionesContractuales(
            tipo_contrato=TipoContrato(tipo="No especificado", modalidad="No especificado", fuente="explícito"),
            penalizaciones=Penalizaciones(atraso=PenalizacionAtraso(porcentaje="No especificado", período="No especificado"), deducciones=[], limite_maximo="No especificado", condiciones_aplicación="No especificado"),
            pagos=Pagos(anticipo=Anticipo(porcentaje="No especificado", garantia_porcentaje="No especificado"), estimaciones=Estimaciones(periodicidad="No especificado", proceso_aprobación="No especificado"), retenciones_finiquito="No especificado"),
            garantía_cumplimiento=GarantiaCumplimiento(monto_porcentaje="5%", tipo="No especificado", plazo_presentación="No especificado", vigencia_meses="No especificado"),
            garantía_vicios_ocultos=GarantiaViciosOcultos(monto_porcentaje="No especificado", tipo="No especificado", periodo_meses="No especificado")
        )
        
        reqs = consolidate_checklist(solvencia, condiciones)
        
        assert len(reqs) == 2
        
        assert reqs[0].subcategoria == Subcategoria.GARANTÍAS
        assert reqs[0].orden_entrega == 1
        
        assert reqs[1].subcategoria == Subcategoria.EXPERIENCIA
        assert reqs[1].orden_entrega == 2
