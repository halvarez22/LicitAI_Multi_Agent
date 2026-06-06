"""
Generación determinista del Análisis de Precios Unitarios (perspectiva concursante).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _split_apu_amounts(
    subtotal: float,
    *,
    line_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """
    Reparte subtotal en renglones APU. Si hay un solo ítem económico, concentra en materiales.
    """
    st = max(float(subtotal or 0), 0.0)
    if st < 0.01:
        return {
            "materiales": 0.0,
            "mano_obra": 0.0,
            "herramienta": 0.0,
            "indirectos": 0.0,
            "utilidad": 0.0,
        }
    if line_items and len(line_items) == 1:
        desc = str(line_items[0].get("descripcion") or line_items[0].get("concepto") or "")
        imp = float(line_items[0].get("importe") or line_items[0].get("subtotal") or st)
        return {
            "materiales": round(imp * 0.72, 2),
            "mano_obra": round(imp * 0.18, 2),
            "herramienta": round(imp * 0.03, 2),
            "indirectos": round(imp * 0.05, 2),
            "utilidad": round(imp * 0.02, 2),
            "_concept": desc,
        }
    materiales = round(st * 0.716, 2)
    mano_obra = round(st * 0.174, 2)
    herramienta = round(st * 0.033, 2)
    indirectos = round(st * 0.046, 2)
    utilidad = round(st - materiales - mano_obra - herramienta - indirectos, 2)
    return {
        "materiales": materiales,
        "mano_obra": mano_obra,
        "herramienta": herramienta,
        "indirectos": indirectos,
        "utilidad": utilidad,
    }


def build_apu_markdown(
    *,
    razon_social: str,
    rfc: str,
    representante: str,
    domicilio: str,
    fecha_es: str,
    procedimiento: str,
    subtotal: float,
    iva: float,
    total: float,
    line_items: Optional[List[Dict[str, Any]]] = None,
    ciudad: str = "",
) -> str:
    """Cuerpo del APU en markdown (tabla + narrativa concursante)."""
    parts = _split_apu_amounts(subtotal, line_items=line_items)
    concept_desc = str(parts.get("_concept") or "").strip()
    if not concept_desc and line_items:
        concept_desc = str(line_items[0].get("descripcion") or line_items[0].get("concepto") or "Partida única")
    if not concept_desc:
        concept_desc = "Bienes y servicios objeto del procedimiento"

    lugar = (ciudad or "México").strip()
    proc = (procedimiento or "el procedimiento de referencia").strip()

    intro = (
        f"Por medio del presente, yo, **{representante}**, en mi carácter de Representante Legal "
        f"con facultades de administración de **{razon_social}**, con R.F.C. **{rfc}**, "
        f"con domicilio fiscal en {domicilio or 'el señalado en el expediente'}, someto a su "
        f"consideración el desglose y análisis del precio unitario ofertado para la partida "
        f"de **{proc}**, el cual se compone de la siguiente manera:\n\n"
    )

    rows = [
        ["Concepto", "Descripción", "Importe (MXN)"],
        [
            "1. Materiales",
            concept_desc[:200],
            _money(parts["materiales"]),
        ],
        [
            "2. Mano de Obra",
            "Servicios de instalación, montaje, conexionado y puesta en marcha.",
            _money(parts["mano_obra"]),
        ],
        [
            "3. Herramienta y Equipo",
            "Herramienta menor, equipo de seguridad y elevación.",
            _money(parts["herramienta"]),
        ],
        [
            "4. Costos Indirectos",
            "Administración, supervisión, logística y trámites aplicables.",
            _money(parts["indirectos"]),
        ],
        [
            "5. Utilidad",
            "Margen empresarial sobre costo directo e indirecto.",
            _money(parts["utilidad"]),
        ],
        ["SUBTOTAL (Sin IVA)", "", _money(subtotal)],
        ["I.V.A. (16%)", "", _money(iva)],
        ["TOTAL", "", _money(total)],
    ]
    table_lines = []
    for row in rows:
        table_lines.append("| " + " | ".join(row) + " |")

    cierre = (
        "\n\nManifiesto bajo protesta de decir verdad que los precios unitarios aquí desglosados "
        "son firmes, no están sujetos a variación y cubren la totalidad de los trabajos necesarios "
        "para la correcta ejecución y entrega conforme a las especificaciones de las bases y, "
        "en su caso, la Junta de Aclaraciones.\n\n"
        "Sin otro particular, quedo a sus órdenes.\n"
    )
    return intro + "\n".join(table_lines) + cierre
