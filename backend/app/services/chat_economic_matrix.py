"""
Utilidades de matriz económica para chat y pegado TSV (Ítem D).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.conversational_price_normalizer import normalize_conversational_price
from app.services.economic_capture_matrix_service import (
    MATRIX_CAPTURE_MIN_ITEMS,
    parse_tsv_price_block,
)


def format_matrix_blocks_markdown(blocks: List[Dict[str, Any]], *, max_rows: int = 30) -> str:
    """Tabla Markdown para el chat a partir de ``capture_matrix_blocks``."""
    if not blocks:
        return ""
    parts: List[str] = []
    for block in blocks[:3]:
        intro = str(block.get("intro_message") or "").strip()
        if intro:
            parts.append(intro)
        cols = block.get("matrix_columns") or [
            {"key": "label", "title": "Ubicación / concepto"},
            {"key": "price", "title": block.get("column_label") or "Precio"},
        ]
        headers = [str(c.get("title") or c.get("key")) for c in cols]
        parts.append("| " + " | ".join(headers) + " |")
        parts.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in (block.get("matrix_rows") or [])[:max_rows]:
            if not isinstance(row, dict):
                continue
            cells = [str(row.get(str(c.get("key")) or "") or "")[:48] for c in cols]
            parts.append("| " + " | ".join(cells) + " |")
        extra = len(block.get("matrix_rows") or []) - max_rows
        if extra > 0:
            parts.append(f"_… y {extra} fila(s) más en resolución por bloque._")
        parts.append(
            "_Usa **Copiar para Excel** en la tarjeta Matriz de precios, o pega aquí ubicación[TAB]precio._"
        )
    return "\n\n".join(parts).strip()


def _tsv_cell(value: Any) -> str:
    """Celda segura para pegado en Excel (sin saltos de línea ni tabuladores internos)."""
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def format_matrix_blocks_excel_tsv(blocks: List[Dict[str, Any]]) -> str:
    """
    Texto TSV listo para portapapeles → Excel (UTF-8 con BOM).

    Columnas: Anexo/archivo, Concepto o ubicación, Precio unitario.
    """
    if not blocks:
        return ""
    lines: List[str] = []
    price_title = "Precio unitario (sin IVA)"
    for block in blocks:
        cols = block.get("matrix_columns") or [
            {"key": "label", "title": "Zona / horario / ubicación"},
            {"key": "price", "title": block.get("column_label") or price_title},
        ]
        label_key = "label"
        price_key = "price"
        for c in cols:
            ck = str(c.get("key") or "")
            if ck and ck != "label":
                price_key = ck
            if ck == "label":
                label_key = ck
        for c in cols:
            if str(c.get("key") or "") == price_key:
                price_title = str(c.get("title") or price_title)
        source = _tsv_cell(block.get("source_file") or block.get("intro_message") or "anexo")
        if not lines:
            lines.append(
                "\t".join(["Anexo / archivo", "Concepto / ubicación", price_title])
            )
        for row in block.get("matrix_rows") or []:
            if not isinstance(row, dict):
                continue
            lines.append(
                "\t".join(
                    [
                        source,
                        _tsv_cell(row.get(label_key)),
                        _tsv_cell(row.get(price_key)),
                    ]
                )
            )
    return "\ufeff" + "\n".join(lines)


def build_proactive_economic_matrix_welcome(
    blocks: List[Dict[str, Any]],
    *,
    pending_row_count: Optional[int] = None,
    support_name: str = "",
) -> str:
    """
    Mensaje humano y proactivo cuando faltan precios: el asistente explica qué detectó
    y cómo capturarlos (sin pedir comandos secretos al usuario).
    """
    total = pending_row_count or sum(len(b.get("matrix_rows") or []) for b in (blocks or []))
    support_line = (
        f" y el soporte de materiales **{support_name}**"
        if str(support_name or "").strip()
        else ""
    )
    head = (
        "Ya revisé los anexos económicos de esta licitación"
        f"{support_line}. "
        f"**Detecté que aún faltan {total} precio(s) unitario(s)** "
        "(por zona, horario o ubicación, según el formato de la convocatoria). "
        "Para armar tu propuesta económica necesito que me los indiques — "
        "**no hace falta responder uno por uno en el chat**.\n\n"
        "Te dejo el detalle en la tabla. **Adjunta tu Excel o CSV lleno** con el botón "
        "📎 junto al chat (recomendado), o usa **Copiar para Excel** en la tarjeta "
        "**Matriz de precios** si prefieres editar en hoja y volver a subir el archivo.\n\n"
    )
    md = format_matrix_blocks_markdown(blocks or [], max_rows=30)
    tail = (
        "\n\n**Flujo recomendado:** completa precios en Excel → **📎 Adjuntar cotización** "
        "en el chat → el sistema importa y valida → escribe **generar propuesta económica**.\n\n"
        "_También puedes avisar con **listo** si capturaste por otro canal._"
    )
    return (head + md + tail).strip()


def build_proactive_few_economic_prices_welcome(
    pending_econ: List[Dict[str, Any]],
) -> str:
    """Saludo proactivo cuando son pocos precios (sin matriz grande)."""
    labels: List[str] = []
    for q in pending_econ[:8]:
        lbl = str(q.get("label") or "").replace("Precio (sin IVA): ", "").strip()
        if lbl:
            labels.append(lbl)
    n = len(pending_econ)
    lines = "\n".join(f"{i}. **{lbl}**" for i, lbl in enumerate(labels, 1))
    extra = ""
    if n > len(labels):
        extra = f"\n_… y {n - len(labels)} concepto(s) más._"
    return (
        f"Ya revisé la parte económica. **Me faltan {n} precio(s) unitario(s)** "
        f"para cerrar la cotización:\n\n{lines}{extra}\n\n"
        "Indícame el importe de cada uno (puedes escribir varios en un solo mensaje, "
        "por ejemplo: `Zona A 45250`). Si un concepto no aplica, dime **no aplica**."
    ).strip()


def build_structured_price_intro_with_matrix(
    missing_slots: List[Dict[str, Any]],
    matrices: List[Dict[str, Any]],
) -> str:
    """Intro económico + tabla orientadora (no «empezamos con un solo precio»)."""
    total = len(missing_slots or [])
    support_name = next(
        (
            str(slot.get("quantity_support_source_name") or "").strip()
            for slot in (missing_slots or [])
            if str(slot.get("quantity_support_source_name") or "").strip()
        ),
        "",
    )
    head = (
        f"Ya leí los anexos económicos"
        + (
            f" y el soporte de materiales **{support_name}**"
            if support_name
            else " y detecté la estructura de cantidades/elementos"
        )
        + f". Completa **{total} precio(s) unitarios** en la **matriz** (no hace falta uno por uno).\n\n"
    )
    md = format_matrix_blocks_markdown(matrices, max_rows=30)
    tail = (
        "\n\n**Cómo capturar:**\n"
        "1. Tabla **Matriz de precios** o **Resolución por bloque** (arriba del chat)\n"
        "2. Pegar aquí: `concepto` + tabulador + `precio` (una fila por línea)\n"
        "3. Exportar CSV, editar y volver a importar\n\n"
        "_Cuando termines la matriz, escribe **listo** o **generar propuesta económica**._"
    )
    return (head + md + tail).strip()


def should_use_matrix_capture(
    pending_count: int,
    *,
    session_mode: Optional[str] = None,
) -> bool:
    if session_mode == "one_by_one":
        return False
    if session_mode == "matrix":
        return True
    return pending_count >= MATRIX_CAPTURE_MIN_ITEMS


def apply_tsv_bulk_to_inputs(
    user_text: str,
    blocks: List[Dict[str, Any]],
    economic_user_inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Aplica pegado TSV masivo a ``economic_user_inputs``.

    Returns:
        dict con ``applied`` (field->value), ``errors`` (list), ``skipped`` (int)
    """
    applied: Dict[str, Any] = {}
    errors: List[str] = []
    if "\t" not in user_text and "," not in user_text:
        return {"applied": applied, "errors": errors, "skipped": 0}

    for block in blocks or []:
        field_by_label: Dict[str, str] = {}
        for row in block.get("matrix_rows") or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            field = str(row.get("field") or "").strip()
            if label and field:
                field_by_label[label] = field
        parsed = parse_tsv_price_block(user_text, field_by_label)
        for field, raw_price in parsed.items():
            val, err, conf = normalize_conversational_price(str(raw_price))
            if err or not val:
                errors.append(f"{field}: {err or 'inválido'}")
                continue
            economic_user_inputs[field] = float(val)
            applied[field] = val
            for block in blocks or []:
                for row in block.get("matrix_rows") or []:
                    if isinstance(row, dict) and str(row.get("field") or "") == field:
                        row["capture_channel"] = "user_tsv"
                        row["price"] = float(val)
    return {"applied": applied, "errors": errors, "skipped": 0}
