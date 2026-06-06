import unicodedata

from app.services.document_deliverable_filter import (
    enforce_deterministic_tipo_accion,
    filter_compliance_for_generation,
    filter_compliance_master_list,
    filter_consolidated_document_candidates,
    is_company_credential_present_only,
    is_pliego_causal_or_prohibition,
    should_show_deliverable_in_ui,
)
from app.services.document_candidate_list_service import build_candidate_document_list


def test_is_pliego_causal_no_presentar_engrapado():
    assert is_pliego_causal_or_prohibition(
        "No presentar documentación engrapada o dentro de micas transparentes ni con broches"
    )
    assert is_pliego_causal_or_prohibition(
        "Datos contradictorios en la propuesta técnica y económica"
    )
    assert not is_pliego_causal_or_prohibition(
        "Carta de declaración de integridad", "Formato Anexo M"
    )


def test_build_candidate_list_excludes_causales_and_dedup():
    compliance = {
        "administrativo": [
            {
                "id": "AD-1",
                "nombre": "Acta constitutiva emitida por fedatario público",
                "descripcion": "Documento legal",
                "snippet": "Acta constitutiva",
                "tipo_accion": "presentar_fisico",
                "action_confidence": 0.9,
            },
            {
                "id": "AD-2",
                "nombre": "Acta constitutiva emitida por fedatario público o autoridad competente",
                "descripcion": "Duplicado",
                "snippet": "Acta constitutiva",
                "tipo_accion": "presentar_fisico",
                "action_confidence": 0.8,
            },
            {
                "id": "AD-146",
                "nombre": "No presentar documentación engrapada o dentro de micas transparentes",
                "descripcion": "Causal",
                "snippet": "No presentar documentación engrapada",
                "tipo_accion": "generar",
                "action_confidence": 0.95,
            },
        ],
        "tecnico": [],
        "formatos": [],
    }
    out = build_candidate_document_list(compliance, require_human_confirmation=False)
    names = [d["nombre"] for d in out["candidate_document_list"]]
    assert len(names) == 1, names
    assert "Acta constitutiva" in names[0]
    assert not any("engrapada" in n for n in names)


def test_should_show_rejects_causa_and_accepts_anexo_m():
    assert not should_show_deliverable_in_ui("Causa 1: No suministrar los bienes")
    assert not should_show_deliverable_in_ui("No presentar documentación engrapada")
    assert should_show_deliverable_in_ui("Anexo M Carta de Declaración de Integridad")
    assert should_show_deliverable_in_ui("Características de Muestras")
    assert should_show_deliverable_in_ui(
        "Opinión del Cumplimiento de Obligaciones Fiscales expedida por el SAT",
        tipo_accion="presentar_fisico",
    )


def test_classify_acta_and_opinion_go_legal_not_economic():
    from app.services.compliance_consolidation_service import classify_deliverable_sobre

    assert classify_deliverable_sobre("Acta constitutiva notariada e inscrita") == "requisitos_legales"
    assert (
        classify_deliverable_sobre(
            "Opinión del Cumplimiento de Obligaciones Fiscales expedida por el SAT"
        )
        == "requisitos_legales"
    )
    assert classify_deliverable_sobre("Análisis de precios unitarios") == "sobre_2_economico"


def test_filter_consolidated_dedupes_acta_and_curriculum():
    raw = {
        "sobre_2_economico": [
            {"nombre_canonico": "Acta constitutiva em", "snippet_representativo": "x"},
            {
                "nombre_canonico": "Acta constitutiva emitida por fedatario público",
                "snippet_representativo": "x",
            },
        ],
        "sobre_1_tecnico": [
            {"nombre_canonico": "Curriculum Original", "snippet_representativo": "x"},
            {"nombre_canonico": "Curriculum de la empresa", "snippet_representativo": "x"},
        ],
        "requisitos_legales": [],
        "otros_requisitos_criticos": [],
        "_meta": {},
    }
    out = filter_consolidated_document_candidates(raw)
    assert len(out["requisitos_legales"]) == 1
    assert "acta" in out["requisitos_legales"][0]["nombre_canonico"].lower()
    assert len(out["sobre_1_tecnico"]) == 1


