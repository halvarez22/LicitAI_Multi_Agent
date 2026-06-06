"""
Corpus de texto de bases/convocatoria por sesión (sin hardcodes por licitación).

Alimenta validación de citas y detección de plantillas embebidas en PDF de bases.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Señales universales de documento «bases / pliego / convocatoria»
_BASES_FILENAME_RE = re.compile(
    r"(?i)\b(bases|convocatoria|pliego|licitaci[oó]n|requisitos|invitaci[oó]n)\b"
)

# Códigos tipo Forma AE-01, FORMATO 07, Anexo III
_TEMPLATE_CODE_RE = re.compile(
    r"(?i)\b(?:forma|formato|anexo|ap[eé]ndice)\s*[- ]?\s*"
    r"([A-Z]{1,4}[- ]?\d{1,4}[A-Z]?)\b"
)

_OCR_PROMPT_NOISE_RE = re.compile(
    r"(?i)analizar y transcribir de forma forense|instrucciones de alta fidelidad|"
    r"extrae todo el texto|prohibido resumir"
)

_PAGE_SPLIT_RE = re.compile(r"---\s*PÁGINA\s+(\d+)\s*---", re.I)

_MUNICIPIO_DE_RE = re.compile(r"(?i)\bmunicipio\s+de\s+([^\n,;]{3,45})")
_ESTADO_DE_RE = re.compile(r"(?i)\bestado\s+de\s+([^\n,;]{3,30})")
_FORMATO_BLOCK_RE = re.compile(
    r"(?i)\b(?:FORMATO|FORMA|ANEXO)\s+[- ]?\s*"
    r"([A-Z]{1,4}[- ]?\d{1,4}[A-Z]?)\b"
)
_LOCALITY_STATE_FOOTER_RE = re.compile(
    r"(?i)\b([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+(?:de\s+)?[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)?)"
    r"\s*,\s*"
    r"([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)?)"
    r"\s*,\s*a[_\s\.]+"
)

_CITY_FOOTER_STOPWORDS = frozenset(
    {
        "situacion",
        "situación",
        "domicilio",
        "fecha",
        "lugar",
        "nombre",
        "representante",
        "licitante",
        "empresa",
        "objeto",
        "descripcion",
        "descripción",
        "tipo",
        "numero",
        "número",
    }
)

_MEXICAN_STATE_TOKENS = frozenset(
    {
        "aguascalientes",
        "baja california",
        "baja california sur",
        "campeche",
        "chiapas",
        "chihuahua",
        "coahuila",
        "colima",
        "durango",
        "guanajuato",
        "guerrero",
        "hidalgo",
        "jalisco",
        "mexico",
        "méxico",
        "michoacan",
        "michoacán",
        "morelos",
        "nayarit",
        "nuevo leon",
        "nuevo león",
        "oaxaca",
        "puebla",
        "queretaro",
        "querétaro",
        "quintana roo",
        "san luis potosi",
        "san luis potosí",
        "sinaloa",
        "sonora",
        "tabasco",
        "tamaulipas",
        "tlaxcala",
        "veracruz",
        "yucatan",
        "yucatán",
        "zacatecas",
        "ciudad de mexico",
        "ciudad de méxico",
    }
)


@dataclass
class BasesCorpus:
    """Texto indexado de documentos fuente de la convocatoria."""

    session_id: str
    segments: List[Tuple[str, str]] = field(default_factory=list)
    filenames: List[str] = field(default_factory=list)

    @property
    def combined(self) -> str:
        return "\n".join(t for _, t in self.segments if t)

    @property
    def combined_norm(self) -> str:
        return _norm_text(self.combined)


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower())


def _is_bases_like_filename(name: str) -> bool:
    fn = str(name or "").strip()
    if not fn:
        return False
    if _BASES_FILENAME_RE.search(fn):
        return True
    return fn.lower().endswith(".pdf")


def _extract_document_text(doc: Dict[str, Any]) -> Tuple[str, str]:
    content = doc.get("content") if isinstance(doc.get("content"), dict) else {}
    filename = str(content.get("filename") or doc.get("filename") or doc.get("name") or "")
    text = str(content.get("extracted_text") or content.get("text") or doc.get("text") or "")
    if _OCR_PROMPT_NOISE_RE.search(text[:500]) and len(text) > 2000:
        chunks = re.split(r"---\s*PÁGINA\s+\d+\s*---", text, flags=re.I)
        cleaned = [
            c.strip()
            for c in chunks
            if c.strip() and not _OCR_PROMPT_NOISE_RE.search(c[:120])
        ]
        if cleaned:
            text = "\n".join(cleaned)
    return filename, text


def build_bases_corpus(
    session_id: str,
    documents: Sequence[Dict[str, Any]],
    *,
    session_state: Optional[Dict[str, Any]] = None,
) -> BasesCorpus:
    """
    Arma corpus a partir de documentos ingeridos de la sesión.

    Prioriza archivos con nombre tipo bases/convocatoria; incluye otros PDF si no hay bases explícitas.
    """
    segments: List[Tuple[str, str]] = []
    filenames: List[str] = []
    candidates: List[Tuple[int, str, str]] = []

    for doc in documents or []:
        if not isinstance(doc, dict):
            continue
        filename, text = _extract_document_text(doc)
        if len(text.strip()) < 80:
            continue
        priority = 0 if _is_bases_like_filename(filename) else 1
        candidates.append((priority, filename, text))

    if not candidates and isinstance(session_state, dict):
        for raw in session_state.get("ingested_files") or []:
            if not isinstance(raw, dict):
                continue
            fn = str(raw.get("filename") or raw.get("name") or "")
            text = str(raw.get("extracted_text") or raw.get("text") or "")
            if len(text.strip()) < 80:
                continue
            priority = 0 if _is_bases_like_filename(fn) else 1
            candidates.append((priority, fn, text))

    candidates.sort(key=lambda x: (x[0], x[1].lower()))
    bases_found = any(p == 0 for p, _, _ in candidates)
    for priority, filename, text in candidates:
        if bases_found and priority > 0:
            continue
        segments.append((filename, text))
        if filename:
            filenames.append(filename)

    return BasesCorpus(session_id=session_id, segments=segments, filenames=filenames)


def session_has_filename(corpus: BasesCorpus, archivo: str) -> bool:
    """True si el nombre de archivo citado coincide con algún documento de la sesión."""
    ref = _norm_text(archivo)
    if not ref:
        return True
    for fn in corpus.filenames:
        nfn = _norm_text(fn)
        if ref in nfn or nfn in ref:
            return True
        if ref.replace(".pdf", "") in nfn:
            return True
    return False


def corpus_contains_phrase(corpus: BasesCorpus, phrase: str, *, min_len: int = 14) -> bool:
    """Comprueba si un fragmento sustantivo aparece en el corpus (normalizado)."""
    p = _norm_text(phrase)
    if len(p) < min_len:
        return False
    return p in corpus.combined_norm


def corpus_contains_all_tokens(corpus: BasesCorpus, tokens: Iterable[str]) -> bool:
    blob = corpus.combined_norm
    for tok in tokens:
        t = _norm_text(tok)
        if len(t) >= 3 and t not in blob:
            return False
    return True


def _expand_template_code_variants(code: str) -> List[str]:
    """Variantes DD05 ↔ DD-05 sin hardcode por licitación."""
    base = re.sub(r"\s+", "", str(code or "").upper())
    if not base:
        return []
    out = [base]
    if "-" not in base:
        m = re.match(r"^([A-Z]{1,4})(\d{1,4}[A-Z]?)$", base)
        if m:
            hyphenated = f"{m.group(1)}-{m.group(2)}"
            if hyphenated not in out:
                out.append(hyphenated)
    else:
        compact = base.replace("-", "")
        if compact not in out:
            out.append(compact)
    return out


def extract_template_codes(label: str) -> List[str]:
    """Extrae códigos AE-01, AT-10, DD-10, etc. de un nombre de formato/anexo."""
    codes: List[str] = []
    text = str(label or "")
    for m in _TEMPLATE_CODE_RE.finditer(text):
        for variant in _expand_template_code_variants(m.group(1)):
            if variant not in codes:
                codes.append(variant)
    loose = re.search(r"(?i)\bforma\s*(DD)\s*[- ]?\s*(\d{1,3})\b", text)
    if loose:
        for variant in _expand_template_code_variants(f"{loose.group(1)}{loose.group(2)}"):
            if variant not in codes:
                codes.append(variant)
    return codes


def _extract_anexo_roman_anchors(label: str) -> List[str]:
    """Anclas «anexo iv», «anexo 7», etc. para plantillas embebidas sin código AE/AT."""
    anchors: List[str] = []
    for m in re.finditer(
        r"(?i)\banexo\s+((?:[ivxlc]+)|\d{1,2})\b",
        str(label or ""),
    ):
        token = str(m.group(1) or "").strip().lower()
        if token and f"anexo {token}" not in anchors:
            anchors.append(f"anexo {token}")
    return anchors


def template_embedded_in_bases(corpus: BasesCorpus, display_name: str) -> Optional[Dict[str, Any]]:
    """
    True si el código del formato aparece en el texto de bases (plantilla embebida en PDF).

    Returns metadata con archivo y coincidencia; None si no hay evidencia en corpus.
    """
    codes = extract_template_codes(display_name)
    blob = corpus.combined_norm
    for code in codes:
        variants: List[str] = []
        for c in _expand_template_code_variants(code):
            variants.extend([c, c.replace("-", " "), c.replace("-", "")])
        for variant in variants:
            v = _norm_text(variant)
            if len(v) < 3:
                continue
            if v in blob or f"forma {v}" in blob or f"formato {v}" in blob:
                archivo = corpus.segments[0][0] if corpus.segments else None
                return {
                    "template_code": code,
                    "match_variant": variant,
                    "archivo_fuente": archivo,
                    "embedded_in_bases": True,
                }
    for anchor in _extract_anexo_roman_anchors(display_name):
        if anchor in blob:
            archivo = corpus.segments[0][0] if corpus.segments else None
            return {
                "template_code": anchor,
                "match_variant": anchor,
                "archivo_fuente": archivo,
                "embedded_in_bases": True,
            }
    return None


def find_experience_year_conflict(corpus: BasesCorpus) -> Optional[Tuple[str, str, str]]:
    """
    Detecta dos requisitos de años distintos cerca de «experiencia» en el mismo corpus.

    Returns (texto_a, texto_b, años) o None.
    """
    combined = corpus.combined
    if not combined:
        return None
    year_pat = re.compile(
        r"(\d{1,2})\s*a(?:ñ|n)os?",
        re.I,
    )
    snippets: List[Tuple[str, str]] = []
    for m in re.finditer(r".{0,90}experiencia.{0,90}", combined, re.I | re.S):
        chunk = re.sub(r"\s+", " ", m.group(0))
        ym = year_pat.search(chunk)
        if not ym:
            continue
        years = ym.group(1)
        if any(years == y for _, y in snippets):
            continue
        snippets.append((chunk[:180], years))
        if len(snippets) >= 2:
            break
    if len(snippets) >= 2 and snippets[0][1] != snippets[1][1]:
        return snippets[0][0], snippets[1][0], f"{snippets[0][1]} vs {snippets[1][1]}"
    return None


def find_unresolved_attachment_reference(corpus: BasesCorpus) -> Optional[str]:
    """Detecta «se adjunta» sin objeto claro en la misma línea (proyecto/anexo faltante)."""
    for line in corpus.combined.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if re.search(r"(?i)se adjunta a las?\s*$", ln):
            return ln[:220]
        if re.search(r"(?i)se adjunta a las?\s+y\s+no\s+consta", ln):
            return ln[:220]
    if re.search(r"(?i)se adjunta a las?\s*\n", corpus.combined):
        return "el numeral indica que un anexo o proyecto «se adjunta» sin precisar el documento en el paquete"
    return None


def find_placeholder_brackets(corpus: BasesCorpus) -> List[str]:
    """Localiza placeholders [X], [Insertar…] en formatos de las bases."""
    found: List[str] = []
    for m in re.finditer(r"\[[^\]]{1,40}\]", corpus.combined):
        token = m.group(0)
        if token not in found:
            found.append(token)
        if len(found) >= 3:
            break
    return found


def corpus_page_text(corpus: BasesCorpus, page_num: int) -> str:
    """Extrae el texto de una página marcada con «--- PÁGINA N ---» en el corpus."""
    if page_num < 1:
        return ""
    for _filename, text in corpus.segments:
        parts = _PAGE_SPLIT_RE.split(text)
        for i in range(1, len(parts), 2):
            try:
                if int(parts[i]) == page_num and i + 1 < len(parts):
                    return parts[i + 1]
            except (ValueError, IndexError):
                continue
    return ""


def infer_primary_jurisdiction(corpus: BasesCorpus) -> Optional[Dict[str, str]]:
    """
    Infiere municipio y estado convocantes desde el encabezado del corpus (sin hardcode).

    Returns dict con keys ``municipality`` y ``state`` (state puede ser vacío).
    """
    head = corpus.combined[:15000]
    if not head.strip():
        return None
    muni_counts: Counter[str] = Counter()
    for m in _MUNICIPIO_DE_RE.finditer(head):
        name = _norm_text(m.group(1).split("\n")[0].strip())
        if 3 <= len(name) <= 40:
            muni_counts[name] += 1
    if not muni_counts:
        return None
    primary_muni = muni_counts.most_common(1)[0][0]
    primary_state = ""
    for m in _ESTADO_DE_RE.finditer(head):
        st = _norm_text(m.group(1).strip())
        if len(st) >= 4:
            primary_state = st
            break
    if not primary_state:
        abbr = re.search(
            r"(?i)municipio\s+de\s+[^,\n]+,\s*([a-záéíóúñ]{4,25})",
            head,
        )
        if abbr:
            primary_state = _norm_text(abbr.group(1))
    return {"municipality": primary_muni, "state": primary_state}


def _looks_like_mexican_state(token: str) -> bool:
    t = _norm_text(token)
    if len(t) < 4:
        return False
    if t in ("fiscal", "moral", "social", "nacional", "federal", "general", "publica", "pública"):
        return False
    return any(s in t or t in s for s in _MEXICAN_STATE_TOKENS)


def _is_plausible_footer_locality(city: str, state: str) -> bool:
    city_norm = _norm_text(city.split()[0] if city else "")
    if city_norm in _CITY_FOOTER_STOPWORDS:
        return False
    return _looks_like_mexican_state(state)


def _locality_differs_from_primary(
    city: str,
    state: str,
    primary: Dict[str, str],
) -> bool:
    """True si ciudad/estado del pie de plantilla no coincide con la convocación."""
    pc = _norm_text(city)
    ps = _norm_text(state)
    pm = primary.get("municipality") or ""
    pst = primary.get("state") or ""
    if pm and pc and (pm in pc or pc in pm):
        return False
    if pst and ps and (pst in ps or ps in pst):
        return False
    if pc and pm and pc != pm:
        return True
    if ps and pst and ps != pst:
        return True
    return bool(pc and ps and pm and pst)


def find_cross_jurisdiction_template_hints(corpus: BasesCorpus) -> List[Dict[str, Any]]:
    """
    Detecta formatos/anexos cuyo pie o encabezado refieren a otra entidad territorial.

    Útil cuando bases integran plantillas de otro municipio/estado (p. ej. Mazatlán en Madera).
    """
    primary = infer_primary_jurisdiction(corpus)
    if not primary:
        return []
    results: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    blob = corpus.combined
    for m in _FORMATO_BLOCK_RE.finditer(blob):
        code = str(m.group(1) or "").strip()
        if not code:
            continue
        window = blob[m.start() : m.start() + 900]
        for loc in _LOCALITY_STATE_FOOTER_RE.finditer(window):
            city = loc.group(1).strip()
            state = loc.group(2).strip()
            if not _is_plausible_footer_locality(city, state):
                continue
            key = (_norm_text(code), _norm_text(city), _norm_text(state))
            if key in seen:
                continue
            if _locality_differs_from_primary(city, state, primary):
                seen.add(key)
                results.append(
                    {
                        "template_code": code,
                        "foreign_city": city,
                        "foreign_state": state,
                        "primary_municipality": primary.get("municipality"),
                        "primary_state": primary.get("state"),
                    }
                )
        for sm in _ESTADO_DE_RE.finditer(window):
            raw_state = sm.group(1).strip()
            if not _looks_like_mexican_state(raw_state):
                continue
            fstate = _norm_text(raw_state)
            pst = _norm_text(primary.get("state") or "")
            if not fstate or not pst or fstate in pst or pst in fstate:
                continue
            key = (_norm_text(code), "", fstate)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "template_code": code,
                    "foreign_city": "",
                    "foreign_state": sm.group(1).strip(),
                    "primary_municipality": primary.get("municipality"),
                    "primary_state": primary.get("state"),
                }
            )
    return results[:3]
