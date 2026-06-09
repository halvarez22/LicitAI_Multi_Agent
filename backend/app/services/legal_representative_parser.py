import re
from typing import Any, Dict, List, Optional, Tuple


NAME_PATTERN = r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ]+){1,5})"

# Cargos societarios que suelen ir entre «como … a» y el nombre humano (no son representante).
_CORPORATE_ROLE_TOKEN = (
    r"comisario|administrador(?:a)?(?:\s+[úu]nico)?|presidente(?:e)?|vicepresidente|"
    r"tesorero|secretario|vocal|gerente|director(?:a)?(?:\s+general)?|apoderado(?:\s+legal)?|"
    r"delegado(?:\s+especial)?|representante(?:\s+legal)?|consejero|síndico|sindico|"
    r"prosecretario|pro\s*tesorero|mesa\s+directiva"
)

_ROLE_WORDS = frozenset({
    "como", "comisario", "administrador", "administradora", "presidente", "presidenta",
    "vicepresidente", "tesorero", "secretario", "secretaria", "vocal", "gerente", "director",
    "directora", "apoderado", "apoderada", "delegado", "representante", "consejero",
    "sindico", "síndico", "prosecretario", "unico", "único", "general", "legal", "especial",
    "mesa", "directiva", "cargo", "nuevo", "nueva",
})


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


_IDENTITY_LABEL_SPLIT_RE = re.compile(
    r"\s+(?:CURP|RFC|R\.F\.C\.|CLAVE\s+DE\s+ELECTOR|CLAVE\s+ELECTOR|"
    r"IDENTIFICACI[OÓ]N(?:\s+OFICIAL)?|N[UÚ]MERO\s+DE\s+IDENTIFICACI[OÓ]N|"
    r"DOMICILIO|NACIONALIDAD|ESTADO\s+CIVIL|INE)\b",
    re.IGNORECASE,
)


def strip_identity_labels_from_person_name(name: str) -> str:
    """
    Quita etiquetas de identidad que el OCR/LLM pegan al nombre (p. ej. «… Martínez CURP»).
    Patrón universal: cualquier expediente con bloques CURP/RFC/INE en la misma línea.
    """
    s = _normalize_spaces(name or "")
    if not s:
        return s
    return _normalize_spaces(_IDENTITY_LABEL_SPLIT_RE.split(s, maxsplit=1)[0])


