from app.services.legal_representative_parser import (
    detect_cif_contribuyente_name,
    detect_legal_representative,
    strip_identity_labels_from_person_name,
)


def test_detect_representante_by_se_designa_pattern():
    text = (
        "En asamblea general extraordinaria se designa a Juan Carlos Perez Lopez "
        "como Administrador Unico de la sociedad."
    )
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert "Juan Carlos Perez Lopez" in result["representative"]
    assert result["confidence"] >= 0.9


def test_detect_representante_by_representante_legal_pattern():
    text = "Representante legal: Maria Fernanda Torres Ramirez con facultades de administracion."
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert "Maria Fernanda Torres Ramirez" in result["representative"]


def test_detect_representante_not_found():
    text = "Objeto social de la compania y clausulas estatutarias sin nombramientos."
    result = detect_legal_representative(text)
    assert result["found"] is False
    assert result["representative"] is None


def test_solo_apoderado_legal_acta_sin_asamblea():
    """Sin escritura de asamblea, el apoderado del acta sigue siendo señal válida."""
    text = "Apoderado legal: Luis Marin Ortega con facultades amplias para actos de administración."
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert "Luis Marin Ortega" in result["representative"]


def test_detect_delegado_especial_con_saltos_ocr_entre_c_y_caracter():
    """Escritura escaneada: saltos de línea entre el C. y «carácter de delegado especial»."""
    text = (
        "el C. Enrique Tadeo Torres Dorantes comparece \n\n"
        "en su caracter de delegado especial de la sociedad."
    )
    r = detect_legal_representative(text)
    assert r["found"] is True
    assert "Enrique Tadeo Torres Dorantes" in r["representative"]
    assert r["trigger"] == "c_nombre_hasta_caracter_delegado_especial"


def test_delegado_especial_prevalece_sobre_apoderado_cuando_coexisten():
    """Patrones genéricos: nombramiento societario reciente no debe perder por mero orden del acta fundador."""
    text = (
        "En la cláusula novena el Apoderado Legal: Pedro Gomez Soto para pleitos y cobranzas. "
        "En asamblea general el C. Ana Ruiz Mendez, en su caracter de delegado especial de la sociedad."
    )
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert "Ana Ruiz Mendez" in result["representative"]
    assert "Pedro Gomez" not in result["representative"]


def test_detect_admin_unico_recayendo_nombramiento_acta_constitutiva():
    """Redacción típica en escritura pública (escaneo OCR): nombre tras 'recayendo dicho nombramiento en el señor'."""
    text = (
        "B).- Que la Sociedad se administre por un ADMINISTRADOR ÚNICO, recayendo dicho nombramiento "
        "en el señor HECTOR MANUEL ALVAREZ GUTIERREZ, quien acepta y toma posesión del cargo."
    )
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert result["trigger"] == "admin_unico_recayendo_nombramiento"
    assert "HECTOR MANUEL ALVAREZ GUTIERREZ" in (result["representative"] or "").upper()


def test_detect_admin_unico_recayendo_el_nombramiento():
    text = (
        "ADMINISTRADOR UNICO, recayendo el nombramiento en el señor Maria Elena Rios Paredes "
        "quien comparece."
    )
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert "Maria Elena Rios Paredes" in result["representative"]


def test_detect_cif_contribuyente_nombre_desde_constancia():
    text = (
        "CÉDULA DE IDENTIFICACION FISCAL\n"
        "RFC:\nAAGH650922253\n"
        "Nombre (s):\nHECTOR MANUEL\n"
        "Primer Apellido:\nALVAREZ\n"
        "Segundo Apellido:\nGUTIERREZ\n"
        "Fecha inicio de operaciones:"
    )
    r = detect_cif_contribuyente_name(text)
    assert r["found"] is True
    assert r["trigger"] == "cif_nombre_apellidos"
    assert "HECTOR MANUEL" in r["full_name"].upper()
    assert "ALVAREZ" in r["full_name"].upper()
    assert "GUTIERREZ" in r["full_name"].upper()


def test_detect_cif_sin_marcador_sat():
    text = "Nombre (s): Ana Lopez Primer Apellido: Ruiz Segundo Apellido: Soto"
    r = detect_cif_contribuyente_name(text)
    assert r["found"] is False


def test_rechaza_delegado_especial_para_que_ocurra_ante_notario():
    text = "Delegado Especial para que ocurra ante Notario Publico"
    result = detect_legal_representative(text)
    assert result["found"] is False


def test_no_confunde_como_comisario_con_nombre():
    """Regresión: «se designa como Comisario» no es un nombre humano."""
    from app.services.legal_representative_parser import is_plausible_representative_name

    assert is_plausible_representative_name("como Comisario") is False
    text = "En asamblea se designa como Comisario a Roberto Sanchez Garcia quien acepta el cargo."
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert result["trigger"] == "se_designa_como_cargo_a"
    assert "Roberto Sanchez Garcia" in result["representative"]


def test_strip_identity_labels_quita_curp_colgando():
    assert strip_identity_labels_from_person_name("Juan Carlos López Martínez CURP") == "Juan Carlos López Martínez"
    assert (
        strip_identity_labels_from_person_name("Ana Ruiz Mendez RFC ABC010101AA1")
        == "Ana Ruiz Mendez"
    )


def test_detect_representante_sin_curp_en_cola_ocr():
    text = (
        "Apoderado legal: Juan Carlos Lopez Martinez CURP LOJM800101HDFRNN09 "
        "con facultades de administracion."
    )
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert result["representative"] == "Juan Carlos Lopez Martinez"


def test_nombrar_como_administrador_unico_a_nombre():
    text = (
        "Los socios convienen en nombrar como Administrador Unico a "
        "Maria Fernanda Torres Ramirez con facultades amplias."
    )
    result = detect_legal_representative(text)
    assert result["found"] is True
    assert result["trigger"] in {"nombrar_como_cargo_a", "nombrar_como_nuevo_admin_unico", "se_nombra_admin_unico"}
    assert "Maria Fernanda Torres Ramirez" in result["representative"]
