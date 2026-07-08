"""
Extracción universal de formatos/anexos del pliego desde el corpus de bases (§5–8).

Complementa CCC/compliance cuando el LLM dejó ítems como informativos o faltantes.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.services.document_deliverable_filter import (
    _ADMIN_FORMAT_TEMPLATE_RE,
    _PLIEGO_POST_ADJUDICATION_ANEXO_RE,
    is_corporate_physical_credential_for_panel,
    is_economic_writer_domain,
    is_formats_panel_noise,
    is_pliego_causal_or_prohibition,
    is_procedural_noise_not_deliverable,
)
from app.services.junta_bases_corpus import extract_template_codes

_PLIEGO_SECTION_LINE_RE = re.compile(
    r"(?m)^\s*((?:5|6|7|8)\.\d+\.?-?)\s+(.{12,420}?)"
    r"(?=\n\s*(?:[5678]\.\d+|\d+\.\d+)|\n\n|---\s*PÁGINA|\Z)",
    re.DOTALL,
)

_ANEXO_INVENTORY_BLOCK_RE = re.compile(
    r"(?is)\banexo\s+"
    r"(?P<num>XIII|XIV|XV|XII|XI|IX|VIII|VII|VI|IV|III|II|I|X|V|\d{1,2})(?![IVXLCDM])"
    r"\s*[,:\.]?\s*"
    r"(?P<body>.{12,6500}?)"
    r"(?=\s*\banexo\s+(?:XIII|XIV|XV|XII|XI|IX|VIII|VII|VI|IV|III|II|I|X|V|\d{1,2})(?![IVXLCDM])\b|\Z)"
)

_GENERABLE_PROPOSAL_RE = re.compile(
    r"(?i)\b("
    r"propuesta\s+t[eé]cnica|propuesta\s+econ[oó]mica|"
    r"proposici[oó]n\s+t[eé]cnica|proposici[oó]n\s+econ[oó]mica|"
    r"cat[aá]logo\s+de\s+conceptos|listado\s+de\s+insumos|"
    r"relaci[oó]n\s+de\s+trabajos|relaci[oó]n\s+de\s+contratos|"
    r"relaci[oó]n\s+de\s+maquinaria|programa\s+calendarizado|"
    r"programa\s+de\s+utilizaci[oó]n|capacidad\s+financiera|"
    r"relaci[oó]n\s+y\s+an[aá]lisis\s+de\s+los\s+costos|"
    r"programa\s+de\s+suministro"
    r")\b"
)


def _label_from_pliego_line(section: str, body: str) -> str:
    text = re.sub(r"\s+", " ", f"{section}. {body}".strip())
    text = re.sub(r"\(Documento que[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .,;")
    if len(text) > 200:
        text = text[:200].rsplit(" ", 1)[0] + "…"
    return text or "Formato del pliego"


def is_pliego_generable_format_line(line: str) -> bool:
    """
    True si el requisito numerado es plantilla/anexo a elaborar (no credencial solo física).
    """
    text = re.sub(r"\s+", " ", str(line or "").strip())
    if len(text) < 12:
        return False
    if re.search(r"(?i)\bno\s+aplica\s+este\s+punto\b", text):
        return False
    if is_pliego_causal_or_prohibition(text, "", text):
        return False
    if is_procedural_noise_not_deliverable(text, "", text):
        return False
    if is_corporate_physical_credential_for_panel(text, "", text):
        if _ADMIN_FORMAT_TEMPLATE_RE.search(text) and re.search(
            r"(?i)\b(carta|declaraci[oó]n|manifestaci[oó]n|listado\s+de\s+verificaci[oó]n)\b",
            text,
        ):
            return True
        return False
    if _ADMIN_FORMAT_TEMPLATE_RE.search(text):
        return True
    if extract_template_codes(text):
        return True
    if is_economic_writer_domain(text, "", text):
        return True
    if _GENERABLE_PROPOSAL_RE.search(text):
        return True
    return False


_ARABIC_TO_ROMAN_ANEXO = {
    "10": "X",
    "11": "XI",
    "12": "XII",
    "13": "XIII",
    "14": "XIV",
    "15": "XV",
}

_OBRA_FILENAME_ALIASES: tuple[tuple[str, str], ...] = (
    (r"modelo\s+de\s+contrato|modelo\s+contrato", "obra|T3"),
    (r"bases\s+y\s+requisitos.*firmad|firmad.*conformidad.*bases", "obra|T4"),
    (r"visita\s+del\s+sitio|visita\s+al\s+sitio|acta.*visita|junta\s+de\s+aclaraciones.*acta", "obra|T5"),
    (r"cumplimiento.*obligaciones\s+contractuales", "obra|T6"),
    (r"partes.*obra.*subcontr|subcontrataci[oó]n", "obra|T7"),
    (r"relaci[oó]n.*contratos.*obras", "obra|T2"),
    (r"acreditaci[oó]n.*propiedad.*maquinaria", "obra|T1_ACRED"),
    (r"relaci[oó]n.*maquinaria|maquinaria.*equipo", "obra|T1"),
    (r"carta.*compromiso.*proposici", "obra|E1"),
    (
        r"anexo\s+ae|propuesta\s+econ[oó]mica|cat[aá]logo.*conceptos|"
        r"presupuesto.*conceptos|anexo\s+e[\s_.-]*2",
        "obra|E2",
    ),
    (r"an[aá]lisis.*precios|precios\s+unitarios|tabla.*precios", "obra|E3"),
    (r"utilidad\s+propuesta|anexo\s+e[\s_.-]*3\s*e|cargo\s+por\s+utilidad", "obra|E3E"),
    (r"programa.*obra.*gantt|gantt|programa.*montos\s+mensuales", "obra|E4"),
    (r"anexo.*materiales|cotizaciones.*materiales", "obra|E5"),
    (r"capital\s+contable|liquidez\s+comprometida|cuadro\s+de\s+finiquito", "obra|T_B_SOLVENCIA"),
)

_OBRA_TE_ANNEXO_BLOCK_RE = re.compile(
    r"\banexo\s+"
    r"(?P<code>t[\s_.-]*(?:b[\s_.-]*)?\d{1,2}|e[\s_.-]*\d{1,2})"
    r"\b\s*"
    r"(?P<body>.{12,6500}?)"
    r"(?=\banexo\s+(?:t[\s_.-]*(?:b[\s_.-]*)?\d{1,2}|e[\s_.-]*\d{1,2})\b|\Z|---\s*PÁGINA|\n\s*II\.-)",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_label_blob(label: str) -> str:
    """Texto uniforme para reglas de anexo (guión/underscore → espacio)."""
    norm = re.sub(r"[_\-.]+", " ", str(label or "").strip().lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return re.sub(r"(?i)\.docx$", "", norm).strip()


def obra_te_dedupe_key(label: str) -> Optional[str]:
    """
    Clave estable obra|T{n}/obra|E{n} desde nombre de archivo o etiqueta de bases.

    Returns:
        Clave ``obra|…`` o None si no aplica a anexos T/E de obra pública.
    """
    norm = _normalize_label_blob(label)

    if re.search(r"aviso\s+de\s+privacidad", norm):
        return "obra|T8_PRIVACIDAD"

    m_tb = re.search(r"(?i)\b(?:anexo|formato)\s+t[\s]*b[\s]*(\d+)\b", norm)
    if m_tb:
        return f"obra|T-B-{m_tb.group(1)}"

    m_t = re.search(r"(?i)\b(?:anexo|formato)\s+t[\s]*(\d{1,2})\b", norm)
    if m_t:
        return f"obra|T{int(m_t.group(1))}"

    m_e = re.search(r"(?i)\b(?:anexo|formato)\s+e[\s]*3[\s]*e\b", norm)
    if m_e:
        return "obra|E3E"

    m_e = re.search(r"(?i)\b(?:anexo|formato)\s+e[\s]*(\d{1,2})\b", norm)
    if m_e:
        return f"obra|E{int(m_e.group(1))}"

    for pat, key in _OBRA_FILENAME_ALIASES:
        if re.search(pat, norm):
            return key

    for code in extract_template_codes(str(label or "")):
        cu = code.upper().replace("-", "")
        if re.match(r"^T\d", cu):
            if cu == "T8" and re.search(r"privacidad", norm):
                return "obra|T8_PRIVACIDAD"
            return f"obra|{cu}"
        if re.match(r"^E\d", cu):
            return f"obra|{cu}"

    return None


def _anexo_key_from_label(label: str) -> Optional[str]:
    obra = obra_te_dedupe_key(label)
    if obra:
        return obra
    raw = str(label or "")
    m = re.search(
        r"(?i)\banexo[\s_.-]+"
        r"(XIII|XIV|XV|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I|\d{1,2})"
        r"(?=[_.\W]|$)",
        raw,
    )
    if m:
        num = m.group(1).upper()
        if num.isdigit():
            num = _ARABIC_TO_ROMAN_ANEXO.get(num, num)
        return f"pliego|ANEXO_{num}"
    return None


def _valid_anexo_inventory_body(num: str, body: str) -> bool:
    """Descarta menciones laterales al anexo (domicilio, modelo técnico) sin plantilla."""
    b = re.sub(r"\s+", " ", str(body or "").strip()).lower()
    if len(b) < 18:
        return False
    if re.match(r"^[\)\(\s,;:\-]+", b):
        return False
    if re.search(r"^\)\s*,", b):
        return False
    if re.search(r"^de las bases,\s*respecto", b):
        return False
    if re.search(r"^modelo que podr", b) and not re.search(
        r"vinculado|socio|asociado\s+comun|manifiesto firmado", b
    ):
        return False
    n = str(num or "").upper()
    if n == "IV" and not re.search(r"carta|membretad", b[:140]):
        return False
    if n == "XI" and not re.search(r"vinculado|socio|asociado\s+comun|manifiesto firmado", b[:220]):
        return False
    return True


def _canonical_anexo_label(num: str, body: str) -> str:
    """Etiqueta corta «Anexo N: …» a partir del párrafo de inventario en bases."""
    short = re.sub(r"\s+", " ", str(body or "").strip())
    short = re.sub(
        r"(?i)^el\s+anexo\s+[ivx\d]+\s+de\s+las\s+presentes\s+bases,\s*es\s+",
        "",
        short,
    )
    short = re.split(r"[.;]\s", short, maxsplit=1)[0].strip(" ,;")
    if len(short) > 130:
        short = short[:130].rsplit(" ", 1)[0] + "…"
    roman = str(num or "").strip().upper()
    return f"Anexo {roman}: {short}" if short else f"Anexo {roman}"


def _sobre_for_anexo(num: str, body: str) -> str:
    """Clasificación de sobre por anexo (universal, sin licitación fija)."""
    n = str(num or "").strip().upper()
    blob = f"{n} {body}".lower()
    if n in ("I", "X", "XII") or re.search(
        r"(?i)\b(proposici[oó]n\s+econ[oó]mica|propuesta\s+econ[oó]mica|"
        r"modelo de c[oó]mo podr[aá] presentarla|ejemplo de c[oó]mo podr[aá]|"
        r"cat[aá]logo|precios\s+unitarios|conflicto\s+de\s+inter[eé]s)\b",
        blob,
    ):
        return "sobre_2_economico"
    if n == "III" or re.search(r"(?i)\bdatos\s+generales\s+del\s+participante\b", blob):
        return "requisitos_legales"
    return "sobre_1_tecnico"


def _canonical_obra_te_label(code: str, body: str) -> str:
    """Etiqueta «Anexo T-n: …» / «Anexo E-n: …» desde inventario de bases."""
    short = re.sub(r"\s+", " ", str(body or "").strip())
    short = re.split(r"[.;]\s", short, maxsplit=1)[0].strip(" ,;")
    if len(short) > 130:
        short = short[:130].rsplit(" ", 1)[0] + "…"
    code_disp = re.sub(r"\s+", "-", str(code or "").strip().upper())
    code_disp = re.sub(r"[-]+", "-", code_disp)
    return f"Anexo {code_disp}: {short}" if short else f"Anexo {code_disp}"


def _sobre_for_obra_te_code(code: str, body: str) -> str:
    """Sobre CompraNet inferido para anexos T/E de obra pública."""
    c = re.sub(r"[\s_.-]+", "", str(code or "").lower())
    if c.startswith("e"):
        return "sobre_3_economico"
    if re.search(r"(?i)propuesta\s+econ|cat[aá]logo|precios|programa", body):
        return "sobre_3_economico"
    return "sobre_1_administrativo"


def _valid_obra_te_inventory_body(code: str, body: str) -> bool:
    """Descarta menciones laterales o fragmentos de párrafo (no inventario real)."""
    b = re.sub(r"\s+", " ", str(body or "").strip())
    if len(b) < 18:
        return False
    if re.match(r"^[\),;:\.]+\s*", b):
        return False
    if re.match(r"(?i)^de las bases de licitaci[oó]n\.?$", b):
        return False
    code_norm = re.sub(r"[\s_.-]+", "", str(code or "").lower())
    if code_norm.startswith("tb"):
        m_num = re.search(r"tb(\d+)", code_norm)
        if m_num:
            n = m_num.group(1)
            if not re.search(rf"(?i)\bt[\s_-]*b[\s_-]*{n}\b", b):
                return False
    return True


def extract_obra_te_annexes_from_bases_corpus(corpus: Any) -> List[Dict[str, Any]]:
    """
    Inventario de anexos T-1…T-8 y E-1…E-5 descritos en bases de obra pública.
    """
    combined = str(getattr(corpus, "combined", "") or "")
    if not combined.strip():
        return []

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for m in _OBRA_TE_ANNEXO_BLOCK_RE.finditer(combined):
        code = re.sub(r"\s+", "-", m.group("code").strip().upper())
        code = re.sub(r"[-]+", "-", code)
        body = re.sub(r"\s+", " ", m.group("body")).strip()
        body_head = body[:360]
        if len(body_head) < 12 or not _valid_obra_te_inventory_body(code, body_head):
            continue
        label = _canonical_obra_te_label(code, body_head)
        key = obra_te_dedupe_key(label) or pliego_format_dedupe_key(label)
        if key in seen:
            continue
        seen.add(key)
        sobre = _sobre_for_obra_te_code(code, body_head)
        out.append(
            {
                "id": f"obra-{code.lower().replace('-', '')}",
                "nombre_canonico": label,
                "nombre": label,
                "snippet_representativo": _pliego_snippet_for_panel(body_head),
                "dedupe_key": key,
                "tipo": "generar",
                "tipo_accion_final": "generar",
                "tipo_accion_propuesto": "generar",
                "confidence": 0.94,
                "sobre_clasificado": sobre,
                "from_document_inventory": True,
                "provenance_ui": {
                    "source": "bases_corpus",
                    "reason": "obra_te_annex_inventory",
                    "section": f"Anexo {code}",
                },
            }
        )
    return out


_E3E_INVENTORY_RE = re.compile(
    r"(?is)\banexo\s+e[\s_.-]*3\s*e\b\s*(?P<body>.{20,1800}?)(?=\banexo\s+e[\s_.-]*[34]\b|\Z|---\s*PÁGINA)",
)


def extract_obra_e3e_annex_from_bases_corpus(corpus: Any) -> List[Dict[str, Any]]:
    """
    Inventario granular del formato E-3 E (utilidad %), separado del paquete APU E-3.
    """
    combined = str(getattr(corpus, "combined", "") or "")
    if not combined.strip():
        return []
    m = _E3E_INVENTORY_RE.search(combined)
    if not m:
        if "utilidad propuesta" not in combined.lower():
            return []
        idx = combined.lower().find("utilidad propuesta")
        body = combined[max(0, idx - 80) : idx + 400]
    else:
        body = m.group("body")
    body_head = re.sub(r"\s+", " ", str(body or "")).strip()[:360]
    if len(body_head) < 20:
        return []
    label = "Anexo E-3 E: Utilidad propuesta para el concurso"
    return [
        {
            "id": "obra-e3e",
            "nombre_canonico": label,
            "nombre": label,
            "snippet_representativo": _pliego_snippet_for_panel(body_head),
            "dedupe_key": "obra|E3E",
            "tipo": "generar",
            "tipo_accion_final": "generar",
            "tipo_accion_propuesto": "generar",
            "confidence": 0.92,
            "sobre_clasificado": "sobre_3_economico",
            "from_document_inventory": True,
            "provenance_ui": {
                "source": "bases_corpus",
                "reason": "obra_e3e_format_inventory",
                "section": "Anexo E-3 E",
            },
        }
    ]


def extract_pliego_anexos_from_bases_corpus(corpus: Any) -> List[Dict[str, Any]]:
    """
    Inventario de anexos I–XV (y arábigos) descrito en el corpus de bases.
    Excluye anexos post-adjudicación (XIII–XV) y ruido de panel.
    """
    combined = str(getattr(corpus, "combined", "") or "")
    if not combined.strip():
        return []

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for m in _ANEXO_INVENTORY_BLOCK_RE.finditer(combined):
        num = m.group("num").upper()
        body = re.sub(r"\s+", " ", m.group("body")).strip()
        body_head = body[:360]
        if len(body_head) < 12 or not _valid_anexo_inventory_body(num, body_head):
            continue
        if _PLIEGO_POST_ADJUDICATION_ANEXO_RE.search(f"Anexo {num}"):
            continue
        label = _canonical_anexo_label(num, body_head)
        if is_formats_panel_noise(label, "", body_head):
            continue
        key = _anexo_key_from_label(label) or pliego_format_dedupe_key(label)
        if key in seen:
            continue
        seen.add(key)
        sobre = _sobre_for_anexo(num, body)
        out.append(
            {
                "id": f"anexo-{num.lower()}",
                "nombre_canonico": label,
                "nombre": label,
                "snippet_representativo": _pliego_snippet_for_panel(body_head),
                "tipo": "generar",
                "tipo_accion_final": "generar",
                "tipo_accion_propuesto": "generar",
                "confidence": 0.93,
                "sobre_clasificado": sobre,
                "from_document_inventory": True,
                "provenance_ui": {
                    "source": "bases_corpus",
                    "reason": "anexo_inventory_block",
                    "section": f"Anexo {num}",
                },
            }
        )
    return out


def _pliego_snippet_for_panel(body: str) -> str:
    """Fragmento corto para filtros UI (evita arrastrar §7 u otras secciones del PDF)."""
    return re.sub(r"\s+", " ", str(body or ""))[:280]


def pliego_format_dedupe_key(label: str) -> str:
    """Fusión por código de forma/anexo o firma de propuesta."""
    raw = str(label or "").strip()
    norm = _normalize_label_blob(raw)

    obra_key = obra_te_dedupe_key(label)
    if obra_key:
        return obra_key

    if re.search(r"(?i)carta\s*compromiso", norm):
        if re.search(r"proposici", norm):
            return "obra|E1"
        if re.search(r"precio", norm):
            return "pliego|carta_compromiso_precios"
        return "pliego|ANEXO_VI"

    anexo_key = _anexo_key_from_label(label)
    if anexo_key:
        return anexo_key
    for pat, key in (
        (r"declaraci[oó]n.*integridad|integridad.*declaraci[oó]n", "pliego|declaracion_integridad"),
        (r"garant[ií]a.*calidad|calidad.*productos", "pliego|ANEXO_V"),
        (r"carta.*aseguramiento|aseguramiento.*bienes", "pliego|ANEXO_IX"),
        (r"multa.*sancion|sancion.*incumplimiento", "pliego|ANEXO_VIII"),
        (r"no\s+conflicto|conflicto.*inter[eé]s", "pliego|ANEXO_X"),
        (r"vinculado.*socio|socio.*asociado", "pliego|ANEXO_XI"),
        (r"compromiso.*requisitos|cumplir.*requisitos\s+solicitados", "pliego|ANEXO_VI"),
        (r"conformidad con las bases", "pliego|ANEXO_II"),
        (r"datos generales del participante", "pliego|ANEXO_III"),
        (r"cat[aá]logo.*conceptos|ejemplo.*presentarla", "pliego|ANEXO_XII"),
        (r"propuesta\s+t[eé]cnica", "pliego|propuesta_tecnica"),
        (r"propuesta\s+econ", "pliego|propuesta_economica"),
        (r"proposici[oó]n\s+econ", "pliego|propuesta_economica"),
        (r"cat[aá]logo\s+de\s+conceptos", "pliego|catalogo_conceptos"),
        (r"aviso\s+de\s+privacidad", "obra|T8_PRIVACIDAD"),
        (r"relaci[oó]n.*costos.*luminarias", "pliego|analisis_costos"),
        (r"programa\s+de\s+suministro", "pliego|programa_suministro"),
        (r"listado\s+de\s+insumos", "pliego|listado_insumos"),
        (r"capacidad\s+financiera", "pliego|capacidad_financiera"),
    ):
        if re.search(pat, norm):
            return key
    codes = extract_template_codes(label)
    if codes:
        cu = codes[0].replace("-", "").upper()
        if re.match(r"^T\d", cu):
            if cu == "T8" and re.search(r"privacidad", norm):
                return "obra|T8_PRIVACIDAD"
            return f"obra|{cu}"
        if re.match(r"^E\d", cu):
            return f"obra|{cu}"
        return f"pliego|{cu}"
    toks = [t for t in norm.split() if len(t) > 3][:5]
    return "pliego|" + "_".join(toks) if toks else norm[:48]


def extract_pliego_generables_from_bases_corpus(corpus: Any) -> List[Dict[str, Any]]:
    """Lista ítems generables: inventario de anexos + §5–8 del corpus indexado."""
    from app.services.compliance_consolidation_service import classify_deliverable_sobre
    from app.services.junta_bases_corpus import BasesCorpus, primary_bases_segments

    if isinstance(corpus, BasesCorpus) and len(corpus.segments) > 1:
        primary_segs = primary_bases_segments(corpus)
        if primary_segs and len(primary_segs) < len(corpus.segments):
            corpus = BasesCorpus(
                session_id=corpus.session_id,
                segments=primary_segs,
                filenames=[fn for fn, _ in primary_segs],
            )

    out: List[Dict[str, Any]] = list(extract_obra_te_annexes_from_bases_corpus(corpus))
    seen: Set[str] = {pliego_format_dedupe_key(r["nombre_canonico"]) for r in out}
    for row in extract_obra_e3e_annex_from_bases_corpus(corpus):
        key = str(row.get("dedupe_key") or pliego_format_dedupe_key(row.get("nombre_canonico") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    for row in extract_pliego_anexos_from_bases_corpus(corpus):
        key = pliego_format_dedupe_key(row["nombre_canonico"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)

    combined = str(getattr(corpus, "combined", "") or "")
    if not combined.strip():
        return out

    for m in _PLIEGO_SECTION_LINE_RE.finditer(combined):
        section = m.group(1)
        body = re.sub(r"\s+", " ", m.group(2)).strip()
        raw = f"{section}. {body}"
        if not is_pliego_generable_format_line(raw):
            continue
        label = _label_from_pliego_line(section, body)
        if is_formats_panel_noise(label, "", body):
            continue
        key = pliego_format_dedupe_key(label)
        if key in seen:
            continue
        seen.add(key)
        sobre = classify_deliverable_sobre(label, body)
        out.append(
            {
                "id": f"pliego-{len(out)+1:02d}",
                "nombre_canonico": label,
                "nombre": label,
                "snippet_representativo": body[:600],
                "tipo": "generar",
                "tipo_accion_final": "generar",
                "tipo_accion_propuesto": "generar",
                "confidence": 0.88,
                "sobre_clasificado": sobre,
                "provenance_ui": {
                    "source": "bases_corpus",
                    "reason": "pliego_section_generable",
                    "section": section,
                },
            }
        )
    return out