def test_filter_consolidated_strips_noise():
    raw = {
        "sobre_1_tecnico": [
            {"nombre_canonico": "Causa 1: No suministrar", "snippet_representativo": "x"},
            {"nombre_canonico": "Anexo M Carta de Declaración de Integridad", "snippet_representativo": "x"},
            {"nombre_canonico": "Junta de aclaraciones", "snippet_representativo": "x"},
        ],
        "sobre_2_economico": [],
        "requisitos_legales": [
            {"nombre_canonico": "Constancia de situación fiscal", "snippet_representativo": "x"},
        ],
        "otros_requisitos_criticos": [],
        "_meta": {"total_consolidados": 4},
    }
    out = filter_consolidated_document_candidates(raw)
    assert len(out["sobre_1_tecnico"]) == 1
    assert "Anexo M" in out["sobre_1_tecnico"][0]["nombre_canonico"]
    assert len(out["requisitos_legales"]) == 1
    assert out["_meta"]["total_consolidados"] == 2


def test_filter_compliance_master_list():
    raw = {
        "administrativo": [
            {"nombre": "Opinión SAT", "tipo_accion": "presentar_fisico"},
            {"nombre": "No presentar muestras requeridas", "tipo_accion": "generar"},
        ],
        "tecnico": [],
        "formatos": [],
    }
    filtered = filter_compliance_master_list(raw)
    assert len(filtered["administrativo"]) == 1
    assert filtered["administrativo"][0]["nombre"] == "Opinión SAT"


def test_filter_compliance_for_generation_excludes_fisico_and_causales():
    raw = {
        "administrativo": [
            {
                "nombre": "Acta constitutiva",
                "descripcion": "Legal",
                "snippet": "Acta constitutiva",
                "tipo_accion": "presentar_fisico",
            },
            {
                "nombre": "Carta de declaración de integridad",
                "descripcion": "Formato",
                "snippet": "Carta bajo protesta",
                "tipo_accion": "generar",
            },
            {
                "nombre": "No presentar documentación engrapada",
                "descripcion": "Causal",
                "snippet": "No presentar",
                "tipo_accion": "generar",
            },
            {
                "nombre": "Propuesta económica en sobre cerrado",
                "descripcion": "Econ",
                "snippet": "propuesta economica",
                "tipo_accion": "generar",
            },
        ],
        "tecnico": [
            {
                "nombre": "Propuesta técnica describiendo especificaciones",
                "descripcion": "Tec",
                "snippet": "propuesta tecnica",
                "tipo_accion": "generar",
            },
            {
                "nombre": "Propuesta técnica describiendo especificaciones del servicio",
                "descripcion": "Dup",
                "snippet": "propuesta tecnica",
                "tipo_accion": "generar",
            },
        ],
        "formatos": [],
    }
    out = filter_compliance_for_generation(raw)
    admin_names = [x["nombre"] for x in out["administrativo"]]
    assert len(admin_names) == 1
    assert "integridad" in admin_names[0].lower()
    assert len(out["tecnico"]) == 1
    assert out.get("_generation_filter_meta", {}).get("output_generable") == 2


def test_company_credential_blocks_generation_not_convocante_letters():
    assert is_company_credential_present_only("Constancia de situación fiscal SAT")
    assert is_company_credential_present_only("Constancia IMSS de cumplimiento")
    assert is_company_credential_present_only("Identificación oficial vigente INE")
    assert not is_company_credential_present_only(
        "Carta de declaración de integridad", "Formato Anexo M"
    )


def test_formats_panel_tipo_upgrades_economic_and_excludes_procedural():
    from app.services.document_candidate_list_service import _formats_panel_tipo_for_item

    assert _formats_panel_tipo_for_item(
        {"nombre_canonico": "Catálogo de conceptos con cantidades y precios unitarios", "tipo": "informativo"}
    ) == "generar"
    assert _formats_panel_tipo_for_item(
        {
            "nombre_canonico": "Carta compromiso de seriedad de su proposición",
            "tipo": "informativo",
        }
    ) == "generar"
    assert _formats_panel_tipo_for_item(
        {
            "nombre_canonico": "8.2. Carta compromiso de seriedad (Forma AE-01)",
            "tipo": "informativo",
        }
    ) == "generar"
    assert _formats_panel_tipo_for_item(
        {
            "nombre_canonico": "Presentar documentos de la propuesta económica dentro del sobre de la propuesta técnica.",
            "tipo": "informativo",
        }
    ) is None
    assert _formats_panel_tipo_for_item(
        {
            "nombre_canonico": "Escrito de solicitud de inscripción, revalidación, modificación o reexpedición",
            "tipo": "informativo",
        }
    ) is None


