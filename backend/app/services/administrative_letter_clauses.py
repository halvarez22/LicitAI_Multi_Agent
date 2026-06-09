"""
Cuerpos determinísticos de cartas administrativas por familia de anexo (universal).

Sin hardcode por licitación: slots desde perfil maestro, metadatos de sesión y snippet de bases.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key
from app.services.convocante_resolver import city_from_convocante_text


def _slot(value: Any, fallback: str = "") -> str:
    t = str(value or "").strip()
    return t if t else fallback


_CP_ONLY_RE = re.compile(
    r"(?i)^(?:c[oó]digo\s+postal|cp\.?)\s*\d{5}$|^\d{5}$"
)
_CP_INLINE_RE = re.compile(
    r"(?i)\s*,?\s*(?:c[oó]digo\s+postal|cp\.?)\s*\d{5}\s*$"
)
_STREET_SEGMENT_RE = re.compile(
    r"(?i)(?:^|\b)(?:avenida|av\.|boulevard|blvd\.|calle|c\.|carretera|"
    r"edificio|departamento|depto\.?|fraccionamiento|colonia|num\.|no\.|#)"
)
_CP_ESTADO_ABREV: Dict[str, str] = {
    "01": "CDMX", "02": "CDMX", "03": "CDMX", "04": "CDMX", "05": "CDMX",
    "06": "CDMX", "07": "CDMX", "08": "CDMX", "09": "CDMX", "10": "CDMX",
    "11": "CDMX", "12": "CDMX", "13": "CDMX", "14": "CDMX", "15": "CDMX", "16": "CDMX",
    "20": "Ags.", "21": "Ags.",
    "22": "B.C.", "23": "B.C.",
    "24": "B.C.S.", "25": "B.C.S.",
    "26": "Camp.", "27": "Camp.",
    "28": "Coah.", "29": "Coah.", "30": "Coah.", "31": "Coah.",
    "32": "Col.", "33": "Col.",
    "34": "Chis.", "35": "Chis.",
    "36": "Chih.", "37": "Chih.",
    "38": "Dgo.", "39": "Dgo.",
    "40": "Gto.", "41": "Gto.",
    "42": "Gro.", "43": "Gro.", "44": "Gro.", "45": "Gro.", "46": "Gro.", "47": "Gro.",
    "48": "Hgo.", "49": "Hgo.", "50": "Hgo.", "51": "Hgo.", "52": "Hgo.",
    "53": "Hgo.", "54": "Hgo.", "55": "Hgo.", "56": "Hgo.", "57": "Hgo.",
    "58": "Mor.", "59": "Mor.", "60": "Mor.", "61": "Mor.", "62": "Mor.",
    "63": "Jal.", "64": "Jal.", "65": "Jal.", "66": "Jal.", "67": "Jal.",
    "68": "Jal.", "69": "Jal.",
    "70": "Tab.", "71": "Tab.",
    "72": "Pue.", "73": "Pue.", "74": "Pue.", "75": "Pue.",
    "76": "Qro.", "77": "Qro.", "78": "Qro.", "79": "Qro.",
    "80": "Ver.", "81": "Ver.", "82": "Ver.", "83": "Ver.", "84": "Ver.",
    "85": "Ver.", "86": "Ver.", "87": "Ver.", "88": "Ver.", "89": "Ver.",
    "90": "Tab.", "91": "Tab.",
    "92": "Chis.", "93": "Chis.", "94": "Chis.", "95": "Chis.",
    "96": "Col.", "97": "Col.",
    "98": "N.L.", "99": "N.L.",
}


def _is_street_like_segment(segment: str) -> bool:
    """True si el fragmento parece vialidad/colonia, no municipio."""
    s = segment.strip()
    if not s or _CP_ONLY_RE.match(s):
        return True
    if re.search(r"(?i)c[oó]digo\s+postal|\bcp\b", s) and re.search(r"\d{5}", s):
        return True
    return bool(_STREET_SEGMENT_RE.search(s))


def _extract_postal_code(domicilio: str) -> str:
    m = re.search(r"\b(\d{5})\b", str(domicilio or ""))
    return m.group(1) if m else ""


def is_invalid_letter_lugar(lugar: str) -> bool:
    """Detecta valores inválidos para LUGAR Y FECHA (CP, vialidad, vacío)."""
    t = str(lugar or "").strip()
    if not t:
        return True
    if _CP_ONLY_RE.match(t):
        return True
    if re.search(r"(?i)c[oó]digo\s+postal|\bcp\b", t):
        return True
    if re.match(r"^\d{5}$", t):
        return True
    return _is_street_like_segment(t)


def city_from_domicilio(domicilio: str) -> str:
    """Extrae municipio/ciudad del domicilio fiscal (universal, sin CP ni vialidad)."""
    raw = str(domicilio or "").strip()
    if not raw:
        return "México"

    if "," not in raw:
        cleaned = _CP_INLINE_RE.sub("", raw).strip(" ,")
        if cleaned and cleaned != raw:
            parts = [p.strip() for p in cleaned.split(",") if p.strip()]
            for seg in reversed(parts or [cleaned]):
                if not _is_street_like_segment(seg):
                    return seg
        m = re.search(
            r"(?i)([A-Za-zÁÉÍÓÚáéíóúñ\.]+)\s+(?:,?\s*)?(?:C[oó]digo\s+Postal|CP\.?)\s*\d{5}",
            raw,
        )
        if m and not _is_street_like_segment(m.group(1)):
            return m.group(1).strip()

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for seg in reversed(parts):
        if not _is_street_like_segment(seg):
            return seg

    cleaned = _CP_INLINE_RE.sub("", raw).strip(" ,")
    tail = [p.strip() for p in cleaned.split(",") if p.strip()]
    if tail:
        return tail[-1]
    return "México"


def format_letter_lugar_ciudad(ciudad: str, domicilio: str = "") -> str:
    """Formatea lugar para carta: municipio + abreviatura de entidad si hay CP reconocible."""
    city = str(ciudad or "").strip()
    if not city or is_invalid_letter_lugar(city):
        return "México"
    # Si la sede convocante ya incluye entidad (p. ej. «León, GTO»), no mezclar CP fiscal.
    if re.search(r",\s*[A-ZÁÉÍÓÚÑ\.]{2,12}\.?\s*$", city):
        return city.rstrip(".")
    cp = _extract_postal_code(domicilio)
    abbrev = _CP_ESTADO_ABREV.get(cp[:2]) if len(cp) == 5 else ""
    if abbrev and abbrev not in city:
        return f"{city}, {abbrev}"
    return city


def resolve_document_ciudad(
    master_profile: Optional[Dict[str, Any]] = None,
    domicilio: Optional[str] = None,
    letter_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Resuelve el lugar para LUGAR Y FECHA.

    Cascada: sede convocante (bases/sesión) > municipio/ciudad del perfil > domicilio fiscal.
    """
    meta = letter_meta or {}
    dom = str(
        domicilio
        or (master_profile or {}).get("domicilio_fiscal")
        or (master_profile or {}).get("domicilio")
        or ""
    ).strip()
    for src in (
        meta.get("lugar_convocante"),
        city_from_convocante_text(meta.get("convocante")),
        city_from_convocante_text(meta.get("entidad")),
    ):
        val = str(src or "").strip()
        if val and not is_invalid_letter_lugar(val):
            return format_letter_lugar_ciudad(val, dom)

    mp = master_profile or {}
    for key in ("municipio", "ciudad", "localidad"):
        val = _slot(mp.get(key))
        if val and not is_invalid_letter_lugar(val):
            return format_letter_lugar_ciudad(val, dom)
    city = city_from_domicilio(dom)
    return format_letter_lugar_ciudad(city, dom)


