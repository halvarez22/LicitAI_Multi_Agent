"""Extracción determinista persona física (INE + RFC)."""

from app.services.fisica_profile_extract import (
    detect_ine_holder_name,
    resolve_fisica_full_name,
    resolve_rfc_persona_fisica,
)


def test_detect_ine_holder_name_desde_credencial():
    text = (
        "INSTITUTO NACIONAL ELECTORAL\n"
        "CREDENCIAL PARA VOTAR\n"
        "NOMBRE\n"
        "HECTOR MANUEL ALVAREZ GUTIERREZ\n"
        "DOMICILIO\n"
        "CALLE EJEMPLO 123\n"
    )
    r = detect_ine_holder_name(text)
    assert r["found"] is True
    assert "HECTOR MANUEL ALVAREZ GUTIERREZ" in r["full_name"].upper()


def test_resolve_fisica_full_name_precedencia_ine_sobre_cif():
    ine = (
        "INSTITUTO NACIONAL ELECTORAL\n"
        "NOMBRE\nANA LUCIA MORALES RIOS\n"
    )
    cif = (
        "CÉDULA DE IDENTIFICACIÓN FISCAL\n"
        "Nombre (s): MARIA\nPrimer Apellido: OTRO\nSegundo Apellido: NOMBRE\n"
    )
    hit = resolve_fisica_full_name(ine_blob=ine, cif_blob=cif)
    assert hit["found"] is True
    assert "ANA LUCIA MORALES RIOS" in hit["full_name"].upper()


def test_resolve_rfc_persona_fisica_prefiere_4_letras():
    ctx = "RFC: CMT160107S83 persona moral\nRFC: AAGH650922253 nombre fisica"
    out = resolve_rfc_persona_fisica(ctx, "CMT160107S83")
    assert out["value"] == "AAGH650922253"
    assert out["changed"] is True
