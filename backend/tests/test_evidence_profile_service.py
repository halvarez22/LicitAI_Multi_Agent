from app.services.evidence_profile_service import (
    build_conflict_pending_questions,
    build_effective_profile,
    build_evidence_profile_from_documents,
    detect_profile_conflicts,
)


def test_build_evidence_profile_from_documents_extracts_core_fields():
    docs = [
        {
            "id": "doc1",
            "content": {
                "status": "ANALYZED",
                "filename": "contrato_manavil.pdf",
                "extracted_text": (
                    "RFC MAAA010101ABC. Representante legal: MARIA ANDREA ALVAREZ AGUILAR. "
                    "Experiencia comprobable de 8 años en servicios similares. "
                    "Capital contable $2,500,000. Domicilio fiscal: Av Reforma 123 Col Centro CDMX. "
                    "Cuenta con certificación ISO 9001:2015."
                ),
            },
        }
    ]

    evidence = build_evidence_profile_from_documents(docs)
    fields = evidence.get("fields") or {}

    assert fields.get("rfc", {}).get("value") == "MAAA010101ABC"
    assert fields.get("representante_legal", {}).get("value").startswith("MARIA")
    assert fields.get("anos_experiencia", {}).get("value") == "8"
    assert fields.get("capital_contable", {}).get("value") == "2500000"
    assert "ISO9001:2015" in (fields.get("certificaciones", {}).get("value") or [])


def test_build_evidence_profile_extracts_contact_fields():
    docs = [
        {
            "id": "doc_cv",
            "content": {
                "status": "ANALYZED",
                "filename": "CV_Empresarial_MANAVIL.pdf",
                "extracted_text": (
                    "Contacto: +52 477 779 7346. "
                    "Correo: licitaciones@manavil.com.mx "
                    "Sitio: www.manavil.com.mx"
                ),
            },
        }
    ]
    evidence = build_evidence_profile_from_documents(docs)
    fields = evidence.get("fields") or {}
    assert "telefono" in fields
    assert fields.get("email", {}).get("value") == "licitaciones@manavil.com.mx"
    assert "manavil.com.mx" in fields.get("web", {}).get("value", "")


def test_cv_precedence_over_numeric_annex_for_contact_fields():
    """226.pdf no debe ocupar email/teléfono antes que un CV con datos reales."""
    docs = [
        {
            "id": "doc226",
            "content": {
                "status": "ANALYZED",
                "filename": "226.pdf",
                "extracted_text": (
                    "Correo institucional etfoyav@guanajuato.gob.mx "
                    "Contrato número 8900005011. Tel referencia 8900005011. "
                    "Domicilio administrativo: General de Recursos Materiales."
                ),
            },
        },
        {
            "id": "doc_cv",
            "content": {
                "status": "ANALYZED",
                "filename": "CV Seguridad Privada Integral.pdf",
                "extracted_text": (
                    "BLVD. LAS PALMAS # 513-A COL. ARBIDE "
                    "TELS. (477) 779-73-46, 470-36-19 y 717-82-00 C.P. 37360 LEON, GTO. "
                    "e-mail: seguridadintegralmanavil@yahoo.com "
                    "www.manavil-seguridad.com.mx"
                ),
            },
        },
    ]
    evidence = build_evidence_profile_from_documents(docs)
    fields = evidence.get("fields") or {}
    assert fields.get("email", {}).get("value") == "seguridadintegralmanavil@yahoo.com"
    assert fields.get("email", {}).get("source_doc") == "CV Seguridad Privada Integral.pdf"
    assert "779" in (fields.get("telefono", {}).get("value") or "")
    assert fields.get("telefono", {}).get("source_doc") == "CV Seguridad Privada Integral.pdf"
    contratos = fields.get("contratos_previos", {}).get("value") or []
    assert len(contratos) == 1
    assert contratos[0]["contrato_id"] == "8900005011"


def test_gob_mx_email_skipped_until_corporate_found():
    """Rechaza .gob.mx y usa el siguiente correo aceptable en el mismo documento."""
    docs = [
        {
            "id": "mix",
            "content": {
                "status": "ANALYZED",
                "filename": "propuesta_mixta.pdf",
                "extracted_text": (
                    "Atentamente unidad@guanajuato.gob.mx para aclaraciones. "
                    "Contacto oferente: licitaciones@empresa-privada.com.mx"
                ),
            },
        }
    ]
    evidence = build_evidence_profile_from_documents(docs)
    assert (
        evidence.get("fields", {}).get("email", {}).get("value")
        == "licitaciones@empresa-privada.com.mx"
    )