def extract_letter_body_from_docx(file_path: str) -> str:
    """
    Extrae el cuerpo de una carta DOCX ya generada (entre separador y ATENTAMENTE).

    Permite refrescar encabezado/fecha/logo sin perder contenido LLM previo.
    """
    try:
        import docx
    except ImportError:
        return ""

    doc = docx.Document(file_path)
    texts = [p.text for p in doc.paragraphs]
    start: Optional[int] = None
    end: Optional[int] = None
    for i, text in enumerate(texts):
        if re.match(r"^_{10,}$", text.strip()):
            start = i + 1
        if start is not None and re.search(
            r"(?i)^A\s*T\s*E\s*N\s*T\s*A\s*M\s*E\s*N\s*T\s*E",
            text.strip(),
        ):
            end = i
            break
    if start is None:
        return ""
    body_lines = texts[start:end] if end is not None else texts[start:]
    return "\n".join(line for line in body_lines if line is not None).strip()


def resolve_letter_session_metadata(
    session_state: Optional[Dict[str, Any]] = None,
    *,
    triage_context: Optional[Dict[str, Any]] = None,
    req_snippet: str = "",
) -> Dict[str, str]:
    """
    Enriquece metadatos de carta: convocante, comité, número de procedimiento.

    Cascada: triage > análisis > fragmento de bases > genérico.
    """
    from app.services.convocante_resolver import extract_convocante_from_text

    session_state = session_state or {}
    tc = triage_context if isinstance(triage_context, dict) else {}
    blob = " ".join(
        str(x or "")
        for x in (
            tc.get("convocante"),
            tc.get("autoridad_convocante"),
            session_state.get("convocante"),
        )
    )
    for key in ("last_analysis", "analysis_snapshot"):
        block = session_state.get(key)
        if isinstance(block, dict):
            blob += " " + " ".join(
                str(block.get(k) or "")
                for k in (
                    "convocante",
                    "autoridad_convocante",
                    "entidad",
                    "dependencia",
                    "organismo",
                    "comite",
                    "concurso_label",
                )
            )
    blob += " " + str(session_state.get("bases_corpus_hint") or "")[:12000]
    blob += " " + str(req_snippet or "")

    extracted = extract_convocante_from_text(blob)

    convocante = _slot(tc.get("convocante") or tc.get("autoridad_convocante"))
    if not convocante:
        for key in ("last_analysis", "analysis_snapshot"):
            block = session_state.get(key)
            if isinstance(block, dict):
                convocante = _slot(
                    block.get("convocante")
                    or block.get("autoridad_convocante")
                    or block.get("entidad")
                )
                if convocante:
                    break
    if not convocante:
        convocante = _slot(extracted.get("convocante"))

    comite = _slot(extracted.get("comite"))
    if not comite:
        m_comite = re.search(
            r"(?i)(comit[eé]\s+de\s+adquisiciones[^\n\.]{0,220}|"
            r"comit[eé]\s+[^\n\.]{8,180}presente)",
            blob,
        )
        if m_comite:
            comite = re.sub(r"\s+", " ", m_comite.group(1)).strip(" .")

    proc = _slot(extracted.get("concurso_label"))
    if not proc:
        m_proc = re.search(
            r"(?i)((?:invitaci[oó]n|concurso|licitaci[oó]n)\s+(?:restringid[oa]|p[uú]blic[oa])?"
            r"[^\n\"]{0,120})",
            blob,
        )
        if m_proc:
            proc = re.sub(r"\s+", " ", m_proc.group(1)).strip(" .")

    destinatario = str(
        tc.get("destinatario")
        or session_state.get("destinatario")
        or extracted.get("destinatario")
        or ""
    ).strip()
    if not destinatario:
        for key in ("last_analysis", "analysis_snapshot"):
            block = session_state.get(key)
            if isinstance(block, dict):
                destinatario = str(block.get("destinatario") or "").strip()
                if destinatario:
                    break
    if not destinatario:
        if comite:
            destinatario = f"{comite.upper()}\nP R E S E N T E"
        elif convocante:
            destinatario = f"{convocante.upper()}\nPRESENTE.-"
        else:
            destinatario = "A QUIEN CORRESPONDA:"

    out: Dict[str, str] = {"destinatario": destinatario}
    if convocante:
        out["convocante"] = convocante
    if proc:
        out["concurso_label"] = proc
    if extracted.get("entidad"):
        out["entidad"] = extracted["entidad"]
    if extracted.get("dependencia"):
        out["dependencia"] = extracted["dependencia"]
    if extracted.get("lugar_convocante"):
        out["lugar_convocante"] = extracted["lugar_convocante"]
    elif convocante:
        lugar = city_from_convocante_text(convocante)
        if lugar:
            out["lugar_convocante"] = lugar
    return out


def _comparecencia_block(
    master_profile: Dict[str, Any],
    doc_metadata: Dict[str, Any],
) -> str:
    rep = _slot(
        master_profile.get("representante_legal") or master_profile.get("representante"),
        "el representante legal",
    )
    razon = _slot(master_profile.get("razon_social"), "la empresa concursante")
    rfc = _slot(master_profile.get("rfc"), "S/D")
    domicilio = _slot(
        master_profile.get("domicilio_fiscal") or master_profile.get("domicilio"),
        "domicilio fiscal registrado ante el SAT",
    )
    licitacion = _slot(
        doc_metadata.get("concurso_label")
        or doc_metadata.get("tender_name"),
        "el presente procedimiento de contratación",
    )
    return (
        f"Quien suscribe, **{rep}**, en mi carácter de Representante Legal con facultades "
        f"de administración de **{razon}**, con Registro Federal de Contribuyentes **{rfc}**, "
        f"señalando como domicilio para oír y recibir notificaciones el ubicado en {domicilio}; "
        f"comparezco en el procedimiento **{licitacion}** y expongo:"
    )


def _legal_blob(doc_metadata: Dict[str, Any]) -> str:
    """Texto combinado de snippet y corpus de bases para extracción normativa."""
    return " ".join(
        str(doc_metadata.get(k) or "")
        for k in ("req_snippet", "bases_corpus_hint", "req_desc")
    )[:16000]


