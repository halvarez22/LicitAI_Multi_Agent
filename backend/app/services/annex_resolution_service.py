"""
Resolución universal de anexos/formatos — etiqueta del pliego + rol semántico + archivo generado.

Deriva de ``document_candidates_consolidated``, inventario y archivos en disco de la sesión.
Sin mapas por convocante: política versionada + dedupe_key + evidencia del panel.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.annex_semantic_policy import (
    economic_role_ids,
    generated_file_patterns_for_role,
    infer_role_from_blob,
    infer_roles_from_query,
    load_annex_semantic_policy,
    match_threshold,
    panel_buckets,
    role_label_es,
)
from app.services.junta_bases_corpus import extract_template_codes
from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key

_ANEXO_TOKEN_RE = re.compile(
    r"(?i)\banexo\s+([ivxlc\d]{1,6}|[a-záéíóúñ]{2,14})",
)
_MULTI_SPACE_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    raw = unicodedata.normalize("NFD", str(text or "").strip().lower())
    t = "".join(c for c in raw if unicodedata.category(c) != "Mn")
    t = re.sub(r"[_\-.]+", " ", t)
    return _MULTI_SPACE_RE.sub(" ", t).strip()


def _annex_display_name(item: Dict[str, Any]) -> str:
    return str(
        item.get("nombre_canonico")
        or item.get("display_name")
        or item.get("nombre")
        or item.get("label")
        or item.get("descripcion")
        or ""
    ).strip()


def _item_snippet(item: Dict[str, Any]) -> str:
    return str(
        item.get("snippet_representativo")
        or item.get("snippet")
        or item.get("descripcion")
        or ""
    ).strip()


def _item_dedupe_key(item: Dict[str, Any]) -> str:
    dk = str(item.get("dedupe_key") or "").strip()
    if dk:
        return dk
    return pliego_format_dedupe_key(_annex_display_name(item))


def iter_session_annex_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ítems del panel consolidado e inventario, deduplicados por dedupe_key."""
    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    ccc = state.get("document_candidates_consolidated")
    if isinstance(ccc, dict):
        for bk in panel_buckets():
            for raw in ccc.get(bk) or []:
                if not isinstance(raw, dict):
                    continue
                label = _annex_display_name(raw)
                if not label:
                    continue
                key = _item_dedupe_key(raw)
                if key in seen:
                    continue
                seen.add(key)
                row = dict(raw)
                row.setdefault("dedupe_key", key)
                row["_panel_bucket"] = bk
                items.append(row)

    inv = state.get("document_inventory")
    if isinstance(inv, dict):
        try:
            from app.services.obra_chat_queue_policy import inventory_item_to_panel_row

            for raw_item in inv.get("items") or []:
                if not isinstance(raw_item, dict):
                    continue
                row = inventory_item_to_panel_row(raw_item)
                if not isinstance(row, dict):
                    continue
                label = _annex_display_name(row)
                if not label:
                    continue
                key = _item_dedupe_key(row)
                if key in seen:
                    continue
                seen.add(key)
                row.setdefault("dedupe_key", key)
                items.append(row)
        except Exception:
            pass

    return items


def _extract_query_codes(query: str) -> List[str]:
    codes: List[str] = []
    for code in extract_template_codes(query):
        cu = code.upper()
        if cu not in codes:
            codes.append(cu)
        compact = cu.replace("-", "")
        if compact not in codes:
            codes.append(compact)
    return codes


def _extract_query_annexo_tokens(query: str) -> List[str]:
    tokens: List[str] = []
    for m in _ANEXO_TOKEN_RE.finditer(str(query or "")):
        tok = _normalize_text(m.group(1))
        if tok and tok not in tokens:
            tokens.append(tok)
    return tokens


def _code_in_label(code: str, label: str, dedupe_key: str) -> bool:
    norm_label = _normalize_text(label)
    cu = code.upper().replace("-", "")
    variants = {cu, code.upper()}
    if "-" not in code.upper():
        m = re.match(r"^([A-Z]{1,4})(\d{1,4})$", cu)
        if m:
            variants.add(f"{m.group(1)}-{m.group(2)}")
    for v in variants:
        if _normalize_text(v) in norm_label:
            return True
        if re.search(rf"(?i)\b{re.escape(v)}\b", label):
            return True
    if cu in dedupe_key.upper().replace("|", "_"):
        return True
    return False


def _annexo_token_in_label(token: str, label: str, dedupe_key: str) -> bool:
    norm_label = _normalize_text(label)
    tok = _normalize_text(token)
    if not tok:
        return False
    if re.search(rf"(?i)\banexo\s+{re.escape(tok)}\b", label):
        return True
    if f"anexo {tok}" in norm_label:
        return True
    dk_upper = dedupe_key.upper()
    if tok.isdigit() or re.match(r"^[ivxlc]+$", tok):
        roman = tok.upper()
        if f"ANEXO_{roman}" in dk_upper:
            return True
    return False


