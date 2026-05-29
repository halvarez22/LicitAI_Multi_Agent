"""Tests universales: catálogo de plantillas y reporte de cobertura."""

from app.services.delivery_coverage_report import build_delivery_coverage_report
from app.services.session_template_catalog import (
    build_session_template_catalog,
    classify_ingested_filename,
    infer_plantilla_sobre,
    is_anexo_tecnico_propuesta_entregable,
)


def test_classify_pliego_referencia_universal():
    doc_class, accion, _ = classify_ingested_filename("bases_0001.pdf")
    assert doc_class == "pliego_referencia"
    assert accion == "referencia"


def test_classify_plantilla_anexo_doc():
    doc_class, accion, sobre = classify_ingested_filename(
        "12. Anexo M (Declaración de Integridad).doc"
    )
    assert doc_class == "plantilla_oferta"
    assert accion == "generar"
    assert sobre == "administrativo"


def test_classify_credencial_ine():
    doc_class, accion, _ = classify_ingested_filename(
        "1. Anexo A-I Acreditación de Personalidad. Persona Física.doc"
    )
    assert doc_class == "credencial_empresa"
    assert accion == "presentar_fisico"


def test_infer_sobre_con_nombre_pipeline_underscores():
    fn = "cat_ANEXO_TECNICO_2026_ABRIL_A_DICIEMBRE.docx"
    assert infer_plantilla_sobre(fn) == "tecnico"
    assert infer_plantilla_sobre("15_Anexo_III_Descripcion_del_Servicio.docx") == "tecnico"


def test_infer_sobre_con_unicode_descompuesto():
    assert infer_plantilla_sobre("ANEXO TE\u0301CNICO 2026 ABRIL A DICIEMBRE.docx") == "tecnico"
    assert infer_plantilla_sobre("15. Anexo III Descripcio\u0301n del Servicio de Limpieza.docx") == "tecnico"


def test_anexo_d_iii_permanece_administrativo():
    assert infer_plantilla_sobre("5. Anexo D-III Integración del costo de limpieza.docx") == "administrativo"


def test_anexo_tecnico_2026_es_plantilla_tecnica():
    fn = "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx"
    assert is_anexo_tecnico_propuesta_entregable(fn)
    doc_class, accion, sobre = classify_ingested_filename(fn)
    assert doc_class == "plantilla_oferta"
    assert accion == "generar"
    assert sobre == "tecnico"


def test_anexo_tecnico_pdf_es_referencia_aun_con_unicode_descompuesto():
    doc_class, accion, sobre = classify_ingested_filename("ANEXO TE\u0301CNICO.pdf")
    assert doc_class == "pliego_referencia"
    assert accion == "referencia"
    assert sobre == "administrativo"


def test_anexo_iii_b_es_tecnico_no_economico():
    assert infer_plantilla_sobre("21. Anexo III-B Actividades del supervisor de limpieza.docx") == "tecnico"
    assert infer_plantilla_sobre("27. Anexo III-G Entrega RM.xls") == "tecnico"


def test_anexo_iii_zona_es_economico():
    assert infer_plantilla_sobre("16. Anexo III P 1 Zona A.xlsx") == "economico"


def test_classify_propuesta_economica_zona():
    doc_class, accion, sobre = classify_ingested_filename(
        "32. Anexo III P1-2 ZA_Propuesta economica.xlsx"
    )
    assert doc_class == "plantilla_oferta"
    assert accion == "generar"
    assert sobre == "economico"


def test_catalog_counts_plantillas():
    docs = [
        {
            "id": "1",
            "content": {"filename": "16. Anexo III P 1 Zona A.xlsx"},
            "metadata": {"status": "ANALYZED"},
        },
        {
            "id": "2",
            "content": {"filename": "bases_0001.pdf"},
            "metadata": {"status": "ANALYZED"},
        },
    ]
    cat = build_session_template_catalog("test_sess", docs)
    assert cat["stats"]["plantilla_oferta"] == 1
    assert cat["stats"]["pliego_referencia"] == 1


def test_coverage_report_pendiente_sin_manifiesto():
    cat = build_session_template_catalog(
        "s1",
        [
            {
                "id": "a",
                "content": {"filename": "10. Anexo K Declaración.docx"},
                "metadata": {},
            }
        ],
    )
    report = build_delivery_coverage_report(
        "s1",
        {"tasks_completed": []},
        [],
        catalog=cat,
    )
    plantilla_rows = [
        r
        for r in report["rows"]
        if r["document_class"] == "plantilla_oferta" and r["accion_recomendada"] == "generar"
    ]
    assert len(plantilla_rows) >= 1
    assert plantilla_rows[0]["estado_cobertura"] in (
        "pendiente_generar",
        "generado",
        "omitido_por_clasificacion",
    )


def test_coverage_report_prefiere_source_doc_id_sobre_nombre():
    cat = build_session_template_catalog(
        "s_lineage",
        [
            {
                "id": "doc-123",
                "content": {"filename": "10. Anexo K Declaración.docx"},
                "metadata": {},
            }
        ],
    )
    report = build_delivery_coverage_report(
        "s_lineage",
        {
            "tasks_completed": [
                {
                    "task": "formats_generation_COMPLETED",
                    "result": {
                        "documentos": [
                            {
                                "nombre": "Salida pipeline.docx",
                                "ruta": "/tmp/salida.docx",
                                "source_doc_id": "doc-123",
                                "source_filename": "10. Anexo K Declaración.docx",
                                "materialization_route": "mirror",
                            }
                        ]
                    },
                }
            ]
        },
        [],
        catalog=cat,
    )
    row = report["rows"][0]
    assert row["estado_cobertura"] == "generado"
    assert row["match_method"] == "generated_source_doc_id"
    assert row["delivered_source_doc_id"] == "doc-123"
