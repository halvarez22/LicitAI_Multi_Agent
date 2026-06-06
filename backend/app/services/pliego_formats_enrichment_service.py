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


def _anexo_key_from_label(label: str) -> Optional[str]:
    m = re.search(
        r"(?i)\banexo[\s_.-]+"
        r"(XIII|XIV|XV|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I|\d{1,2})"
        r"(?=[_.\W]|$)",
        str(label or ""),
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
    norm = re.sub(r"\s+", " ", raw.lower())
    if re.match(r"(?i)^carta[_\s-]*compromiso(?:\.docx)?$", raw) or re.match(
        r"(?i)^carta[_\s-]*compromiso$", norm
    ):
        return "pliego|ANEXO_VI"
    anexo_key = _anexo_key_from_label(label)
    if anexo_key:
        return anexo_key
    for pat, key in (
        (r"declaraci[oó]n.*integridad|integridad.*declaraci[oó]n", "pliego|ANEXO_VII"),
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
        (r"relaci[oó]n.*costos.*luminarias", "pliego|analisis_costos"),
        (r"programa\s+de\s+suministro", "pliego|programa_suministro"),
        (r"listado\s+de\s+insumos", "pliego|listado_insumos"),
        (r"capacidad\s+financiera", "pliego|capacidad_financiera"),
    ):
        if re.search(pat, norm):
            return key
    codes = extract_template_codes(label)
    if codes:
        return f"pliego|{codes[0].replace('-', '').upper()}"
    toks = [t for t in norm.split() if len(t) > 3][:5]
    return "pliego|" + "_".join(toks) if toks else norm[:48]


def extract_pliego_generables_from_bases_corpus(corpus: Any) -> List[Dict[str, Any]]:
    """Lista ítems generables: inventario de anexos + §5–8 del corpus indexado."""
    from app.services.compliance_consolidation_service import classify_deliverable_sobre

    out: List[Dict[str, Any]] = list(extract_pliego_anexos_from_bases_corpus(corpus))
    seen: Set[str] = {pliego_format_dedupe_key(r["nombre_canonico"]) for r in out}

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