def _token_overlap_score(query_norm: str, label_norm: str) -> int:
    q_tokens = {t for t in query_norm.split() if len(t) >= 4}
    l_tokens = {t for t in label_norm.split() if len(t) >= 4}
    if not q_tokens or not l_tokens:
        return 0
    overlap = len(q_tokens & l_tokens)
    return min(50, overlap * 12)


def _score_item_match(
    query: str,
    item: Dict[str, Any],
    query_roles: List[str],
) -> Tuple[int, List[str]]:
    label = _annex_display_name(item)
    snippet = _item_snippet(item)
    dedupe_key = _item_dedupe_key(item)
    role = infer_role_from_blob(label, snippet, dedupe_key)
    reasons: List[str] = []
    score = 0

    codes = _extract_query_codes(query)
    for code in codes:
        if _code_in_label(code, label, dedupe_key):
            score = max(score, 100)
            reasons.append(f"code:{code}")

    for tok in _extract_query_annexo_tokens(query):
        if _annexo_token_in_label(tok, label, dedupe_key):
            score = max(score, 88)
            reasons.append(f"anexo_token:{tok}")

    q_norm = _normalize_text(query)
    l_norm = _normalize_text(label)
    if len(l_norm) >= 8 and l_norm in q_norm:
        score = max(score, 82)
        reasons.append("label_substring")
    overlap = _token_overlap_score(q_norm, l_norm)
    if overlap:
        score = max(score, overlap)
        reasons.append("token_overlap")

    if role and role in query_roles:
        score = max(score, 72)
        reasons.append(f"role_query:{role}")

    bucket = str(item.get("_panel_bucket") or item.get("sobre_clasificado") or "")
    if role in economic_role_ids() and bucket == "sobre_2_economico":
        score += 4

    prov = item.get("provenance_ui")
    if isinstance(prov, dict) and prov.get("source") == "bases_corpus":
        score += 2

    return score, reasons


def _list_generated_files(session_id: str) -> List[str]:
    if not session_id:
        return []
    root = os.path.join("/data/outputs", session_id)
    found: List[str] = []
    for sub in ("2.propuesta_economica", "propuesta_economica", ""):
        base = os.path.join(root, sub) if sub else root
        if not os.path.isdir(base):
            continue
        try:
            for fn in sorted(os.listdir(base)):
                if fn.lower().endswith((".docx", ".xlsx", ".pdf")):
                    found.append(fn)
        except OSError:
            continue
    seen: Set[str] = set()
    out: List[str] = []
    for fn in found:
        key = fn.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(fn)
    return out[:12]


def _match_file_to_role(filename: str, role_id: str) -> bool:
    for rx in generated_file_patterns_for_role(role_id):
        if rx.search(filename):
            return True
    return False


def _pick_generated_file(
    files: List[str],
    role_id: Optional[str],
    label: str,
) -> Optional[str]:
    if not files:
        return None
    if role_id:
        for fn in files:
            if _match_file_to_role(fn, role_id):
                return fn
    norm_label = _normalize_text(label)
    label_tokens = [t for t in norm_label.split() if len(t) >= 5][:6]
    for fn in files:
        fn_norm = _normalize_text(fn)
        if all(t in fn_norm for t in label_tokens[:3] if label_tokens):
            return fn
    return files[0]


@dataclass
class AnnexResolution:
    """Resultado de resolución de anexo para chat/UI."""

    matched: bool = False
    score: int = 0
    panel_label: str = ""
    semantic_role: str = ""
    semantic_role_label: str = ""
    dedupe_key: str = ""
    sobre_bucket: str = ""
    snippet: str = ""
    generated_file: Optional[str] = None
    match_reasons: List[str] = field(default_factory=list)
    provenance_ui: Optional[Dict[str, Any]] = None
    policy_version: str = ""

    def user_facing_annex_line(self) -> str:
        """Línea corta para chat: etiqueta del pliego + rol + archivo si existe."""
        if not self.matched and not self.panel_label:
            return ""
        label = self.panel_label or role_label_es(self.semantic_role)
        role_txt = self.semantic_role_label or role_label_es(self.semantic_role)
        parts: List[str] = []
        if label:
            parts.append(f"**{label}**")
        if role_txt and role_txt.lower() not in label.lower():
            parts.append(f"({role_txt})")
        if self.generated_file:
            parts.append(f"archivo generado: **{self.generated_file}**")
        return " ".join(parts).strip()


