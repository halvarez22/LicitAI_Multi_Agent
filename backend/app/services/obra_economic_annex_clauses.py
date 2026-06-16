"""
Cláusulas determinísticas para anexos económicos de obra pública (E-1 a E-5).

HRU: montos desde motor económico verificado; sin inventar desgloses APU ni programas Gantt.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.administrative_letter_clauses import (
    _markdown_table,
    _slot,
    extract_obra_annex_inventory_requirement,
)


def _money(value: float) -> str:
    return f"${float(value or 0):,.2f}"


def _e3_subannex_checklist(snippet: str) -> List[str]:
    """Renglones E-3 A–F detectados en snippet de bases."""
    blob = str(snippet or "")
    labels = (
        ("E-3 A", r"anexo\s+e[\s_.-]*3\s*a|an[aá]lisis\s+de\s+los\s+precios\s+unitarios"),
        ("E-3 B", r"e[\s_.-]*3\s*b|factor\s+de\s+salario\s+real"),
        ("E-3 C", r"e[\s_.-]*3\s*c|factor\s+de\s+indirectos"),
        ("E-3 D", r"e[\s_.-]*3\s*d|costo\s+de\s+financiamiento"),
        ("E-3 E", r"e[\s_.-]*3\s*e|cargo\s+por\s+utilidad"),
        ("E-3 F", r"e[\s_.-]*3\s*f|an[aá]lisis\s+de\s+b[aá]sicos"),
    )
    found: List[str] = []
    for code, pat in labels:
        if re.search(pat, blob, re.I):
            found.append(code)
    if not found:
        found = ["E-3 A", "E-3 B", "E-3 C", "E-3 D", "E-3 E", "E-3 F"]
    return found


def extract_obra_plazo_ejecucion(corpus: str) -> str:
    """
    Extrae plazo de ejecución publicado en bases (sin inventar días).

    Returns:
        Fragmento breve del plazo o cadena vacía si no hay evidencia.
    """
    text = str(corpus or "")
    patterns = (
        r"(?i)(\d{1,4}\s*d[ií]as\s*(?:naturales|h[aá]biles)(?:\s+y\s+\d{1,2}\s*d[ií]as)?[^.\n]{0,90}(?:conclusi[oó]n|ejecuci[oó]n|entrega|obra))",
        r"(?i)contando\s+con\s+(\d{1,4}\s*d[ií]as\s*(?:naturales|h[aá]biles)[^.\n]{0,90}(?:conclusi[oó]n|obra))",
        r"(?i)(\d{1,4}\s*d[ií]as\s*(?:naturales|h[aá]biles))[^.\n]{0,70}obra",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        line = re.sub(r"\s+", " ", m.group(0)).strip(" .;")
        if re.search(r"\d", line) and 8 <= len(line) <= 200:
            return line
    return ""


def _resolve_concurso_label(concurso: str, corpus: str, fallback: str) -> str:
    """Etiqueta de procedimiento desde metadata o corpus (sin hardcode por licitación)."""
    label = str(concurso or "").strip()
    if label:
        return label
    m = re.search(
        r"(?i)licitaci[oó]n\s+p[uú]blica\s+(?:nacional\s+)?(?:num\.?\s*)?([A-Z]/\d+/\d+)",
        str(corpus or ""),
    )
    if m:
        return f"Licitación Pública Num. {m.group(1).replace(' ', '')}"
    m2 = re.search(r"(?i)licitaci[oó]n\s+p[uú]blica[^\n,]{0,90}", str(corpus or ""))
    if m2:
        return re.sub(r"\s+", " ", m2.group(0)).strip()[:120]
    return fallback


_ECONOMIC_REQ_CONTAMINATION_RE = re.compile(
    r"(?i)de\s+las\s+causas\s+de|descalific|desechamient|causa[s]?\s+de\s+exclusi[oó]n|"
    r"ser[aá]\s+descalificad|no\s+se\s+aceptar[aá]n|dictamen\s+de\s+evaluaci[oó]n|"
    r"mecanismo\s+de\s+puntos|propuesta\s+conveniente,\s*y\s+que\s+de\s+acuerdo"
)


def _sanitize_economic_req_line(line: str, annex_code: str) -> str:
    """Elimina cola contaminada (p. ej. causas de descalificación pegadas al inventario)."""
    text = re.sub(r"\s+", " ", str(line or "").strip(" .;"))
    if not text:
        return ""
    if _ECONOMIC_REQ_CONTAMINATION_RE.search(text):
        cut = _ECONOMIC_REQ_CONTAMINATION_RE.search(text)
        if cut and cut.start() > 24:
            text = text[: cut.start()].strip(" .;,:")
    for cut_pat in (
        r"(?i)\s*:\s*DE LAS CAUSAS\b",
        r"(?i)\s+DE LAS CAUSAS\b",
    ):
        parts = re.split(cut_pat, text, maxsplit=1)
        if parts and parts[0].strip():
            text = parts[0].strip(" .;,:")
    if annex_code.upper() == "E-5":
        m = re.search(
            r"(?i)(deber[aá]\s+presentar\s+cotizaciones[^:]{0,160}|"
            r"cotizaciones?\s+de\s+(?:los\s+)?(?:siguientes\s+)?materiales[^:]{0,160})",
            text,
        )
        if m:
            text = re.sub(r"\s+", " ", m.group(1)).strip(" .;,:")
    return text


def _clean_economic_req_line(snippet: str, annex_code: str, fallback: str) -> str:
    """Prefiere texto breve del inventario; evita ruido OCR del corpus completo."""
    from app.services.administrative_letter_clauses import (
        extract_obra_annex_inventory_requirement,
    )

    raw = str(snippet or "").strip()
    candidates: List[str] = []
    if raw:
        candidates.append(_sanitize_economic_req_line(raw, annex_code))
    inv = extract_obra_annex_inventory_requirement(raw, annex_code)
    if inv:
        candidates.append(_sanitize_economic_req_line(inv, annex_code))
    for line in candidates:
        if (
            line
            and 12 <= len(line) <= 420
            and not re.search(r"(?i)\[fuente:|presupuesto\s+52", line)
            and not _ECONOMIC_REQ_CONTAMINATION_RE.search(line)
        ):
            return line
    return fallback


def build_obra_e1_carta_compromiso_markdown(
    *,
    concurso: str,
    master_profile: Dict[str, Any],
    resumen: Dict[str, Any],
    req_snippet: str = "",
    plazo_ejecucion: str = "",
) -> str:
    """
    Carta-compromiso de la proposición (Anexo E-1) con importe total e IVA desde motor.

    El plazo se toma de bases; si no hay evidencia, se deja [Consignar] (HITL).
    """
    corpus = str(req_snippet or "")
    req_line = _clean_economic_req_line(
        req_snippet,
        "E-1",
        "Carta-compromiso en papel membretado del participante con el importe total "
        "de la proposición (incluyendo I.V.A.) y el plazo de ejecución solicitado.",
    )
    concurso_label = _resolve_concurso_label(concurso, corpus, concurso)
    razon = _slot(master_profile.get("razon_social"), "la empresa concursante")
    rfc = _slot(master_profile.get("rfc"), "S/D")
    rep = _slot(
        master_profile.get("representante_legal") or master_profile.get("representante"),
        "el representante legal",
    )
    domicilio = _slot(
        master_profile.get("domicilio_fiscal") or master_profile.get("domicilio"),
        "domicilio fiscal registrado ante el SAT",
    )
    total = float(resumen.get("total") or 0)
    iva = float(resumen.get("iva") or 0)
    moneda = str(resumen.get("moneda") or "MXN")
    total_line = (
        f"**{_money(total)}** ({moneda}), incluyendo I.V.A. por **{_money(iva)}**"
        if total > 0
        else "**[Consignar]** — importe total con I.V.A. verificado en el motor económico"
    )
    plazo = str(plazo_ejecucion or "").strip() or extract_obra_plazo_ejecucion(corpus)
    plazo_line = plazo if plazo else "**[Consignar]** — plazo congruente con el programa de ejecución"

    parts = [
        "**ANEXO E-1 — CARTA-COMPROMISO DE LA PROPOSICIÓN**\n",
        f"**Concurso:** {concurso_label}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
        "\nNosotros, **"
        f"{razon}**, con domicilio en {domicilio}, Registro Federal de Contribuyentes "
        f"**{rfc}**, representados en este acto por **{rep}**, en su carácter de "
        "Representante Legal, **bajo protesta de decir verdad**, manifestamos:\n",
        "\n1. Presentamos la presente carta-compromiso en **papel membretado del "
        "participante**, conforme al Anexo E-1 de las bases.\n",
        f"\n2. **Importe total de la proposición (incluyendo I.V.A.):** {total_line}.\n",
        f"\n3. **Plazo de ejecución solicitado:** {plazo_line}.\n",
        "\n4. Nos obligamos a cumplir los términos de la proposición económica "
        "presentada y a mantener los importes durante el procedimiento de adjudicación "
        "y, en su caso, durante la vigencia del contrato respectivo.\n",
        "\nLo anterior, en cumplimiento del Anexo E-1 de las bases.\n",
        "\nProtesto lo necesario.",
    ]
    return "\n".join(parts)


def build_obra_e2_catalog_markdown(
    *,
    concurso: str,
    mapeo_items: List[Dict[str, Any]],
    resumen: Dict[str, Any],
    req_snippet: str = "",
) -> str:
    """
    Catálogo E-2 con unidad, cantidad y precio unitario (sin inventar partidas).

    Returns:
        Markdown del cuerpo del Anexo E-2 / AE.
    """
    req_line = _clean_economic_req_line(
        req_snippet,
        "E-2",
        "Catálogo de conceptos, unidades de medición, cantidades de trabajo, "
        "precios unitarios propuestos y el total de la proposición.",
    )
    cols = ("PARTIDA", "CONCEPTO", "UNIDAD", "CANT.", "P.U.", "IMPORTE")
    rows: List[List[str]] = []
    for item in mapeo_items:
        pu = float(item.get("precio_unitario") or 0)
        imp = float(item.get("importe") or 0)
        if pu <= 0 and imp > 0:
            cant = float(item.get("cantidad") or 1)
            pu = imp / cant if cant else 0
        rows.append(
            [
                str(item.get("partida") or ""),
                str(item.get("descripcion") or item.get("concepto") or "")[:200],
                str(item.get("unidad") or "[Consignar]"),
                str(item.get("cantidad") or ""),
                _money(pu) if pu > 0 else "[Consignar]",
                _money(imp) if imp > 0 else "[Consignar]",
            ]
        )
    if not rows:
        rows = [["[Consignar]"] * len(cols)]

    parts = [
        "**ANEXO E-2 — CATÁLOGO DE CONCEPTOS Y PRECIOS UNITARIOS**\n",
        f"**Concurso:** {concurso}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
        "\n**Bajo protesta de decir verdad**, presento el catálogo de conceptos con "
        "cantidades y precios unitarios propuestos:\n\n",
        _markdown_table(list(cols), rows),
        "\n",
    ]
    if resumen.get("obra_breakdown"):
        parts.extend(
            [
                f"\n**Costos directos:** {_money(float(resumen.get('costos_directos') or 0))}",
                f"**Costos indirectos:** {_money(float(resumen.get('costos_indirectos') or 0))}",
                f"**Utilidad:** {_money(float(resumen.get('utilidad') or 0))}",
                f"**Subtotal antes de IVA:** {_money(float(resumen.get('subtotal') or 0))}",
                f"**I.V.A.:** {_money(float(resumen.get('iva') or 0))}",
                f"**Total de la proposición:** {_money(float(resumen.get('total') or 0))}\n",
            ]
        )
    else:
        parts.append(
            f"\n**Subtotal:** {_money(float(resumen.get('subtotal') or 0))} | "
            f"**I.V.A.:** {_money(float(resumen.get('iva') or 0))} | "
            f"**Total:** {_money(float(resumen.get('total') or 0))}\n"
        )
    parts.extend(
        [
            "\nLos importes anteriores provienen del motor económico de la sesión; "
            "cualquier corrección de precios unitarios debe reflejarse en el catálogo "
            "y en las tarjetas APU antes de la entrega.\n",
            "\nLo anterior, en cumplimiento del Anexo E-2 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)


def build_obra_e3_annex_markdown(
    *,
    concurso: str,
    mapeo_items: List[Dict[str, Any]],
    req_snippet: str = "",
    tabla_precios_basename: str = "",
    has_verified_apu_cards: bool = False,
) -> str:
    """
    Portada E-3 sin desglose APU inventado.

    Las tarjetas APU por concepto (E-3 A–F) son HITL o importación desde Excel.
    """
    req_line = _clean_economic_req_line(
        req_snippet,
        "E-3",
        "Análisis de los precios unitarios estructurados por costos directos, "
        "indirectos, financiamiento y utilidad, con subanexos E-3 A a E-3 F.",
    )
    checklist = _e3_subannex_checklist(req_snippet)
    concept_lines = []
    for item in mapeo_items[:50]:
        desc = str(item.get("descripcion") or item.get("concepto") or "").strip()
        if desc:
            concept_lines.append(
                f"- Partida {item.get('partida', '')}: {desc[:160]}"
            )
    parts = [
        "**ANEXO E-3 — ANÁLISIS DE PRECIOS UNITARIOS**\n",
        f"**Concurso:** {concurso}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
        "\n**Subanexos exigidos en bases:**\n",
    ]
    for code in checklist:
        parts.append(f"- **{code}**")
    parts.append("")
    if concept_lines:
        parts.append("**Conceptos del catálogo sujetos a tarjeta APU:**\n")
        parts.extend(concept_lines)
        parts.append("")
    if tabla_precios_basename:
        parts.append(
            f"**Soporte tabular:** `{tabla_precios_basename}` (catálogo / precios unitarios).\n"
        )
    if has_verified_apu_cards:
        parts.append(
            "\n**Bajo protesta de decir verdad**, integro las **tarjetas de análisis de "
            "precios unitarios** desglosadas por concepto, conforme a los subanexos E-3 A a E-3 F.\n"
        )
    else:
        parts.extend(
            [
                "\n**Bajo protesta de decir verdad**, integro a este anexo las **tarjetas de "
                "análisis de precios unitarios** por cada concepto del catálogo, con los "
                "subanexos exigidos en bases.\n",
                "\n**Documentos requeridos (no generables automáticamente sin HITL):**\n",
                "- Tarjetas APU por concepto (costos directos, indirectos, financiamiento, utilidad).\n",
                "- Desglose factor de salario real (E-3 B), indirectos (E-3 C), financiamiento (E-3 D), "
                "utilidad/fiscal (E-3 E) y básicos de cuadrillas/materiales (E-3 F).\n",
                "\n**[Consignar]** — Adjunte las tarjetas APU verificadas. El sistema **no** "
                "inventa porcentajes de materiales/mano de obra sin evidencia documental.\n",
            ]
        )
    parts.extend(
        [
            "\nLo anterior, en cumplimiento del Anexo E-3 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)


def build_obra_e4_programa_markdown(
    *,
    concurso: str,
    req_snippet: str = "",
    has_gantt_attachments: bool = False,
) -> str:
    """Anexo E-4: programas Gantt (HITL físico)."""
    req_line = extract_obra_annex_inventory_requirement(req_snippet, "E-4")
    if not req_line:
        req_line = "Programas de obra en barras de Gantt (físico y de montos mensuales)."
    parts = [
        "**ANEXO E-4 — PROGRAMAS DE OBRA (GANTT)**\n",
        f"**Concurso:** {concurso}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
    ]
    if has_gantt_attachments:
        parts.append(
            "\n**Bajo protesta de decir verdad**, anexo los programas de obra en formato Gantt "
            "exigidos en bases:\n"
            "- Programa de obra físico por conceptos o partidas.\n"
            "- Programa de obra físico de montos mensuales por conceptos o partidas.\n"
        )
    else:
        parts.extend(
            [
                "\n**Bajo protesta de decir verdad**, integro a este anexo los programas de obra "
                "en formato Gantt exigidos en bases.\n",
                "\n**Documentos requeridos (no generables por el sistema):**\n",
                "a) **Programa de obra físico** en barras de Gantt, por conceptos o partidas.\n",
                "b) **Programa de obra físico de montos mensuales** en barras de Gantt.\n",
                "\n**[Consignar]** — Adjunte ambos programas elaborados conforme al plazo de "
                "ejecución de la obra y al calendario de bases.\n",
            ]
        )
    parts.extend(
        [
            "\nLo anterior, en cumplimiento del Anexo E-4 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)


def build_obra_e5_cotizaciones_markdown(
    *,
    concurso: str,
    req_snippet: str = "",
    has_cotizaciones_attachments: bool = False,
) -> str:
    """
    Anexo E-5: cotizaciones de materiales (HITL físico).

    No afirma adjuntar cotizaciones sin evidencia documental en sesión.
    """
    corpus = str(req_snippet or "")
    req_line = _clean_economic_req_line(
        corpus,
        "E-5",
        "Cotizaciones de los materiales a utilizar en la obra.",
    )
    concurso_label = _resolve_concurso_label(concurso, corpus, concurso)
    parts = [
        "**ANEXO E-5 — COTIZACIONES DE MATERIALES**\n",
        f"**Concurso:** {concurso_label}\n",
        f"**Requisito publicado en bases:** {req_line}\n",
    ]
    if has_cotizaciones_attachments:
        parts.append(
            "\n**Bajo protesta de decir verdad**, anexo las cotizaciones de materiales "
            "exigidas en bases, emitidas por los proveedores correspondientes.\n"
        )
    else:
        parts.extend(
            [
                "\n**Bajo protesta de decir verdad**, integro a este anexo las cotizaciones "
                "de materiales exigidas en las bases.\n",
                "\n**Documentos requeridos (no generables por el sistema):**\n",
                "- Cotizaciones de los materiales a utilizar en la obra, en original o copia "
                "certificada conforme a bases.\n",
                "- Deben corresponder a los insumos y costos básicos de materiales "
                "utilizados en el Anexo E-3.\n",
                "\n**[Consignar]** — Adjunte las cotizaciones originales en hoja membretada "
                "de los proveedores. El sistema **no** inventa precios de proveedores "
                "sin evidencia documental.\n",
            ]
        )
    parts.extend(
        [
            "\nLo anterior, en cumplimiento del Anexo E-5 de las bases.\n",
            "\nProtesto lo necesario.",
        ]
    )
    return "\n".join(parts)