def test_opm_pliego_section_extracts_dd_and_propuesta_items():
    from app.services.junta_bases_corpus import BasesCorpus
    from app.services.pliego_formats_enrichment_service import (
        extract_pliego_generables_from_bases_corpus,
    )

    snippet = """
5.1.- Forma DD-01 Escrito mediante el cual el licitante manifiesta facultades.

5.2.- Forma DD-02 Declaración de Integridad

8.3 Proposición económica (Documento que afecta la solvencia de la propuesta).

8.11 Relación y análisis de los costos del suministro de luminarias

6.5. Constancia positiva vigente de Opinión de Cumplimiento SAT
"""
    corpus = BasesCorpus(session_id="s_pliego", segments=[("Bases.pdf", snippet)])
    rows = extract_pliego_generables_from_bases_corpus(corpus)
    names = " ".join(r["nombre_canonico"].lower() for r in rows)
    assert "dd-01" in names or "dd 01" in names.replace(" ", "")
    assert "integridad" in names
    assert "proposici" in names and "econ" in names
    assert "costos" in names or "luminarias" in names
    assert "sat" not in names or "dd" in names


def test_issste_lettered_block_extracts_identidad_and_imss():
    from app.services.corporate_physical_enrichment_service import (
        extract_corporate_physical_from_bases_corpus,
    )
    from app.services.junta_bases_corpus import BasesCorpus

    snippet = """
b) Carta en papel, preferentemente membretado, Bajo Protesta de Decir Verdad, mediante
la cual los participantes acrediten su personalidad jurídica, Anexo No. 7 de estas bases.
c) Identificación oficial vigente de quien firma las proposiciones, (Pasaporte, Cedula
Profesional, Credencial para Votar con Fotografía), y acta constitutiva de la empresa y
sus modificaciones.
d) Escrito Bajo Protesta de Decir Verdad de no encontrarse en los supuestos del artículo
50 y 60 penúltimo párrafo de la Ley, conforme al Anexo No. 15 de estas Bases.
i)
Cédula de determinación de cuotas obrero-patronales del SUA y comprobante de pago,
así como opinión del cumplimiento de obligaciones en materia de seguridad social.
j)
Presentar el formato de Opinión del SAT, respecto al Artículo 32 del Código Fiscal.
q) Carta bajo protesta de decir verdad que, en caso de resultar ganador de la presente
licitación, deberá presentar al Instituto póliza de responsabilidad civil por $1,000,000.00.
u) Presentar las CUIPS del 100% del personal solicitado en esta licitación.
v) Otro requisito posterior no administrativo.
"""
    corpus = BasesCorpus(session_id="s_issste", segments=[("Bases.pdf", snippet)])
    rows = extract_corporate_physical_from_bases_corpus(corpus)
    names = " ".join(r["nombre"].lower() for r in rows)
    assert "identificaci" in names
    assert "acta constitutiva" in names or "acta" in names
    assert "imss" in names or "obrero" in names or "seguridad social" in names
    assert "formato de opini" not in names
    assert "cuips" not in names
    assert "resultar ganador" not in names


def test_opm_sat_line_with_solvency_parenthetical_not_causal():
    """6.5 OPM: «de no presentar este documento» es nota de solvencia, no causal de desechamiento."""
    from app.services.document_deliverable_filter import (
        is_bases_admin_physical_credential_line,
        is_pliego_causal_or_prohibition,
    )

    line = (
        '6.5. Constancia positiva vigente de "Opinión de Cumplimiento de Obligaciones '
        "Fiscales Federales\" expedida por el Servicio de Administración Tributaria, "
        "de acuerdo con lo establecido en el artículo 32-D del Código Fiscal de la Federación, "
        "salvo que se encuentren garantizados en alguna de las formas permitidas por el mismo, "
        "adjuntando el documento que así lo acredite (De no presentar este documento afecta "
        "la solvencia de la propuesta; más sin embargo también deberá presentarla a la firma "
        "del contrato, vigente y positiva)."
    )
    assert not is_pliego_causal_or_prohibition(line, "", line)
    assert is_bases_admin_physical_credential_line(line)