def resolve_annex_from_query(
    state: Dict[str, Any],
    user_query: str,
    *,
    session_id: str = "",
    role_hint: Optional[str] = None,
    economic_only: bool = False,
) -> AnnexResolution:
    """
    Resuelve una mención de anexo/formato contra el panel de la sesión.

    Precedencia: código en consulta → token anexo → rol semántico → overlap léxico.
    """
    pol = load_annex_semantic_policy()
    result = AnnexResolution(policy_version=str(pol.get("policy_version") or ""))
    query = str(user_query or "").strip()
    items = iter_session_annex_items(state)
    if not items:
        return result

    query_roles = infer_roles_from_query(query)
    if role_hint:
        query_roles = [role_hint] + [r for r in query_roles if r != role_hint]

    best_score = 0
    best_item: Optional[Dict[str, Any]] = None
    best_reasons: List[str] = []

    for item in items:
        label = _annex_display_name(item)
        dedupe_key = _item_dedupe_key(item)
        role = infer_role_from_blob(label, _item_snippet(item), dedupe_key)
        if economic_only and role and role not in economic_role_ids():
            if not query_roles or role not in query_roles:
                continue
        score, reasons = _score_item_match(query, item, query_roles)
        if score > best_score:
            best_score = score
            best_item = item
            best_reasons = reasons

    # Sin señal explícita de anexo: resolver por rol económico (total/catálogo)
    if best_score < match_threshold() and role_hint:
        for item in items:
            label = _annex_display_name(item)
            dk = _item_dedupe_key(item)
            role = infer_role_from_blob(label, _item_snippet(item), dk)
            if role != role_hint:
                continue
            bucket = str(item.get("_panel_bucket") or item.get("sobre_clasificado") or "")
            score = 70
            if bucket == "sobre_2_economico":
                score += 5
            if score > best_score:
                best_score = score
                best_item = item
                best_reasons = [f"role_hint:{role_hint}"]

    if not best_item or best_score < match_threshold():
        return result

    label = _annex_display_name(best_item)
    snippet = _item_snippet(best_item)
    dedupe_key = _item_dedupe_key(best_item)
    role = infer_role_from_blob(label, snippet, dedupe_key) or role_hint or ""

    files = _list_generated_files(session_id)
    gen_file = _pick_generated_file(files, role, label)

    result.matched = True
    result.score = best_score
    result.panel_label = label
    result.semantic_role = role
    result.semantic_role_label = role_label_es(role) if role else ""
    result.dedupe_key = dedupe_key
    result.sobre_bucket = str(
        best_item.get("_panel_bucket") or best_item.get("sobre_clasificado") or ""
    )
    result.snippet = snippet[:280]
    result.generated_file = gen_file
    result.match_reasons = best_reasons
    prov = best_item.get("provenance_ui")
    result.provenance_ui = dict(prov) if isinstance(prov, dict) else None
    return result


def resolve_economic_annex(
    state: Dict[str, Any],
    user_query: str,
    *,
    session_id: str = "",
    mode: str = "general",
) -> AnnexResolution:
    """Atajo para procedencia económica: rol según modo + consulta."""
    role_map = {
        "catalog": "concept_catalog",
        "total": "economic_proposal",
    }
    hint = role_map.get(mode)
    if mode == "total" and infer_roles_from_query(user_query):
        hints = infer_roles_from_query(user_query)
        if hints:
            hint = hints[0]
    res = resolve_annex_from_query(
        state,
        user_query,
        session_id=session_id,
        role_hint=hint,
        economic_only=not _extract_query_annexo_tokens(user_query)
        and not _extract_query_codes(user_query),
    )
    if res.matched:
        return res
    # Fallback: mejor ítem económico del panel sin consulta explícita
    return resolve_annex_from_query(
        state,
        user_query,
        session_id=session_id,
        role_hint=hint,
        economic_only=False,
    )


def build_annex_doc_message(
    resolution: AnnexResolution,
    *,
    user_query: str = "",
) -> str:
    """Texto corto sobre anexo resuelto para incrustar en mensaje Gate 5."""
    if not resolution.matched:
        tokens = _extract_query_annexo_tokens(user_query)
        if tokens:
            tok = tokens[0].upper()
            return (
                f"No encuentro **Anexo {tok}** en el inventario indexado de las bases "
                f"de esta sesión — revisa **Formatos/Anexos Detectados**."
            )
        return ""

    label = resolution.panel_label
    role = resolution.semantic_role_label
    explicit_tokens = _extract_query_annexo_tokens(user_query)

    if explicit_tokens:
        tok = explicit_tokens[0].upper()
        head = f"Sobre el **Anexo {tok}**"
        if label and _normalize_text(tok) not in _normalize_text(label):
            head += f" (en tus bases: **{label}**"
            if role:
                head += f" — {role}"
            head += ")"
        else:
            head = f"El anexo **{label}**"
    else:
        head = f"Anexo/formato: **{label}**"
        if role and role.lower() not in label.lower():
            head += f" ({role})"

    if resolution.generated_file:
        return f"{head}; materializado como **{resolution.generated_file}**."
    return f"{head}; revisa **Logística y Expedientes** para el archivo generado."


