"""
Utilidades para materializar texto de LLM en Word sin markdown crudo.

Elimina énfasis tipo Markdown y reglas horizontales que no aportan en DOCX.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Instrucción compartida para prompts de redacción (Technical / Formats).
ANTI_PLACEHOLDER_PROMPT_RULE = (
    "REGLA CRÍTICA: Si no tienes un dato real verificado en el contexto, NO escribas "
    '"...", "N/A", "[dato]" ni placeholders entre corchetes. Omite esa oración o escribe '
    'exactamente: "Dato pendiente de confirmar por el representante legal."'
)


def strip_markdown_for_docx(text: str) -> str:
    """
    Normaliza texto proveniente del LLM antes de ``add_paragraph`` en DOCX.

    - Quita encabezados Markdown (# …) dejando el título en plano.
    - Elimina líneas que son solo separadores (-, =, *, mezclas).
    - Retira **negrita**, *cursiva*, __ y _ de énfasis (enfoque conservador).
    """
    if not text:
        return ""
    out_lines: List[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        compact = stripped.replace(" ", "")
        if len(compact) >= 3 and set(compact) <= {"-", "=", "_", "*"}:
            continue
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
        if m:
            line = m.group(2).rstrip()
        while "**" in line:
            nxt = re.sub(r"\*\*([^*]*)\*\*", r"\1", line, count=1)
            if nxt == line:
                break
            line = nxt
        while "__" in line:
            nxt = re.sub(r"__([^_]*)__", r"\1", line, count=1)
            if nxt == line:
                break
            line = nxt
        line = line.replace("**", "").replace("*", "")
        line = line.replace("__", "").replace("_", "")
        out_lines.append(line.rstrip())
    return "\n".join(out_lines).rstrip()


def is_markdown_table_line(line: str) -> bool:
    """Detecta si una línea pertenece a una estructura de tabla Markdown."""
    clean = line.strip()
    # Una línea de tabla debe empezar/terminar con | o tener el separador |---|
    if clean.startswith("|") and clean.endswith("|"):
        return True
    if "|" in clean and set(clean.replace("|", "").replace(" ", "").replace("-", "").replace(":", "")) <= set():
        # Es la línea de separación |---|---|
        return "|" in clean and "-" in clean
    return False


def parse_markdown_table(lines: List[str]) -> List[List[str]]:
    """
    Convierte un bloque de líneas Markdown en una matriz de datos (filas x celdas).
    Limpia espacios y elimina la línea de separación |---|
    """
    matrix: List[List[str]] = []
    for line in lines:
        clean = line.strip()
        if not clean or (set(clean.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")) == set() and "-" in clean):
            # Omitir líneas vacías o de separación |---|
            continue
        
        # Dividir por | y limpiar cada celda
        cells = [c.strip() for c in clean.split("|")]
        # Eliminar las celdas vacías de los extremos (causadas por el | inicial/final)
        if clean.startswith("|"):
            cells = cells[1:]
        if clean.endswith("|"):
            cells = cells[:-1]
        
        if any(c for c in cells): # Solo añadir si tiene contenido
            matrix.append(cells)
    return matrix
