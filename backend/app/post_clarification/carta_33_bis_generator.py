from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from docx import Document

from app.services.resilient_llm import ResilientLLMClient

logger = logging.getLogger(__name__)


def _fallback_questions() -> List[Dict[str, Any]]:
    return [
        {
            "tipo": "tecnica",
            "pregunta": "Solicitamos confirmar el alcance operativo definitivo por turno, área y cantidad de elementos.",
        },
        {
            "tipo": "legal",
            "pregunta": "Solicitamos precisar documentos obligatorios posteriores a la junta y forma de acreditación.",
        },
        {
            "tipo": "economica",
            "pregunta": "Solicitamos confirmar reglas de integración económica e importes aplicables por periodo.",
        },
    ]


async def build_questions_anexo10_from_text(
    text: str,
    *,
    llm: Optional[ResilientLLMClient] = None,
    correlation_id: str = "",
) -> List[Dict[str, Any]]:
    llm = llm or ResilientLLMClient()
    prompt = f"""
Texto de acta de junta de aclaraciones:
{text[:16000]}

Genera JSON estricto:
{{
  "preguntas_aclaracion": [
    {{"tipo":"tecnica|legal|economica", "pregunta":"texto", "referencia":"opcional"}}
  ]
}}

Reglas:
1) Máximo 8 preguntas.
2) Evita inventar normas no citadas.
3) Si el texto no da base suficiente, devuelve lista vacía.
"""
    resp = await llm.generate(
        prompt=prompt,
        system_prompt="Asistente de licitaciones. Responde SOLO JSON válido.",
        format="json",
        correlation_id=correlation_id,
    )
    if not resp.success:
        return _fallback_questions()
    raw = (resp.response or "").strip()
    try:
        obj = json.loads(raw)
        items = obj.get("preguntas_aclaracion") if isinstance(obj, dict) else None
        if isinstance(items, list):
            clean: List[Dict[str, Any]] = []
            for it in items[:8]:
                if not isinstance(it, dict):
                    continue
                p = str(it.get("pregunta") or "").strip()
                if not p:
                    continue
                t = str(it.get("tipo") or "tecnica").strip().lower()
                if t not in ("tecnica", "legal", "economica"):
                    t = "tecnica"
                clean.append(
                    {
                        "tipo": t,
                        "pregunta": p,
                        "referencia": str(it.get("referencia") or "").strip() or None,
                    }
                )
            return clean or _fallback_questions()
    except Exception as e:
        logger.warning("post_clarification_questions_parse_failed: %s", e)
    return _fallback_questions()


async def build_carta_33_bis_text(
    *,
    session_name: str,
    tipo_junta: str,
    preguntas: List[Dict[str, Any]],
    acta_excerpt: str,
    llm: Optional[ResilientLLMClient] = None,
    correlation_id: str = "",
) -> str:
    llm = llm or ResilientLLMClient()
    prompt = f"""
Redacta borrador de carta protestada de conformidad con aclaraciones (art. 33 Bis),
en español formal, para revisión humana.

Datos:
- Licitación/Sesión: {session_name}
- Tipo de junta: {tipo_junta}
- Preguntas adicionales (Anexo 10): {json.dumps(preguntas, ensure_ascii=False)}
- Extracto de acta: {acta_excerpt[:7000]}

Entrega texto plano, con:
1) Encabezado
2) Declaración de conformidad con aclaraciones
3) Referencia a preguntas presentadas
4) Lugar, fecha, nombre y firma
"""
    resp = await llm.generate(
        prompt=prompt,
        system_prompt="Redactor legal de licitaciones. No inventes referencias no citadas.",
        correlation_id=correlation_id,
    )
    if not resp.success or not (resp.response or "").strip():
        # Fallback determinístico
        now = datetime.utcnow().strftime("%d/%m/%Y")
        return (
            "Asunto: Carta de conformidad con aclaraciones (Art. 33 Bis)\n\n"
            f"Por medio de la presente, en relación con la sesión {session_name}, "
            "manifestamos bajo protesta de decir verdad que conocemos y aceptamos las "
            "aclaraciones emitidas en la junta correspondiente, y que nuestra propuesta "
            "se formula conforme a dichas precisiones.\n\n"
            "Asimismo, presentamos las preguntas complementarias en formato Anexo 10 "
            "para su valoración.\n\n"
            f"Lugar y fecha: ____________________, {now}\n"
            "Nombre y firma del representante legal: ____________________\n"
        )
    return resp.response.strip()


def write_carta_docx(path: str, carta_text: str) -> str:
    doc = Document()
    for block in (carta_text or "").split("\n\n"):
        doc.add_paragraph(block.strip())
    doc.save(path)
    return path
