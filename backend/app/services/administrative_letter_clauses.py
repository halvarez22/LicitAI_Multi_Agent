"""
Cuerpos determinísticos de cartas administrativas por familia de anexo (universal).

Sin hardcode por licitación: slots desde perfil maestro, metadatos de sesión y snippet de bases.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key


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
    cp = _extract_postal_code(domicilio)
    abbrev = _CP_ESTADO_ABREV.get(cp[:2]) if len(cp) == 5 else ""
    if abbrev and abbrev not in city:
        return f"{city}, {abbrev}"
    return city


def resolve_document_ciudad(
    master_profile: Optional[Dict[str, Any]] = None,
    domicilio: Optional[str] = None,
) -> str:
    """
    Resuelve el lugar para LUGAR Y FECHA.

    Cascada: municipio/ciudad/localidad del perfil > extracción del domicilio fiscal.
    """
    mp = master_profile or {}
    dom = str(
        domicilio or mp.get("domicilio_fiscal") or mp.get("domicilio") or ""
    ).strip()
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
                    "organismo",
                    "comite",
                )
            )
    blob += " " + str(session_state.get("bases_corpus_hint") or "")[:8000]
    blob += " " + str(req_snippet or "")

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

    comite = ""
    m_comite = re.search(
        r"(?i)(comit[eé]\s+de\s+adquisiciones[^\n\.]{0,220}|"
        r"comit[eé]\s+[^\n\.]{8,180}presente)",
        blob,
    )
    if m_comite:
        comite = re.sub(r"\s+", " ", m_comite.group(1)).strip(" .")
    elif convocante:
        comite = convocante.upper()

    proc = ""
    m_proc = re.search(
        r"(?i)((?:invitaci[oó]n|concurso|licitaci[oó]n)\s+(?:restringid[oa]|p[uú]blic[oa])?"
        r"[^\n\"]{0,120})",
        blob,
    )
    if m_proc:
        proc = re.sub(r"\s+", " ", m_proc.group(1)).strip(" .")

    destinatario = "A QUIEN CORRESPONDA:"
    if comite:
        destinatario = f"{comite.upper()}\nP R E S E N T E"

    out: Dict[str, str] = {"destinatario": destinatario}
    if convocante:
        out["convocante"] = convocante
    if proc:
        out["concurso_label"] = proc
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