def _call_clause_builder(
    builder: Any,
    meta: Dict[str, Any],
    master_profile: Dict[str, Any],
) -> str:
    """Invoca builder de cláusula (firma con o sin master_profile)."""
    import inspect

    params = inspect.signature(builder).parameters
    if "master_profile" in params:
        return builder(meta, master_profile=master_profile)
    return builder(meta)


def _participant_data_lines(master_profile: Dict[str, Any]) -> str:
    """Bloque de datos generales del participante desde perfil maestro."""
    mp = master_profile or {}
    tipo = _slot(mp.get("tipo"), "Persona moral")
    if tipo.lower() in {"moral", "persona moral", "pm"}:
        tipo = "Persona moral"
    fields = [
        ("Razón social o denominación", mp.get("razon_social")),
        ("RFC", mp.get("rfc")),
        (
            "Domicilio fiscal",
            mp.get("domicilio_fiscal") or mp.get("domicilio"),
        ),
        (
            "Representante legal",
            mp.get("representante_legal") or mp.get("representante"),
        ),
        ("Teléfono", mp.get("telefono")),
        ("Correo electrónico", mp.get("email")),
        ("Tipo de persona", tipo),
    ]
    lines = []
    for label, val in fields:
        display = _slot(val, "No registrado en perfil maestro")
        lines.append(f"- **{label}:** {display}")
    return "\n".join(lines)


def _body_anexo_ii(doc_metadata: Dict[str, Any]) -> str:
    """Manifiesto de conformidad con las bases (pliego|ANEXO_II)."""
    blob = _legal_blob(doc_metadata)
    invitacion = ""
    if re.search(r"(?i)copia.*invitaci[oó]n|integrar.*invitaci[oó]n", blob):
        invitacion = (
            "Declaro que, en su caso, se integra a este escrito la copia de la invitación "
            "o convocatoria que ampara el presente procedimiento, conforme a lo señalado en "
            "las bases.\n\n"
        )
    return (
        "**Bajo protesta de decir verdad**, manifiesto que **conozco, acepto y me sujeto** "
        "al contenido de las bases del concurso, sus anexos y, en su caso, a las respuestas "
        "emitidas en la junta de aclaraciones.\n\n"
        "Manifiesto que la documentación e información presentada por mi representada es "
        "veraz, auténtica y corresponde fielmente a su situación jurídica, fiscal y de "
        "capacidad para participar en el procedimiento.\n\n"
        f"{invitacion}"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )


def _body_anexo_iii(
    doc_metadata: Dict[str, Any],
    *,
    master_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Datos generales del participante (pliego|ANEXO_III)."""
    data_block = _participant_data_lines(master_profile or {})
    return (
        "**DATOS GENERALES DEL PARTICIPANTE**\n\n"
        f"{data_block}\n\n"
        "**Bajo protesta de decir verdad**, manifiesto que los datos anteriores son ciertos "
        "y corresponden a la situación actual de mi representada.\n\n"
        "Manifiesto que la empresa cuenta con los activos, personal, infraestructura, "
        "solvencia económica y capacidad material necesarios para la producción, suministro "
        "o prestación del objeto del concurso, en los términos exigidos en las bases.\n\n"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )


def _body_anexo_iv(doc_metadata: Dict[str, Any]) -> str:
    """Carta en papel membretado de la empresa (pliego|ANEXO_IV)."""
    return (
        "Por medio del presente escrito, en **papel membretado** de mi representada, "
        "**presento formalmente** la documentación y propuesta correspondiente al "
        "procedimiento de referencia, conforme a lo establecido en las bases del concurso.\n\n"
        "Manifiesto que los bienes y/o servicios ofertados cumplen con las especificaciones "
        "técnicas, requisitos de calidad y condiciones aplicables señaladas en las bases y, "
        "en su caso, en la junta de aclaraciones.\n\n"
        "Sin otro particular, quedo a sus órdenes."
    )


def _body_anexo_viii(doc_metadata: Dict[str, Any]) -> str:
    """Manifiesto de conformidad y aceptación de multas/sanciones (pliego|ANEXO_VIII)."""
    blob = _legal_blob(doc_metadata)
    multa_tail = ""
    if re.search(r"(?i)multa|sanci[oó]n|pena\s+convencional", blob):
        multa_tail = " en los términos y montos previstos en las bases y la normatividad aplicable"
    return (
        "**Bajo protesta de decir verdad**, manifiesto que **conozco y acepto** el contenido "
        "de las bases del concurso, sus anexos y, en su caso, las aclaraciones emitidas.\n\n"
        "**En caso de resultar adjudicado**, manifiesto que acepto las multas, penas "
        f"convencionales y sanciones administrativas que correspondan{multa_tail} "
        "en caso de incumplimiento del contrato, retraso en la entrega de los bienes "
        "y/o servicios, o cualquier otra causa prevista en las bases.\n\n"
        "Manifiesto que mi representada cumplirá en tiempo y forma con las obligaciones "
        "contractuales derivadas del procedimiento.\n\n"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )


OBRA_TABULAR_DEDUPE_KEYS = frozenset({"obra|T1", "obra|T2"})

_DEFAULT_T1_COLUMNS = (
    "NOMBRE",
    "UBICACIÓN FÍSICA",
    "PROPIEDAD",
    "CANTIDAD",
)

_DEFAULT_T2_COLUMNS = (
    "CONTRATANTE",
    "DOMICILIO Y TELÉFONO",
    "DESCRIPCIÓN DE LA OBRA",
    "IMPORTE DEL CONTRATO",
    "AVANCE FINANCIERO (%)",
    "FECHA DE TERMINACIÓN",
)


def is_obra_tabular_annex(req_label: str = "", dedupe: str = "") -> bool:
    """True si el anexo obra es formato tabular (no carta administrativa)."""
    key = dedupe or pliego_format_dedupe_key(req_label)
    return key in OBRA_TABULAR_DEDUPE_KEYS


def _extract_t1_table_columns(blob: str) -> List[str]:
    """Infiere columnas del Anexo T-1 desde snippet de inventario (fallback universal)."""
    text = str(blob or "")
    m = re.search(
        r"(?i)anexo\s+t[\s_.-]*1[^\n]{0,180}(nombre[^\n]{0,220})",
        text,
    )
    segment = m.group(0) if m else text[:280]
    found: List[str] = []
    for label, pat in (
        ("NOMBRE", r"(?i)\bnombre\b"),
        ("UBICACIÓN FÍSICA", r"(?i)ubicaci[oó]n\s+f[ií]sica"),
        ("PROPIEDAD", r"(?i)\bpropiedad\b"),
        ("CANTIDAD", r"(?i)\bcantidad\b"),
        ("MARCA", r"(?i)\bmarca\b"),
        ("MODELO", r"(?i)\bmodelo\b"),
    ):
        if re.search(pat, segment) and label not in found:
            found.append(label)
    if "NOMBRE" in found and len(found) >= 3:
        return found
    return list(_DEFAULT_T1_COLUMNS)


def _extract_t2_table_columns(blob: str) -> List[str]:
    """Infiere columnas del Anexo T-2 desde snippet de inventario (fallback universal)."""
    text = str(blob or "")
    m = re.search(
        r"(?i)anexo\s+t[\s_.-]*2[^\n]{0,420}(contratante[^\n]{0,320})",
        text,
    )
    segment = m.group(0) if m else text[:420]
    found: List[str] = []
    for label, pat in (
        ("CONTRATANTE", r"(?i)\bcontratante\b"),
        ("DOMICILIO Y TELÉFONO", r"(?i)domicilio.*tel[eé]fono|tel[eé]fono.*domicilio"),
        ("DESCRIPCIÓN DE LA OBRA", r"(?i)descripci[oó]n.*obra"),
        ("IMPORTE DEL CONTRATO", r"(?i)importe.*contrato"),
        ("AVANCE FINANCIERO (%)", r"(?i)avance.*financ"),
        ("FECHA DE TERMINACIÓN", r"(?i)fecha.*termin"),
    ):
        if re.search(pat, segment) and label not in found:
            found.append(label)
    if "CONTRATANTE" in found and len(found) >= 4:
        return found
    return list(_DEFAULT_T2_COLUMNS)


def _contratos_rows_from_profile(
    master_profile: Optional[Dict[str, Any]],
) -> List[List[str]]:
    """Filas de contratos de obra solo desde perfil/sesión (sin inventar obras)."""
    mp = master_profile or {}
    rows: List[List[str]] = []

    def _append_from_dict(item: Dict[str, Any]) -> None:
        rows.append(
            [
                _slot(item.get("contratante") or item.get("cliente") or item.get("nombre")),
                _slot(
                    item.get("domicilio_telefono")
                    or item.get("domicilio")
                    or item.get("telefono")
                ),
                _slot(
                    item.get("descripcion_obra")
                    or item.get("descripcion")
                    or item.get("obra")
                ),
                _slot(item.get("importe") or item.get("monto") or item.get("importe_contrato")),
                _slot(item.get("avance_financiero") or item.get("avance") or item.get("porcentaje_avance")),
                _slot(
                    item.get("fecha_terminacion")
                    or item.get("terminacion")
                    or item.get("fecha_fin")
                ),
            ]
        )

    for key in (
        "contratos_obra",
        "relacion_contratos",
        "contratos",
        "contratos_vigentes",
    ):
        block = mp.get(key)
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    _append_from_dict(item)
        elif isinstance(block, dict):
            vals = block.get("value")
            if isinstance(vals, list):
                for item in vals:
                    if isinstance(item, dict):
                        mapped = {
                            "contratante": item.get("contratante") or item.get("cliente"),
                            "domicilio_telefono": item.get("domicilio_telefono")
                            or item.get("domicilio"),
                            "descripcion_obra": item.get("descripcion_obra")
                            or item.get("objeto"),
                            "importe": item.get("importe") or item.get("monto"),
                            "avance_financiero": item.get("avance_financiero"),
                            "fecha_terminacion": item.get("fecha_terminacion"),
                        }
                        if item.get("contrato_id") and not mapped.get("descripcion_obra"):
                            mapped["descripcion_obra"] = f"Contrato {item.get('contrato_id')}"
                        _append_from_dict(mapped)
    return rows


def _maquinaria_rows_from_profile(
    master_profile: Optional[Dict[str, Any]],
) -> List[List[str]]:
    """Filas de maquinaria solo desde perfil/sesión (sin inventar equipos)."""
    mp = master_profile or {}
    rows: List[List[str]] = []
    for key in ("maquinaria", "equipos", "equipo_maquinaria", "maquinaria_equipo"):
        block = mp.get(key)
        if not isinstance(block, list):
            continue
        for item in block:
            if isinstance(item, dict):
                rows.append(
                    [
                        _slot(item.get("nombre") or item.get("equipo")),
                        _slot(item.get("ubicacion") or item.get("ubicacion_fisica")),
                        _slot(item.get("propiedad") or item.get("tenencia")),
                        _slot(item.get("cantidad"), "1"),
                    ]
                )
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                rows.append([str(c) for c in item[:4]])
    return rows


def _markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    """Tabla markdown compatible con ``parse_markdown_table`` en DOCX."""
    hdr = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = [hdr, sep]
    for row in rows:
        padded = list(row) + [""] * (len(headers) - len(row))
        body.append("| " + " | ".join(padded[: len(headers)]) + " |")
    return "\n".join(body)


def _body_obra_t1_maquinaria(
    doc_metadata: Dict[str, Any],
    *,
    master_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Relación de maquinaria y equipo (obra pública, Anexo T-1) — solo formato tabular."""
    mp = master_profile or {}
    blob = _legal_blob(doc_metadata)
    cols = _extract_t1_table_columns(str(doc_metadata.get("req_snippet") or blob))
    obra = _slot(
        doc_metadata.get("objeto_obra")
        or doc_metadata.get("tender_name")
        or doc_metadata.get("concurso_label"),
        "[Objeto de la obra conforme bases]",
    )
    contratista = _slot(mp.get("razon_social"), "[Razón social del contratista]")
    vigencia = _slot(doc_metadata.get("fecha") or doc_metadata.get("fecha_corta"), "[Fecha]")
    concurso = _slot(
        doc_metadata.get("concurso_label") or doc_metadata.get("tender_name"),
        "[Número de concurso/licitación]",
    )
    fecha = _slot(doc_metadata.get("fecha"), "[Fecha del documento]")

    rows = _maquinaria_rows_from_profile(mp)
    if not rows:
        placeholder = ["[Consignar]", "[Consignar]", "[Consignar]", "[Consignar]"]
        rows = [placeholder[: len(cols)]]

    parts = [
        "**ANEXO T-1 — RELACIÓN DE MAQUINARIA Y EQUIPO DE CONSTRUCCIÓN**\n",
        f"**OBRA:** {obra}",
        f"**CONTRATISTA:** {contratista}",
        f"**VIGENCIA:** {vigencia}",
        f"**CONCURSO:** {concurso}",
        f"**FECHA:** {fecha}\n",
        _markdown_table(cols, rows),
        "\nLa maquinaria y equipo listados se presentan conforme al Anexo T-1 de las bases. "
        "Los soportes de propiedad, arrendamiento o disponibilidad se acreditan en el "
        "documento correspondiente del expediente, sin duplicar aquí información de otros "
        "anexos (T-2, T-6 u otros).",
        "\n**Bajo protesta de decir verdad**, manifiesto que la relación anterior es veraz "
        "y que los equipos estarán disponibles para la ejecución de la obra en caso de "
        "resultar adjudicado.",
        "\nProtesto lo necesario.",
    ]
    return "\n".join(parts)


def _body_obra_t2_contratos(
    doc_metadata: Dict[str, Any],
    *,
    master_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Relación de contratos de obras vigentes (obra pública, Anexo T-2) — formato tabular."""
    mp = master_profile or {}
    snippet = str(doc_metadata.get("req_snippet") or "")
    cols = _extract_t2_table_columns(snippet or _legal_blob(doc_metadata))
    contratista = _slot(mp.get("razon_social"), "[Razón social del contratista]")
    concurso = _slot(
        doc_metadata.get("concurso_label") or doc_metadata.get("tender_name"),
        "[Número de concurso/licitación]",
    )
    fecha = _slot(doc_metadata.get("fecha"), "[Fecha del documento]")

    rows = _contratos_rows_from_profile(mp)
    if not rows:
        rows = [["[Consignar]"] * len(cols)]

    parts = [
        "**ANEXO T-2 — RELACIÓN DE CONTRATOS DE OBRAS**\n",
        f"**CONTRATISTA:** {contratista}",
        f"**CONCURSO EN CURSO:** {concurso}",
        f"**FECHA:** {fecha}\n",
        _markdown_table(cols, rows),
        "\nRelación presentada conforme al Anexo T-2 de las bases, respecto de contratos "
        "de obra **vigentes a la fecha de recepción y apertura de proposiciones** "
        "celebrados con la administración pública o con particulares.",
        "\n**Bajo protesta de decir verdad**, manifiesto que **no se incluye** en esta "
        "relación el procedimiento licitatorio en curso ni obras que aún no estén "
        "formalmente contratadas; solo constan contratos reales y verificables de mi "
        "representada.",
        "\nVerifico que ninguna fila describe la obra o concurso objeto de la presente "
        "licitación en curso.",
        "\nLos soportes documentales (actas, contratos, finiquitos) se presentan en los "
        "anexos de acreditación correspondientes, sin duplicar aquí información de otros "
        "formatos (T-b-2 u otros).",
        "\nProtesto lo necesario.",
    ]
    return "\n".join(parts)


def _body_obra_t8_privacidad(doc_metadata: Dict[str, Any]) -> str:
    """Carta breve de aceptación del aviso de privacidad (obra pública, Anexo T-8)."""
    lic = _slot(doc_metadata.get("concurso_label") or doc_metadata.get("tender_name"), "el procedimiento de referencia")
    return (
        "**Bajo protesta de decir verdad**, manifiesto que he revisado y entendido el "
        "**Aviso de Privacidad** anexo a la convocatoria y bases de "
        f"{lic}, y que **acepto** su contenido para efectos de mi participación "
        "en el procedimiento.\n\n"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )


def _body_obra_t3_contrato(doc_metadata: Dict[str, Any]) -> str:
    """Conformidad con el modelo de contrato (obra pública, Anexo T-3)."""
    return (
        "**Bajo protesta de decir verdad**, manifiesto que he revisado el **Modelo de Contrato** "
        "publicado en las bases del concurso y que **firmo de conformidad** su contenido, "
        "obligándome a suscribir el contrato en los términos que resulten del procedimiento "
        "en caso de resultar adjudicado.\n\n"
        "Lo anterior, en cumplimiento del Anexo T-3 de las bases.\n\n"
        "Protesto lo necesario."
    )


def _body_obra_t4_bases(doc_metadata: Dict[str, Any]) -> str:
    """Bases y requisitos firmados de conformidad (obra pública, Anexo T-4)."""
    blob = _legal_blob(doc_metadata)
    invitacion = ""
    if re.search(r"(?i)copia.*invitaci[oó]n|integrar.*invitaci[oó]n", blob):
        invitacion = (
            "Declaro que, en su caso, se integra a este escrito la copia de la invitación "
            "o convocatoria que ampara el presente procedimiento, conforme a lo señalado en "
            "las bases.\n\n"
        )
    return (
        "**Bajo protesta de decir verdad**, manifiesto que **conozco, acepto y me sujeto** "
        "al contenido de las **Bases y Requisitos** del concurso, sus anexos técnicos y "
        "económicos y, en su caso, a las respuestas emitidas en la junta de aclaraciones.\n\n"
        "Manifiesto que la documentación e información presentada por mi representada es "
        "veraz, auténtica y corresponde fielmente a su situación jurídica, fiscal y de "
        "capacidad para participar en el procedimiento.\n\n"
        f"{invitacion}"
        "Lo anterior, en cumplimiento del Anexo T-4 de las bases.\n\n"
        "Protesto lo necesario."
    )


def _body_obra_t5_visita(doc_metadata: Dict[str, Any]) -> str:
    """Acta de visita/junta o manifestación de obtención (obra pública, Anexo T-5)."""
    blob = _legal_blob(doc_metadata)
    if re.search(r"(?i)no\s+haber\s+asistido|en\s+caso\s+de\s+no\s+haber\s+asistido", blob):
        return (
            "**Bajo protesta de decir verdad**, manifiesto que **no asistí** a la visita al "
            "sitio de los trabajos y/o a la junta de aclaraciones, y que **obtendré** la copia "
            "del acta correspondiente expedida por un servidor público designado por la "
            "convocante, conforme a lo establecido en las bases del concurso.\n\n"
            "Lo anterior, en cumplimiento del Anexo T-5 de las bases.\n\n"
            "Protesto lo necesario."
        )
    return (
        "**Bajo protesta de decir verdad**, manifiesto que **asistí** a la visita al sitio de "
        "los trabajos y/o a la junta de aclaraciones del procedimiento, o que **anexo** la "
        "constancia o acta correspondiente expedida por la convocante, conforme a lo "
        "establecido en las bases.\n\n"
        "Lo anterior, en cumplimiento del Anexo T-5 de las bases.\n\n"
        "Protesto lo necesario."
    )


def _body_obra_tb2_experiencia(doc_metadata: Dict[str, Any]) -> str:
    """Formato T-b 2: experiencia técnica acreditada con actas (obra pública)."""
    return (
        "**Formato T-b 2 — Documentación de experiencia y capacidad técnica**\n\n"
        "**Bajo protesta de decir verdad**, anexo la documentación que comprueba la "
        "experiencia y capacidad técnica de mi representada en trabajos similares, con "
        "por lo menos una obra acreditada mediante copia de **acta de cierre administrativo**, "
        "**entrega-recepción** o documento afín, en los términos del formato T-b 2 de las bases.\n\n"
        "Manifiesto que los montos y características de las obras referidas corresponden a "
        "obras reales ejecutadas por mi representada y son consistentes con la relación de "
        "contratos y demás anexos de la presente proposición.\n\n"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )


def _body_obra_e4_programa(doc_metadata: Dict[str, Any]) -> str:
    """Programas de obra en Gantt (obra pública, Anexo E-4)."""
    return (
        "Por medio del presente, **presento** los programas de obra exigidos en las bases:\n\n"
        "a) **Programa de Obra físico** en barras de Gantt, por conceptos o por partidas.\n\n"
        "b) **Programa de Obra Físico de Montos Mensuales** en barras de Gantt, por conceptos "
        "o por partidas.\n\n"
        "Manifiesto que los programas se elaboraron conforme al calendario de ejecución de la "
        "obra y a los plazos establecidos en las bases del concurso.\n\n"
        "Lo anterior, en cumplimiento del Anexo E-4 de las bases.\n\n"
        "Protesto lo necesario."
    )


def is_short_acceptance_annex(
    req_label: str = "",
    req_desc: str = "",
    req_snippet: str = "",
) -> bool:
    """Anexos que solo requieren carta corta de aceptación/firma (no redactar política completa)."""
    blob = " ".join((req_label, req_desc, req_snippet)).lower()
    if re.search(r"aviso\s+de\s+privacidad", blob):
        return True
    if re.search(
        r"anexar\s+el\s+documento\s+debidamente\s+firmad",
        blob,
    ) and re.search(r"aceptaci[oó]n\s+o\s+negativa", blob):
        return True
    if re.search(r"anexo\s+t[\s_-]*8\b", blob) and "privacidad" in blob:
        return True
    return False


def strip_redundant_signature_blocks(text: str) -> str:
    """
    Elimina bloques de firma duplicados del cuerpo LLM antes del cierre formal DOCX.
    """
    if not text or not str(text).strip():
        return text or ""
    lines = str(text).splitlines()
    cut: Optional[int] = None
    for i, line in enumerate(lines):
        low = line.lower().strip()
        if re.search(
            r"(?i)^(firma\s+del\s+representante|representante\s+legal\s+de|"
            r"a\s*t\s*e\s*n\s*t\s*a\s*m\s*e\s*n\s*t\s*e)",
            low,
        ):
            cut = i
            break
    if cut is not None and cut > 0:
        trimmed = "\n".join(lines[:cut]).strip()
        if trimmed:
            return trimmed
    return text


def _body_anexo_xii(doc_metadata: Dict[str, Any]) -> str:
    """Conformidad con catálogo/modelo de presentación (pliego|ANEXO_XII)."""
    blob = _legal_blob(doc_metadata)
    uom = ""
    if re.search(r"(?i)unidad\s+de\s+medida|cantidad\s+distinta|no\s+podr[aá]\s+ofertar", blob):
        uom = (
            "Manifiesto que **no ofertaré unidad de medida, cantidad o formato distinto** "
            "al señalado en las bases y catálogo de conceptos del concurso, salvo lo "
            "expresamente permitido por la convocante.\n\n"
        )
    return (
        "**Bajo protesta de decir verdad**, manifiesto que la propuesta y el catálogo de "
        "conceptos se presentan **conforme al modelo y criterios** señalados en las bases "
        "del concurso.\n\n"
        f"{uom}"
        "Manifiesto que los conceptos, descripciones y estructura de presentación respetan "
        "el formato de referencia publicado en las bases, sin alteraciones no autorizadas.\n\n"
        "**En caso de resultar adjudicado**, me comprometo a suministrar los bienes y/o "
        "servicios conforme a dicho catálogo y especificaciones.\n\n"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )


def _body_anexo_v(doc_metadata: Dict[str, Any]) -> str:
    pct = "el porcentaje establecido en las bases del concurso"
    if re.search(r"\b10\s*%|\bdiez\s+por\s+ciento\b", str(doc_metadata.get("req_snippet") or ""), re.I):
        pct = "el 10% del valor total de las cantidades mínimas adjudicadas, en los términos de las bases"
    return (
        "Que, por medio del presente escrito y **bajo protesta de decir verdad**, manifiesto que "
        "los bienes y/o servicios ofertados por mi representada en el procedimiento de referencia "
        "cumplen con los estándares de calidad, especificaciones técnicas y características mínimas "
        "establecidas en las Bases del Concurso y, en su caso, en la Junta de Aclaraciones.\n\n"
        f"Asimismo, me comprometo formalmente a otorgar a favor de la convocante la Garantía de "
        f"Cumplimiento por {pct}, respondiendo por la buena calidad de los productos y por la "
        "inexistencia de vicios ocultos.\n\n"
        "Sin otro particular por el momento, quedo a sus órdenes."
    )


def _body_anexo_vi() -> str:
    return (
        "**Bajo protesta de decir verdad**, manifiesto que mi representada cumplirá con cada uno "
        "de los requisitos solicitados en las bases y, en su caso, en la junta de aclaraciones, "
        "y que cuenta con capacidad amplia y suficiente para la entrega de los bienes o servicios "
        "objeto del concurso.\n\n"
        "**En caso de resultar adjudicado**, me comprometo a cumplir en tiempo y forma con las "
        "obligaciones derivadas del procedimiento."
    )


def _body_anexo_vii() -> str:
    return (
        "**Bajo protesta de decir verdad**, manifiesto que mi representada se abstendrá, por sí "
        "o por interpósita persona, de adoptar conductas para inducir o alterar las evaluaciones "
        "de las propuestas, el resultado del procedimiento u otros aspectos que otorguen "
        "condiciones más ventajosas respecto de los demás participantes.\n\n"
        "Declaro que la proposición de mi representada fue elaborada de manera independiente, "
        "con apego a las bases y a la normatividad aplicable, y que la información y documentación "
        "presentada es veraz, íntegra y auténtica, conduciéndonos con legalidad, honradez y buena "
        "fe durante el procedimiento de contratación y, en su caso, durante la ejecución contractual.\n\n"
        "Sin otro particular, quedo a sus órdenes."
    )


def _body_anexo_ix() -> str:
    return (
        "**Bajo protesta de decir verdad**, manifiesto que **en caso de resultar adjudicado** "
        "el presente concurso, los bienes y/o servicios objeto del mismo estarán asegurados "
        "por cuenta y riesgo de mi representada hasta su recepción final por parte de los "
        "responsables designados por la convocante, en el entendido de que dicha responsabilidad "
        "se liberará una vez que la convocante emita la aceptación por escrito de los bienes "
        "y servicios entregados.\n\n"
        "Lo anterior, en estricto apego a lo solicitado en las bases del concurso.\n\n"
        "Sin otro particular, reitero mi compromiso y quedo a sus gratas órdenes."
    )


def _body_anexo_x() -> str:
    return (
        "Que, **bajo protesta de decir verdad**, manifiesto que **no se actualiza ninguno** de "
        "los supuestos señalados en el **artículo 49, fracción IX**, de la Ley General de "
        "Responsabilidades Administrativas; es decir, declaro que, antes de la celebración de "
        "contratos de adquisiciones, arrendamientos, enajenaciones o prestación de servicios, "
        "no desempeño empleo, cargo o comisión en el servicio público, o que, en su caso, con la "
        "formalización del contrato correspondiente no se actualiza un conflicto de interés.\n\n"
        "Asimismo, en mi calidad de representante legal, extiendo esta manifestación respecto de "
        "los socios o accionistas que ejercen control sobre la sociedad, garantizando que ninguno "
        "de ellos se encuentra en dicha situación.\n\n"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )


def _extract_legal_context_from_blob(blob: str) -> Dict[str, str]:
    """
    Extrae referencias normativas citadas en bases/snippet (universal, sin fijar convocante).

    Returns:
        Diccionario con claves opcionales: ley_adquisiciones, articulos_adquisiciones,
        ley_responsabilidades_local, lgra_articulos_rango, codigo_fiscal_clausula.
    """
    text = str(blob or "")
    out: Dict[str, str] = {}

    m_ley = re.search(
        r"(?i)(Ley\s+de\s+Adquisiciones[^\n\.;]{5,160}?)(?:\.|;|\n|$)",
        text,
    )
    if m_ley:
        out["ley_adquisiciones"] = re.sub(r"\s+", " ", m_ley.group(1)).strip(" .;")

    m_arts = re.search(
        r"(?i)art[ií]culos?\s+([\dº°oO,\sy]+)\s+de\s+(?:la\s+)?Ley\s+de\s+Adquisiciones",
        text,
    )
    if m_arts:
        out["articulos_adquisiciones"] = re.sub(r"\s+", " ", m_arts.group(1)).strip(" .")

    m_lgra_local = re.search(
        r"(?i)(Ley\s+de\s+Responsabilidades\s+Administrativas\s+del\s+Estado[^\n\.;]{0,80})",
        text,
    )
    if m_lgra_local:
        out["ley_responsabilidades_local"] = re.sub(
            r"\s+", " ", m_lgra_local.group(1)
        ).strip(" .;")

    if re.search(r"(?i)art[ií]culos?\s+6[5-9]|art[ií]culos?\s+7[0-2]", text):
        out["lgra_articulos_rango"] = "65, 66, 67, 68, 69, 70, 71 y 72"

    m_cf = re.search(
        r"(?i)(fracciones?\s+[IVXLC]+(?:\s+a\s+la\s+[IVXLC]+)?\s+del\s+art[ií]culo\s+57\s*Bis[^\n\.;]{0,80})",
        text,
    )
    if m_cf:
        out["codigo_fiscal_clausula"] = re.sub(r"\s+", " ", m_cf.group(1)).strip(" .;")
    elif re.search(r"(?i)57\s*Bis", text):
        out["codigo_fiscal_clausula"] = (
            "los supuestos de las fracciones señaladas en las bases respecto del artículo 57 Bis "
            "del código fiscal aplicable"
        )

    if re.search(
        r"(?i)protecci[oó]n\s+de\s+datos\s+personales|lgpdp|datos\s+personales\s+en\s+posesi[oó]n",
        text,
    ):
        out["datos_personales"] = "1"

    return out


def _body_anexo_xi(doc_metadata: Dict[str, Any]) -> str:
    """Manifiesto de no vinculación con otros concursantes (familia pliego|ANEXO_XI)."""
    blob = _legal_blob(doc_metadata)
    legal = _extract_legal_context_from_blob(blob)

    ley_adq = legal.get("ley_adquisiciones") or (
        "la normatividad en materia de adquisiciones, arrendamientos, enajenaciones "
        "y contratación de servicios aplicable conforme a las bases del concurso"
    )
    arts_adq = legal.get("articulos_adquisiciones")
    if arts_adq:
        impedimento = (
            f"en los supuestos previstos en los artículos {arts_adq} de {ley_adq}"
        )
    else:
        impedimento = (
            f"en los supuestos de impedimento legal señalados en {ley_adq} "
            "y en las bases del concurso"
        )

    parts = [
        "**Bajo protesta de decir verdad**, manifiesto que mi representada **no se encuentra "
        "vinculada** por algún socio o asociado común con otros concursantes, ni mantiene "
        "relaciones profesionales, laborales o de negocios con ninguno de los demás "
        "participantes en el procedimiento.\n\n",
        f"Asimismo, manifiesto que no estoy legalmente impedido para participar {impedimento}.\n\n",
        f"Declaro que conozco las disposiciones vigentes de {ley_adq}.\n\n",
        "Manifiesto que mi representada es de nacionalidad mexicana y se encuentra constituida "
        "conforme a las leyes de los Estados Unidos Mexicanos.\n\n",
        "Manifiesto que participamos en condiciones de equidad, sin que nuestra propuesta "
        "implique ventajas ilícitas respecto de otros interesados.\n\n",
    ]

    lgra_rango = legal.get("lgra_articulos_rango")
    if lgra_rango or re.search(r"(?i)ley general de responsabilidades", blob):
        lgra_federal = "la Ley General de Responsabilidades Administrativas"
        lgra_local = legal.get("ley_responsabilidades_local")
        if lgra_rango and lgra_local:
            parts.append(
                f"Manifiesto que conozco lo establecido en los artículos {lgra_rango} "
                f"de {lgra_federal} y de {lgra_local}.\n\n"
            )
        elif lgra_rango:
            parts.append(
                f"Manifiesto que conozco lo establecido en los artículos {lgra_rango} "
                f"de {lgra_federal} y la normatividad señalada en las bases del concurso.\n\n"
            )
        else:
            parts.append(
                f"Manifiesto que conozco lo establecido en {lgra_federal} y la normatividad "
                "en materia de responsabilidades administrativas señalada en las bases.\n\n"
            )

    if legal.get("datos_personales"):
        parts.append(
            "Acepto el tratamiento de datos personales y de la información solicitada en el "
            "concurso, conforme a la Ley General de Protección de Datos Personales en Posesión "
            "de Sujetos Obligados y a lo señalado en las bases del procedimiento.\n\n"
        )

    if legal.get("codigo_fiscal_clausula"):
        parts.append(
            f"Manifiesto que no se actualiza ninguno de {legal['codigo_fiscal_clausula']}.\n\n"
        )

    parts.append(
        "**En caso de resultar adjudicado**, manifiesto que aceptaré las multas y sanciones "
        "que correspondan en caso de incumplimiento del contrato y/o retraso en la entrega de "
        "los bienes y/o servicios objeto del procedimiento.\n\n"
        "Lo anterior, en cumplimiento de lo establecido en las bases del concurso.\n\n"
        "Protesto lo necesario."
    )
    return "".join(parts)


_ASUNTO_BY_DEDUPE: Dict[str, str] = {
    "obra|T1": "Relación de maquinaria y equipo de construcción",
    "obra|T2": "Relación de contratos de obras vigentes",
    "obra|T3": "Modelo de Contrato (firmado de conformidad)",
    "obra|T4": "Bases y Requisitos (firmados de conformidad)",
    "obra|T5": "Acta de Visita y Junta de Aclaraciones",
    "obra|E4": "Programas de Obra en Gantt",
    "obra|T8_PRIVACIDAD": "Aceptación del Aviso de Privacidad",
    "obra|T8": "Aceptación del Aviso de Privacidad",
    "pliego|ANEXO_II": "Manifiesto de conformidad con las bases del concurso",
    "pliego|ANEXO_III": "Datos generales del participante",
    "pliego|ANEXO_IV": "Carta en papel membretado de la empresa",
    "pliego|ANEXO_VIII": "Manifiesto de conformidad y aceptación de multas y sanciones",
    "pliego|ANEXO_X": "Anexo X — Manifestación en hoja membretada (conflicto de interés, art. 49 LGRA)",
    "pliego|ANEXO_XI": (
        "Manifiesto de no vinculación por socio o asociado común y de relaciones con otros concursantes"
    ),
    "pliego|ANEXO_XII": "Conformidad con el catálogo y modelo de presentación de la propuesta",
}


def resolve_letter_asunto(req_label: str, req_snippet: str = "", dedupe: str = "") -> str:
    """Título/asunto legible para carta (sin truncar por nombre de archivo)."""
    key = dedupe or pliego_format_dedupe_key(req_label)
    if key in _ASUNTO_BY_DEDUPE:
        return _ASUNTO_BY_DEDUPE[key]
    snippet = str(req_snippet or "").strip()
    m = re.search(
        r"(?i)((?:anexo|formato|carta|manifiesto|declaraci[oó]n)[^\n\.;]{8,160})",
        snippet,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip(" .;")[:180]
    cleaned = re.sub(r"\.docx$", "", req_label, flags=re.I)
    cleaned = re.sub(r"_+", " ", cleaned).strip()
    return cleaned[:180] if cleaned else "Documento administrativo"


_CLAUSE_BY_DEDUPE: Dict[str, Any] = {
    "obra|T1": _body_obra_t1_maquinaria,
    "obra|T2": _body_obra_t2_contratos,
    "obra|T3": _body_obra_t3_contrato,
    "obra|T4": _body_obra_t4_bases,
    "obra|T5": _body_obra_t5_visita,
    "obra|T-B-2": _body_obra_tb2_experiencia,
    "obra|E4": _body_obra_e4_programa,
    "obra|T8_PRIVACIDAD": _body_obra_t8_privacidad,
    "obra|T8": _body_obra_t8_privacidad,
    "pliego|ANEXO_II": _body_anexo_ii,
    "pliego|ANEXO_III": _body_anexo_iii,
    "pliego|ANEXO_IV": _body_anexo_iv,
    "pliego|ANEXO_V": _body_anexo_v,
    "pliego|ANEXO_VI": lambda _m: _body_anexo_vi(),
    "pliego|ANEXO_VII": lambda _m: _body_anexo_vii(),
    "pliego|ANEXO_VIII": _body_anexo_viii,
    "pliego|ANEXO_IX": lambda _m: _body_anexo_ix(),
    "pliego|ANEXO_X": lambda _m: _body_anexo_x(),
    "pliego|ANEXO_XI": _body_anexo_xi,
    "pliego|ANEXO_XII": _body_anexo_xii,
}


def try_build_clause_markdown(
    *,
    req_label: str,
    master_profile: Dict[str, Any],
    doc_metadata: Dict[str, Any],
    req_snippet: str = "",
) -> Optional[str]:
    """
    Devuelve cuerpo markdown determinístico si el requisito encaja en una familia conocida.

    Returns:
        Markdown del cuerpo (sin encabezado DOCX duplicado) o None.
    """
    meta = dict(doc_metadata or {})
    meta["req_snippet"] = req_snippet
    dedupe = pliego_format_dedupe_key(req_label)
    builder = _CLAUSE_BY_DEDUPE.get(dedupe)
    if not builder:
        return None
    body = _call_clause_builder(builder, meta, master_profile)
    if is_obra_tabular_annex(req_label, dedupe):
        return body
    asunto = resolve_letter_asunto(req_label, req_snippet, dedupe)
    concurso = _slot(meta.get("concurso_label") or meta.get("tender_name"))
    header_lines = [f"**Asunto:** {asunto[:180]}"]
    if concurso:
        header_lines.append(f"**Concurso:** {concurso[:180]}")
    return (
        "\n".join(header_lines)
        + "\n\n"
        + _comparecencia_block(master_profile, meta)
        + "\n\n"
        + body
    )


def build_administrative_letter_markdown(
    *,
    req_nombre: str,
    req_desc: str = "",
    req_snippet: str = "",
    master_profile: Dict[str, Any],
    doc_metadata: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Carta administrativa universal: cláusula determinística o fallback acotado sin truncar snippets.
    """
    enriched = resolve_letter_session_metadata(
        session_state,
        req_snippet=req_snippet or req_desc,
    )
    meta = {**doc_metadata, **{k: v for k, v in enriched.items() if v}}
    clause = try_build_clause_markdown(
        req_label=req_nombre,
        master_profile=master_profile,
        doc_metadata=meta,
        req_snippet=req_snippet or req_desc,
    )
    if clause:
        return clause

    rep = _slot(
        master_profile.get("representante_legal") or master_profile.get("representante"),
        "el representante legal",
    )
    razon = _slot(master_profile.get("razon_social"), "la empresa concursante")
    rfc = _slot(master_profile.get("rfc"), "S/D")
    domicilio = _slot(
        master_profile.get("domicilio_fiscal") or master_profile.get("domicilio"),
        "domicilio fiscal registrado ante el SAT",
    )
    licitacion = _slot(meta.get("concurso_label") or meta.get("tender_name"), "la presente licitación")
    titulo = _slot(req_nombre, "Documento administrativo")
    contexto = _slot(req_desc or req_snippet)
    contexto_line = ""
    if contexto:
        short = re.sub(r"\s+", " ", contexto)[:400].rsplit(" ", 1)[0] + "…" if len(contexto) > 400 else contexto
        contexto_line = (
            f"\n\nEn relación con el requisito «{titulo[:120]}», manifiesto lo siguiente conforme "
            f"a las bases: {short}"
        )

    return (
        f"**Asunto:** {titulo[:160]}\n\n"
        f"{_comparecencia_block(master_profile, meta)}"
        f"{contexto_line}\n\n"
        f"**Bajo protesta de decir verdad**, manifiesto que la información contenida en el "
        f"presente documento es verídica, que actúo con facultades suficientes para obligar a "
        f"**{razon}** (RFC **{rfc}**), con domicilio en {domicilio}, y que nos comprometemos a "
        f"cumplir las obligaciones derivadas de las bases aplicables al procedimiento "
        f"«{licitacion}».\n\n"
        f"Sin otro particular, quedo a sus órdenes."
    )