_ANNEX_DOC_MARKERS = ("anexo", "formato", "plantilla")
_ANNEX_LITERAL_CITATION_RE = (
    r"(?i)\bque\s+dice\b",
    r"(?i)\bque\s+establece\b",
    r"(?i)\bsegun\s+el\s+pliego\b",
    r"(?i)\bsegun\s+las\s+bases\b",
    r"(?i)\bliteral\b",
    r"(?i)\bcitar\b",
    r"(?i)\bfragmento\b",
    r"(?i)\bextracto\b",
    r"(?i)\bconforme\s+a\s+las\s+bases\b",
    r"(?i)\bdonde\s+dice\b",
    r"(?i)\ben\s+que\s+apartado\b",
)
_ANNEX_IDENTITY_RE = (
    r"(?i)\bque\s+es\b",
    r"(?i)\bque\s+va\b",
    r"(?i)\bpara\s+que\b",
    r"(?i)\bde\s+que\s+(trata|va)\b",
    r"(?i)\bque\s+documento\b",
    r"(?i)\bcual\s+es\s+el\b",
    r"(?i)\bque\s+debo\s+(presentar|entregar|llenar)\b",
    r"(?i)\bque\s+se\s+debe\s+(presentar|entregar|llenar)\b",
    r"(?i)\bque\s+contiene\b",
    r"(?i)\bque\s+incluye\b",
)


def is_annex_literal_citation_query(query: str) -> bool:
    """Consulta que exige texto literal del pliego → RAG, no identidad HRU."""
    q = str(query or "")
    if not q.strip():
        return False
    return any(re.search(pat, q) for pat in _ANNEX_LITERAL_CITATION_RE)


def detect_annex_identity_intent(query: str) -> bool:
    """
    Consulta sobre qué es / qué va un anexo (identidad semántica desde panel).

    Excluye citas literales y preguntas de procedencia económica (otro canal).
    """
    qn = _normalize_text(query)
    if len(qn) < 10:
        return False
    if not any(m in qn for m in _ANNEX_DOC_MARKERS):
        return False
    if is_annex_literal_citation_query(query):
        return False
    if re.search(
        r"(?i)(de\s+donde\s+sacaste|procedencia\s+de|mis\s+precios|como\s+viste)",
        query,
    ):
        return False
    if any(re.search(pat, query) for pat in _ANNEX_IDENTITY_RE):
        return True
    if _extract_query_annexo_tokens(query) and re.search(
        r"(?i)(que|cual|para\s+que|de\s+que|documento)",
        query,
    ):
        return True
    return False


def build_annex_identity_message(
    state: Dict[str, Any],
    user_query: str,
    *,
    session_id: str = "",
) -> Optional[str]:
    """Respuesta Gate 5: qué es / qué va un anexo según panel de la sesión."""
    from app.services.chat_gate5_formatter import format_gate5_message

    res = resolve_annex_from_query(state, user_query, session_id=session_id)
    if not res.matched:
        fail_line = build_annex_doc_message(res, user_query=user_query)
        if fail_line:
            return format_gate5_message(
                status="No ubico ese anexo en el inventario indexado de esta sesión.",
                detail=fail_line,
                cta=(
                    "Revisa **Formatos/Anexos Detectados** o confirma el nombre exacto "
                    "en las bases en **Fuentes**."
                ),
            )
        return None

    sobre_raw = str(res.sobre_bucket or "").replace("_", " ").strip()
    sobre_txt = sobre_raw.replace("sobre ", "Sobre ").strip()
    if sobre_txt.lower().startswith("sobre"):
        sobre_txt = "Sobre " + sobre_txt[6:].strip()

    status = (
        f"**{res.panel_label}** — {res.semantic_role_label or 'formato del expediente'} "
        f"en esta licitación."
    )
    detail_parts: List[str] = []
    if res.snippet:
        sn = re.sub(r"\s+", " ", res.snippet).strip()
        if len(sn) > 200:
            sn = sn[:199].rstrip() + "…"
        detail_parts.append(f"En las bases: {sn}")
    if sobre_txt:
        detail_parts.append(f"Clasificado en **{sobre_txt}**.")
    if res.generated_file:
        detail_parts.append(f"Archivo generado: **{res.generated_file}**.")
    detail = " ".join(detail_parts) or "Revisa **Formatos/Anexos Detectados** para el detalle."
    if len(detail) > 320:
        detail = detail[:319].rstrip() + "…"

    cta = (
        "Para el texto legal completo abre **Fuentes** (bases) o "
        "**Formatos/Anexos Detectados** en el panel central."
    )
    return format_gate5_message(status=status, detail=detail, cta=cta)