UNAQ_DOCNO_SNIPPET = """
Documento No. 2  Para acreditar su personalidad el concursante deberá presentar:
A) Personas morales: del acta constitutiva de la empresa;
original para cotejo y copia simple de la escritura en caso de que el poder notarial del representante legal
no se encuentre dentro del acta constitutiva;
y de la misma manera, la última modificación a los estatutos (solo para el caso que se haya modificado su objeto social).
Constancia de Situación fiscal vigente y su constancia de opinión POSITIVA emitida por el SAT.
EN AMBOS CASOS SE DEBERÁ DE ADJUNTAR COPIA DE LA OPINIÓN DE CUMPLIMIENTO DE OBLIGACIONES ESTATALES
EN SENTIDO POSITIVO EMITIDA POR LA SECRETARÍA DE FINANZAS DEL GOBIERNO DEL ESTADO DE QUERÉTARO.
Documento No. 3  Copia original certificada de una identificación oficial vigente (credencial de elector, pasaporte).
Documento No. 7  Copia de la constancia vigente que acredite estar dado de alta en el padrón de proveedores de Oficialía Mayor.
Texto FIANZA SERIEDAD DE PROPUESTA Por _____ (1) _________    A favor de la UNIVERSIDAD AERONÁUTICA EN QUERÉTARO
4.14 Que el importe de la garantía de seriedad de la propuesta sea menor al solicitado, así como no presentar la garantía con
cheque de caja, cheque certificado o fianza emitida por una institución legalmente constituida.
En hoja membretada de la empresa debera presentar relación de clientes principales.
deberá presentar carta poder simple, esto es suscrita ante dos testigos.
"""


UNAQ_ANEXO_SNIPPET = """
Anexo I, es el modelo de cómo podrá presentarla. No podrá ofertar una unidad de medida o cantidad distinta.
Anexo II, manifiesto de conformidad con las bases, en este documento deberá integrar copia de la invitación.
Anexo III, que refiere a los datos generales del participante, debidamente llenado y firmado.
Anexo V, Carta Garantía de Calidad de los productos y/o servicios que el concursante esté ofertando.
Anexo VII, Carta Declaración de Integridad, donde manifieste abstenerse de adoptar conductas.
Anexo X, carta firmada manifestando bajo protesta de decir verdad que no tiene conflicto de interés.
ANEXO XI, Manifiesto firmado por el representante legal de no encontrarse vinculado por algún socio.
Anexo XII, es un ejemplo de cómo podrá presentarla. No podrá ofertar una unidad de medida.
Anexo XIII, en caso de presentarla mediante fianza, la misma deberá cumplir requisitos de ejecución.
Sobres cerrados con propuestas técnicas y económicas deberán entregarse en ventanilla.
"""


def test_unaq_anexo_inventory_from_corpus():
    from app.services.junta_bases_corpus import BasesCorpus
    from app.services.pliego_formats_enrichment_service import (
        extract_pliego_anexos_from_bases_corpus,
    )

    corpus = BasesCorpus(session_id="s_unaq_fmt", segments=[("Bases.pdf", UNAQ_ANEXO_SNIPPET)])
    rows = extract_pliego_anexos_from_bases_corpus(corpus)
    names = " ".join(r["nombre_canonico"].lower() for r in rows)
    assert len(rows) >= 7
    assert "anexo iii" in names
    assert "anexo vii" in names or "integridad" in names
    assert "anexo x" in names
    assert "anexo xiii" not in names
    assert "sobres cerrados" not in names


def test_formats_panel_noise_excludes_sobres_and_formato_anexar():
    from app.services.document_deliverable_filter import is_formats_panel_noise

    assert is_formats_panel_noise("Sobres cerrados con propuestas técnicas y económicas")
    assert is_formats_panel_noise("Formato para Anexar Documentos")
    assert not is_formats_panel_noise(
        "Anexo VII: Carta Declaración de Integridad",
        snippet="Carta Declaración de Integridad",
    )