def _trim_name_candidate(candidate: str) -> str:
    """Quita cola legal capturada por regex con IGNORECASE (p. ej. «con facultades», «comparece»)."""
    s = _normalize_spaces(candidate)
    if not s:
        return s
    cut = re.split(
        r"\s+(?:con|quien|comparece|para|en\s+su|y\s+declara|quien\s+acepta|mediante|otorga)\b",
        s,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return strip_identity_labels_from_person_name(cut)


def _looks_like_person_name(candidate: str) -> bool:
    """Evita tomar razones sociales u otros encabezados como nombre de persona."""
    u = (candidate or "").strip().upper()
    if len(u) < 6:
        return False
    if any(x in u for x in (" S.A.", " S. A.", " SAPI", " S DE ", " DE C.V", " SOCIEDAD ", " ANÓNIMA ", " ANONIMA ")):
        return False

    lower_c = (candidate or "").strip().lower()
    if lower_c.startswith("para que ") or lower_c.startswith("a fin de ") or lower_c.startswith("a efecto de "):
        return False
    if lower_c.startswith("como "):
        return False

    bad_words = {
        "quien", "acepta", "dicho", "nombramiento", "otorga", "declara", "manifiesta", "acuerda",
        "comparece", "otorgar", "poder", "para", "que", "ocurra", "ante", "notario", "notaria",
        "notaría", "publico", "público", "escritura", "delegado", "especial", "facultad", "facultades",
        "sociedad", "secretario", "tesorero", "vocal", "mediante", "virtud", "efecto", "fin",
    }
    tokens = re.findall(r"[a-záéíóúñ]+", lower_c)
    if not tokens or len(tokens) < 2:
        return False
    if any(word in bad_words for word in tokens):
        return False
    if all(word in _ROLE_WORDS for word in tokens):
        return False
    if any(word in _ROLE_WORDS for word in tokens) and not any(
        word not in _ROLE_WORDS and word not in bad_words for word in tokens
    ):
        return False
    if any(word in lower_c for word in ("notario publico", "notario público", "para que ocurra")):
        return False

    return True


def is_plausible_representative_name(candidate: str) -> bool:
    """API pública para validar nombres de representante antes de persistir en perfil."""
    return _looks_like_person_name(candidate)


def detect_legal_representative(text: str) -> Dict[str, Any]:
    """
    Extrae representante legal con heurística determinista y evidencia.

    Principios (cualquier acta / escritura societaria mexicana razonable):

    - Solo **patrones léxico-estructurales** reutilizables (administrador único,
      delegado especial, representante legal, etc.).
    - **Prohibido** codificar nombres propios, RFC, denominaciones o redacción de
      un solo cliente o un solo formato de acta.
    - Si conviven varias señales (p. ej. apoderado en acta fundadora y delegado
      en asamblea/escritura reciente), se elige por **orden de confianza** del
      patrón y posición en el contexto, no por memorizar un expediente.

    Recorre todas las coincidencias y elige la de mayor ``confidence``; en empate,
    la que aparece antes en el texto (coherente con contexto ordenado asamblea→acta).
    """
    clean = _normalize_spaces(text)
    if not clean:
        return {
            "found": False,
            "representative": None,
            "confidence": 0.0,
            "strategy": "deterministic_regex",
            "evidence": "",
            "trigger": "none",
        }

    patterns: List[Dict[str, Any]] = [
        # Asamblea: "convienen en nombrar como Nuevo Administrador Único a NOMBRE"
        {
            "trigger": "nombrar_como_nuevo_admin_unico",
            "confidence": 0.99,
            "regex": rf"(?:convienen\s+en\s+)?nombrar(?:\s+como)?\s+(?:nuevo\s+)?administrador(?:a)?\s+[úu]nico\s+a\s+(?:la\s+|el\s+)?(?:c\.\s*)?{NAME_PATTERN}",
        },
        # Asamblea: "se nombra/nombrará como Administrador Único al/a la NOMBRE"
        {
            "trigger": "se_nombra_admin_unico",
            "confidence": 0.98,
            "regex": rf"se\s+nombra(?:r[aá])?\s+(?:como\s+)?(?:nuevo\s+)?administrador(?:a)?\s+[úu]nico\s+(?:al?\s+|la\s+)?(?:c\.\s*)?{NAME_PATTERN}",
        },
        # Escrituras de asamblea: delegado especial / presidente (prevalecen sobre apoderados del acta antigua)
        {
            "trigger": "c_comparece_delegado_especial",
            "confidence": 0.98,
            "regex": rf"(?:el\s+)?(?:c\.\s*){NAME_PATTERN}\s*,\s*(?:en\s+)?(?:su\s+)?car[aá]cter\s+de\s+delegado\s+especial",
        },
        {
            "trigger": "nombre_coma_caracter_delegado_especial",
            "confidence": 0.98,
            "regex": rf"{NAME_PATTERN}\s*,\s*(?:en\s+)?(?:su\s+)?car[aá]cter\s+de\s+delegado\s+especial",
        },
        # OCR con saltos entre "C. NOMBRE" y "carácter de delegado especial" (escritura de asamblea)
        {
            "trigger": "c_nombre_hasta_caracter_delegado_especial",
            "confidence": 0.981,
            "regex": rf"(?:el\s+)?(?:c\.\s*){NAME_PATTERN}[\s\S]{{0,360}}?car[aá]cter\s+de\s+delegado\s+especial",
        },
        {
            "trigger": "delegado_especial_el_c_nombre",
            "confidence": 0.975,
            "regex": rf"delegado\s+especial(?:\s+de\s+la\s+sociedad)?\s*,\s*(?:el\s+)(?:c\.\s*)?{NAME_PATTERN}",
        },
        {
            "trigger": "presidente_asamblea_el_c",
            "confidence": 0.965,
            "regex": rf"presidente\s+de\s+la\s+asamblea\w*\s*,\s*(?:el\s+)?(?:c\.\s*)?{NAME_PATTERN}",
        },
        {
            "trigger": "presidente_mesa_directiva_el_c",
            "confidence": 0.964,
            "regex": rf"presidente\s+de\s+la\s+mesa\s+directiva\w*\s*,\s*(?:el\s+)?(?:c\.\s*)?{NAME_PATTERN}",
        },
        # «se designa como Comisario a NOMBRE» — el cargo no es el representante.
        {
            "trigger": "se_designa_como_cargo_a",
            "confidence": 0.97,
            "regex": (
                rf"se\s+designa\s+como\s+(?:{_CORPORATE_ROLE_TOKEN})\s+"
                rf"(?:a|al)\s+(?:la\s+|el\s+)?(?:c\.\s*)?{NAME_PATTERN}"
            ),
        },
        {
            "trigger": "nombrar_como_cargo_a",
            "confidence": 0.97,
            "regex": (
                rf"(?:convienen\s+en\s+)?nombrar(?:\s+como)?\s+(?:{_CORPORATE_ROLE_TOKEN})\s+"
                rf"(?:a|al)\s+(?:la\s+|el\s+)?(?:c\.\s*)?{NAME_PATTERN}"
            ),
        },
        {
            "trigger": "se_designa",
            "confidence": 0.95,
            "regex": (
                rf"(?:se\s+designa(?!\s+como\s+(?:{_CORPORATE_ROLE_TOKEN}))\s*"
                rf"|designando\s+para\s+tal\s+cargo\s+a\s+)"
                rf"(?:la|el|al|a)?\s*(?:c\.\s*)?{NAME_PATTERN}"
            ),
        },
        # Escritura pública / acta: "ADMINISTRADOR ÚNICO, recayendo (dicho) nombramiento en el señor NOMBRE"
        {
            "trigger": "admin_unico_recayendo_nombramiento",
            "confidence": 0.93,
            "regex": rf"(?:administrador(?:a)?\s+[úu]nico)\s*,\s*recayendo\s+(?:dicho\s+|el\s+)?nombramiento\s+en\s+(?:el|la)?\s*(?:c\.\s*)?(?:señor|señora)\s+{NAME_PATTERN}",
        },
        {
            "trigger": "admin_unico_nombramiento_en_c",
            "confidence": 0.91,
            "regex": rf"(?:administrador(?:a)?\s+[úu]nico)\s*,\s*recayendo\s+(?:dicho\s+|el\s+)?nombramiento\s+en\s+(?:el|la)?\s*c\.\s*{NAME_PATTERN}",
        },
        {
            "trigger": "administrador_unico",
            "confidence": 0.9,
            "regex": rf"(?:administrador(?:a)?\s+[úu]nico(?:\s+es)?|nombramiento\s+de\s+administrador(?:a)?\s+[úu]nico)\s*(?:[:\-]|\s+de\s+)?(?:la|el|al|a)?\s*(?:c\.\s*)?{NAME_PATTERN}",
        },
        {
            "trigger": "representante_legal",
            "confidence": 0.85,
            "regex": rf"(?:representante\s+legal|apoderado\s+legal)\s*(?:[:\-]|\s+)?(?:la|el|al|a)?\s*(?:c\.\s*)?{NAME_PATTERN}",
        },
    ]

    best: Optional[Tuple[float, int, Dict[str, Any]]] = None
    for item in patterns:
        for m in re.finditer(item["regex"], clean, flags=re.IGNORECASE):
            groups = [g for g in m.groups() if g]
            candidate = _trim_name_candidate(groups[-1] if groups else m.group(0))
            if not _looks_like_person_name(candidate):
                continue
            evidence = _normalize_spaces(m.group(0))[:320]
            payload = {
                "found": True,
                "representative": candidate,
                "confidence": item["confidence"],
                "strategy": "deterministic_regex",
                "evidence": evidence,
                "trigger": item["trigger"],
            }
            key = (item["confidence"], -m.start())
            if best is None or key > (best[0], best[1]):
                best = (item["confidence"], -m.start(), payload)

    if best:
        return best[2]

    return {
        "found": False,
        "representative": None,
        "confidence": 0.0,
        "strategy": "deterministic_regex",
        "evidence": "",
        "trigger": "none",
    }


_CIF_DOC_MARKERS = re.compile(
    r"c[eé]dula\s+de\s+identificaci[oó]n\s+fiscal|constancia\s+de\s+situaci[oó]n\s+fiscal",
    re.IGNORECASE,
)

# Bloque típico SAT (CIF / constancia): etiquetas "Nombre(s)", "Primer Apellido", "Segundo Apellido"
_CIF_NOMBRE_APPELLIDOS = re.compile(
    r"Nombre\s*\(s\)\s*:\s*"
    r"(?P<nom>(?:[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ]+)(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ]+)*)"
    r"\s*Primer\s+Apellido\s*:\s*"
    r"(?P<p1>[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ]+)"
    r"\s*Segundo\s+Apellido\s*:\s*"
    r"(?P<p2>[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ]+)",
    re.IGNORECASE,
)


_RFC_MORAL_RE = re.compile(r"\b([A-ZÑ&]{3}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE)


def _rfc_prefix_letter_len(rfc: str) -> int:
    """Cuenta letras (y &) al inicio del RFC antes del primer dígito."""
    u = (rfc or "").strip().upper()
    n = 0
    for ch in u:
        if "A" <= ch <= "Z" or ch in "Ñ&":
            n += 1
        else:
            break
    return n


def _score_rfc_moral_local_context(upper_text: str, start: int, end: int) -> int:
    """Puntuación heurística: RFC de empresa cerca de etiquetas SAT / razón social."""
    lo = max(0, start - 260)
    hi = min(len(upper_text), end + 260)
    w = upper_text[lo:hi].lower()
    score = 0
    positives = (
        "razon social",
        "razón social",
        "denominacion",
        "denominación",
        "contribuyente",
        "persona moral",
        "sociedad",
        "r.f.c",
        "rfc:",
        " rfc ",
        "registro federal",
        "cedula de identificacion fiscal",
        "cédula de identificación fiscal",
        "constancia de situacion",
        "constancia de situación",
        "identificacion fiscal",
        "identificación fiscal",
        "datos de identificacion",
        "datos de identificación",
    )
    negatives = (
        "representante legal",
        "apoderado legal",
        "firma electronica",
        "firma electrónica",
        "credencial para votar",
        "clave de elector",
        "ine ",
    )
    for p in positives:
        if p in w:
            score += 14
    for n in negatives:
        if n in w:
            score -= 10
    return score


def resolve_rfc_persona_moral(text: str, llm_rfc: Optional[str]) -> Dict[str, Any]:
    """
    Selecciona el RFC del contribuyente persona moral cuando el texto mezcla RFC de persona física.

    En CIF/constancia/actas suele aparecer el RFC de la moral (3 letras) y el del representante (4 letras).
    El LLM a veces devuelve el segundo; esta función prioriza candidatos con patrón moral y contexto SAT.

    Args:
        text: Contexto concatenado (OCR/RAG) donde buscar RFCs.
        llm_rfc: Valor propuesto por el LLM (puede ser None o vacío).

    Returns:
        Dict con: value (RFC final o None), strategy, previous_llm, evidence_snippet, changed.
    """
    clean = _normalize_spaces(text or "")
    if not clean:
        return {
            "value": None,
            "strategy": "empty_context",
            "previous_llm": llm_rfc,
            "evidence_snippet": "",
            "changed": False,
        }

    upper = clean.upper()
    placeholders = {"", "NO ENCONTRADO", "NO ENCONTRADO.", "N/A", "...", "S/D", "SD"}

    by_rfc: Dict[str, Tuple[int, int, int]] = {}
    for m in _RFC_MORAL_RE.finditer(upper):
        val = m.group(1).upper()
        sc = _score_rfc_moral_local_context(upper, m.start(), m.end())
        prev = by_rfc.get(val)
        if prev is None or sc > prev[2] or (sc == prev[2] and m.start() < prev[0]):
            by_rfc[val] = (m.start(), m.end(), sc)

    llm_u = (llm_rfc or "").strip().upper()
    llm_norm = llm_u if llm_u not in placeholders else ""

    if not by_rfc:
        return {
            "value": llm_norm or None,
            "strategy": "llm_no_moral_rfc_pattern_in_text",
            "previous_llm": llm_rfc,
            "evidence_snippet": (clean[:280] if clean else ""),
            "changed": False,
        }

    ranked = sorted(by_rfc.items(), key=lambda kv: (-kv[1][2], kv[1][0]))
    best_rfc, (s, e, _) = ranked[0]
    evidence = clean[max(0, s - 40) : min(len(clean), e + 80)].strip()

    if not llm_norm:
        return {
            "value": best_rfc,
            "strategy": "deterministic_moral_rfc_anchor",
            "previous_llm": llm_rfc,
            "evidence_snippet": evidence[:320],
            "changed": bool(llm_rfc),
        }

    llm_prefix = _rfc_prefix_letter_len(llm_norm)
    if llm_prefix == 4 and llm_norm not in by_rfc:
        return {
            "value": best_rfc,
            "strategy": "deterministic_moral_rfc_anchor_over_fisica_llm",
            "previous_llm": llm_rfc,
            "evidence_snippet": evidence[:320],
            "changed": llm_norm != best_rfc,
        }

    if llm_prefix == 3 and llm_norm in by_rfc:
        s2, e2, _ = by_rfc[llm_norm]
        ev2 = clean[max(0, s2 - 40) : min(len(clean), e2 + 80)].strip()
        return {
            "value": llm_norm,
            "strategy": "llm_moral_rfc_confirmed_in_text",
            "previous_llm": llm_rfc,
            "evidence_snippet": ev2[:320],
            "changed": False,
        }

    if llm_prefix == 3 and llm_norm not in by_rfc:
        return {
            "value": best_rfc,
            "strategy": "deterministic_moral_rfc_anchor_llm_not_in_text",
            "previous_llm": llm_rfc,
            "evidence_snippet": evidence[:320],
            "changed": llm_norm != best_rfc,
        }

    return {
        "value": best_rfc,
        "strategy": "deterministic_moral_rfc_anchor",
        "previous_llm": llm_rfc,
        "evidence_snippet": evidence[:320],
        "changed": llm_norm != best_rfc,
    }


def is_constancia_cif_text(text: str, max_scan_chars: int = 12000) -> bool:
    """
    Indica si el texto contiene marcadores típicos de Cédula de Identificación Fiscal
    o Constancia de Situación Fiscal del SAT (primeros caracteres del documento).
    """
    clean = _normalize_spaces(text or "")
    if not clean:
        return False
    return bool(_CIF_DOC_MARKERS.search(clean[:max_scan_chars]))


def detect_cif_contribuyente_name(text: str) -> Dict[str, Any]:
    """
    Persona física: nombre completo desde etiquetas de la CIF / constancia del SAT.

    No sustituye actas societarias; solo aplica si el texto parece constancia fiscal.
    """
    clean = _normalize_spaces(text)
    if not clean or not _CIF_DOC_MARKERS.search(clean[:6000]):
        return {
            "found": False,
            "full_name": None,
            "confidence": 0.0,
            "strategy": "cif_sat_labels",
            "evidence": "",
            "trigger": "none",
        }
    m = _CIF_NOMBRE_APPELLIDOS.search(clean)
    if not m:
        return {
            "found": False,
            "full_name": None,
            "confidence": 0.0,
            "strategy": "cif_sat_labels",
            "evidence": "",
            "trigger": "none",
        }
    parts = [m.group("nom"), m.group("p1"), m.group("p2")]
    full_name = _normalize_spaces(" ".join(p for p in parts if p))
    if len(full_name) < 5:
        return {
            "found": False,
            "full_name": None,
            "confidence": 0.0,
            "strategy": "cif_sat_labels",
            "evidence": "",
            "trigger": "none",
        }
    evidence = _normalize_spaces(m.group(0))[:320]
    return {
        "found": True,
        "full_name": full_name,
        "confidence": 0.9,
        "strategy": "cif_sat_labels",
        "evidence": evidence,
        "trigger": "cif_nombre_apellidos",
    }