def test_build_evidence_profile_extracts_contratos_previos():
    docs = [
        {
            "id": "doc226",
            "content": {
                "status": "ANALYZED",
                "filename": "226.pdf",
                "extracted_text": (
                    "Constancia de contrato número 8900005011 para servicios integrales. "
                    "Se acreditan 1,514 elementos de vigilancia en operación."
                ),
            },
        }
    ]
    evidence = build_evidence_profile_from_documents(docs)
    contratos = (evidence.get("fields") or {}).get("contratos_previos", {}).get("value") or []
    assert len(contratos) == 1
    assert contratos[0]["contrato_id"] == "8900005011"
    assert contratos[0]["elementos_vigilancia"] == "1514"


def test_build_evidence_profile_ignores_low_signal_documents():
    docs = [
        {"id": "x1", "content": {"filename": "vacio.pdf", "extracted_text": "   "}},
        {"id": "x2", "content": {"filename": "ruido.pdf", "extracted_text": "abc"}},
    ]
    evidence = build_evidence_profile_from_documents(docs)
    assert evidence.get("fields") == {}


def test_build_evidence_profile_ignores_base_documents_by_source_name():
    docs = [
        {
            "id": "base_doc",
            "content": {
                "status": "ANALYZED",
                "filename": "LA-51-GYN-051GYN025-N-8-2024 VIGILANCIA.pdf",
                "extracted_text": "RFC MUAE731110GP9 y domicilio administrativo",
            },
        },
        {
            "id": "company_doc",
            "content": {
                "status": "ANALYZED",
                "filename": "CV_Empresarial_MANAVIL.pdf",
                "extracted_text": "RFC SPI060202AG5 y correo contacto@manavil.com.mx",
            },
        },
    ]
    evidence = build_evidence_profile_from_documents(docs)
    fields = evidence.get("fields") or {}
    assert fields.get("rfc", {}).get("value") == "SPI060202AG5"


def test_build_effective_profile_respects_precedence():
    master = {
        "rfc": "OLDR010101AAA",
        "representante_legal": "REP MASTER",
        "anos_experiencia": "2",
    }
    evidence = {
        "fields": {
            "rfc": {"value": "NEWR010101BBB", "source_doc": "acta.pdf", "confidence": 0.8},
            "representante_legal": {"value": "REP DOC", "source_doc": "poder.pdf", "confidence": 0.9},
        }
    }
    overrides = {"representante_legal": "REP HITL"}

    effective, provenance = build_effective_profile(
        master_profile=master,
        evidence_profile=evidence,
        user_overrides=overrides,
    )

    assert effective["rfc"] == "NEWR010101BBB"
    assert effective["representante_legal"] == "REP HITL"
    assert effective["anos_experiencia"] == "2"
    assert provenance["rfc"]["source"] == "session_doc"
    assert provenance["representante_legal"]["source"] == "user_direct"


def test_detect_profile_conflicts_and_pending_questions():
    master = {"representante_legal": "REP MASTER", "rfc": "AAA010101AAA"}
    evidence = {
        "fields": {
            "representante_legal": {
                "value": "REP DOCUMENTO",
                "source_doc": "acta_nueva.pdf",
                "confidence": 0.9,
            },
            "rfc": {"value": "AAA010101AAA", "source_doc": "sat.pdf", "confidence": 0.9},
        }
    }

    conflicts = detect_profile_conflicts(master_profile=master, evidence_profile=evidence)
    assert len(conflicts) == 1
    assert conflicts[0]["field"] == "representante_legal"
    assert conflicts[0]["error_type"] == "CONFLICTING_EVIDENCE"

    questions = build_conflict_pending_questions(conflicts)
    assert len(questions) == 1
    assert questions[0]["type"] == "evidence_profile_conflict"
    assert questions[0]["error_type"] == "CONFLICTING_EVIDENCE"


def test_detect_profile_conflicts_skips_resolved_fields():
    master = {"representante_legal": "REP MASTER"}
    evidence = {
        "fields": {
            "representante_legal": {"value": "REP DOC", "source_doc": "x.pdf", "confidence": 0.9},
        }
    }
    overrides = {"representante_legal": {"value": "REP MASTER", "chosen_source": "master_profile"}}
    conflicts = detect_profile_conflicts(
        master_profile=master,
        evidence_profile=evidence,
        evidence_profile_overrides=overrides,
    )
    assert conflicts == []