def test_unaq_documento_no_panel_deduped_without_noise():
    from app.services.corporate_physical_enrichment_service import (
        extract_corporate_physical_from_bases_corpus,
    )
    from app.services.document_deliverable_filter import (
        is_corporate_physical_panel_noise,
        physical_credential_dedupe_key,
    )
    from app.services.junta_bases_corpus import BasesCorpus

    assert is_corporate_physical_panel_noise(
        "Formato para Anexar Documentos",
        snippet="deberá presentar acta constitutiva vigente",
    )
    assert is_corporate_physical_panel_noise(
        "Fianza de Seriedad de Propuesta",
        snippet="Por _____ (1) _________ A favor de la UNIVERSIDAD",
    )

    corpus = BasesCorpus(session_id="s_unaq", segments=[("Bases.pdf", UNAQ_DOCNO_SNIPPET)])
    rows = extract_corporate_physical_from_bases_corpus(corpus)
    names = [r["nombre"] for r in rows]
    keys = [physical_credential_dedupe_key(n) for n in names]
    assert len(keys) == len(set(keys))
    def _fold(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn"
        )

    joined = _fold(" ".join(names))
    assert "identificaci" in joined
    assert "acta constitutiva" in joined
    assert "poder notarial" in joined or "poder" in joined
    assert "sat" in joined or "situacion fiscal" in joined
    assert "queretaro" in joined or "estatal" in joined
    assert "padron" in joined
    assert "garantia" in joined or "seriedad" in joined
    assert "relacion" in joined
    assert "carta poder" in joined
    assert "formato para anexar" not in joined
    assert not any("fianza de seriedad" in n.lower() and "garantia" not in n.lower() for n in names)


def test_physical_dedupe_merges_sat_and_escritura_variants():
    from app.services.document_deliverable_filter import physical_credential_dedupe_key

    k1 = physical_credential_dedupe_key(
        "Constancia de Situación Fiscal Vigente y opinión SAT"
    )
    k2 = physical_credential_dedupe_key("Constancia de Situación fiscal vigente")
    k3 = physical_credential_dedupe_key("Escritura de la empresa")
    k4 = physical_credential_dedupe_key("Poder Notarial del Representante Legal")
    assert k1 == k2
    assert k3 == k4


def test_opm_section6_extracts_imss_sat_and_domicilio():
    from app.services.corporate_physical_enrichment_service import (
        extract_corporate_physical_from_bases_corpus,
    )
    from app.services.junta_bases_corpus import BasesCorpus

    snippet = """
6.3. Identificación oficial del licitante persona física (o de representante legal).
6.5. Constancia positiva vigente de Opinión de Cumplimiento de Obligaciones Fiscales Federales expedida por el SAT.
6.6 Carta compromiso en la que se obliga a presentar la Constancia de No Adeudo expedida por la Tesorería Municipal.
6.7 Opinión de cumplimiento de obligaciones fiscales en materia de seguridad social, expedida por el IMSS
6.10. Comprobante de domicilio fiscal del licitante.
6.4. Manifestación bajo protesta (Forma DD-04) de operaciones inexistentes.
"""
    corpus = BasesCorpus(session_id="s_opm", segments=[("Bases.pdf", snippet)])
    rows = extract_corporate_physical_from_bases_corpus(corpus)
    names = " ".join(r["nombre"].lower() for r in rows)
    assert "sat" in names or "opinión" in names or "cumplimiento" in names
    assert "imss" in names
    assert "domicilio" in names
    assert "identificación" in names
    assert "no adeudo" in names or "adeudo" in names
    assert "dd-04" not in names and "operaciones inexistentes" not in names


def test_federal_bases_corporate_panel_filters_noise():
    from app.services.corporate_physical_enrichment_service import (
        extract_corporate_physical_from_bases_corpus,
    )
    from app.services.document_deliverable_filter import is_corporate_physical_credential_for_panel
    from app.services.junta_bases_corpus import BasesCorpus

    snippet = """
REQUISITOS DEL PARTICIPANTE
4.2. Identificación oficial vigente de quien firma las proposiciones.
4.3. Cédula de determinación de cuotas obrero-patronales del SUA y comprobante de pago,
así como opinión del cumplimiento de obligaciones en materia de seguridad social (IMSS).
4.4. Presentar el formato de Opinión del SAT, respecto al Artículo 32 del Código Fiscal.
4.5. Acta Constitutiva de la empresa.
4.6. Póliza de seguro de responsabilidad civil.
8.2. Presentación de CFDI o factura electrónica en formato digital.
8.3. Mano de Obra (cálculo del factor del salario real).
9.1. Garantía de cumplimiento del contrato.
9.2. Devolución de la Garantía El Instituto dará al proveedor su autorización.
10.1. Seguros: el licitante ganador durante la vigencia del contrato deberá presentar póliza.
11.1. ANEXO 9 Resumen de cotización.
11.2. Carta en papel, preferentemente membretado, Bajo Protesta de Decir Verdad.
"""
    corpus = BasesCorpus(session_id="s_fed", segments=[("Bases.pdf", snippet)])
    rows = extract_corporate_physical_from_bases_corpus(corpus)
    names = " | ".join(r["nombre"].lower() for r in rows)
    assert "identificaci" in names
    assert "acta constitutiva" in names
    assert "imss" in names or "cedula" in names or "obrero" in names
    assert "responsabilidad civil" in names or "poliza" in names
    assert "cfdi" not in names
    assert "mano de obra" not in names
    assert "anexo 9" not in names
    assert "devoluci" not in names
    assert "licitante ganador" not in names
    assert len(rows) <= 8
    assert not is_corporate_physical_credential_for_panel(
        "Presentar el formato de Opinión del SAT", "", "formato artículo 32"
    )
    assert not is_corporate_physical_credential_for_panel(
        "Carta en papel membretado Bajo Protesta de Decir Verdad", "", ""
    )


def test_corporate_physical_panel_excludes_pliego_annexes():
    from app.services.document_deliverable_filter import (
        is_corporate_physical_credential_for_panel,
        filter_corporate_physical_consolidated,
    )

    assert not is_corporate_physical_credential_for_panel(
        "11. Anexo L Comprobante de Muestras.doc", "", "comprobante de muestras"
    )
    assert not is_corporate_physical_credential_for_panel(
        "1. Anexo A-I Acreditación de Personalidad. Persona Física.doc", "", ""
    )
    assert not is_corporate_physical_credential_for_panel(
        "7. Anexo F Constancia de Visitas.xlsx", "", "visita instalaciones"
    )
    assert is_corporate_physical_credential_for_panel(
        "Constancia de situación fiscal SAT",
        "",
        "Impresión de la Constancia de situación fiscal",
        "presentar_fisico",
    )
    assert is_corporate_physical_credential_for_panel(
        "Opinión del Cumplimiento de Obligaciones Fiscales expedida por el SAT",
        "",
        "opinión positiva vigente",
    )

    consolidated = {
        "sobre_1_tecnico": [
            {"nombre_canonico": "Anexo L Comprobante de Muestras.doc", "tipo": "informativo"},
            {"nombre_canonico": "Constancia IMSS", "tipo": "presentar_fisico", "snippet_representativo": "constancia imss"},
        ],
        "sobre_2_economico": [],
        "requisitos_legales": [],
        "otros_requisitos_criticos": [],
    }
    out = filter_corporate_physical_consolidated(consolidated)
    names = [x["nombre"] for x in out["candidate_document_list"]]
    assert len(names) == 1
    assert "IMSS" in names[0]


def test_company_credential_blocks_generation_not_convocante_letters_enforced():
    raw = {
        "administrativo": [
            {
                "nombre": "Opinión del Cumplimiento de Obligaciones Fiscales expedida por el SAT",
                "descripcion": "Solvencia",
                "snippet": "opinión positiva del sat",
                "tipo_accion": "generar",
            },
            {
                "nombre": "Carta de declaración de integridad",
                "descripcion": "Formato",
                "snippet": "Carta bajo protesta Anexo M",
                "tipo_accion": "generar",
            },
        ],
        "tecnico": [],
        "formatos": [],
    }
    out = filter_compliance_for_generation(raw)
    admin_names = [x["nombre"] for x in out["administrativo"]]
    assert len(admin_names) == 1
    assert "integridad" in admin_names[0].lower()
    assert out["_generation_filter_meta"]["skipped_company_credential"] >= 1


def test_enforce_deterministic_tipo_accion_causal_and_fisico():
    causal = enforce_deterministic_tipo_accion(
        {"nombre": "No presentar documentación engrapada", "tipo_accion": "generar", "quality_flags": []}
    )
    assert causal["tipo_accion"] == "informativo"
    fisico = enforce_deterministic_tipo_accion(
        {
            "nombre": "Opinión del cumplimiento SAT",
            "descripcion": "Opinión positiva",
            "tipo_accion": "generar",
            "quality_flags": [],
        }
    )
    assert fisico["tipo_accion"] == "presentar_fisico"
    imss = enforce_deterministic_tipo_accion(
        {
            "nombre": "Constancia de cumplimiento IMSS",
            "tipo_accion": "generar",
            "quality_flags": [],
        }
    )
    assert imss["tipo_accion"] == "presentar_fisico"
    assert "enforced_company_credential_fisico" in (imss.get("quality_flags") or [])
