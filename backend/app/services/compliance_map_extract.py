"""
Extracción del JSON de mapa del ComplianceAgent con validación Pydantic y reintento dirigido.

El LLM devuelve la raíz ``{ administrativo, tecnico, formatos }``; los ítems enriquecidos
(``match_tier``, ``evidence_match``, …) se calculan después en ``_reduce_zone_items``.
Por eso el esquema estricto aquí es ``ComplianceMapChunkOutputStrict``, no
``ComplianceRequirementItemStrict`` (ese aplica a la lista maestra ya reducida).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from app.contracts.compliance_items import (
    ComplianceMapChunkOutputLoose,
    ComplianceMapChunkOutputStrict,
)
from app.services.llm_service import LLMServiceClient

logger = logging.getLogger(__name__)

RETRY_PROMPT_SUFFIX_ES = (
    "\n\nTu respuesta anterior no cumplió el esquema JSON requerido. Errores: {summary}\n"
    "Devuelve ÚNICAMENTE un JSON con las claves \"administrativo\", \"tecnico\" y \"formatos\" "
    '(cada una un array de objetos con "nombre", "page" (entero ≥ 0), "descripcion", '
    '"snippet", "quality_flags" (array de strings). Sin markdown ni texto adicional.'
)


def _coerce_llm_text_to_dict(text: str) -> Optional[Dict[str, Any]]:
    """Replica la lógica ligera de fences + subcadena JSON de ``ComplianceAgent._robust_json_parse``."""
    if text is None or not str(text).strip():
        return None
    t = str(text)
    try:
        if "```json" in t:
            t = t.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in t:
            t = t.split("```", 1)[1].split("```", 1)[0].strip()
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        return json.loads(t[start : end + 1])
    except (json.JSONDecodeError, IndexError, ValueError):
        return None


def _validation_error_summary(err: ValidationError, max_items: int = 8) -> str:
    parts = []
    for e in err.errors()[:max_items]:
        loc = ".".join(str(x) for x in e.get("loc", ()))
        parts.append(f"{loc}: {e.get('msg', '')}")
    return "; ".join(parts) if parts else str(err)


def _try_loose(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(d, dict):
        return None
    try:
        loose = ComplianceMapChunkOutputLoose.model_validate(d)
        return loose.model_dump(mode="python")
    except ValidationError:
        return None


@dataclass
class ComplianceJsonExtractResult:
    """Resultado de ``extract_compliance_data_with_retry``."""

    data: Optional[Dict[str, Any]]
    result_type: str
    error: Optional[str] = None
    raw_preview: Optional[str] = None


def _strict_validate(d: Optional[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[ValidationError]]:
    if not isinstance(d, dict):
        return None, None
    try:
        validated = ComplianceMapChunkOutputStrict.model_validate(d)
        return validated.model_dump(mode="python"), None
    except ValidationError as e:
        return None, e


async def extract_compliance_data_with_retry(
    client: LLMServiceClient,
    *,
    prompt: str,
    system_prompt: Optional[str],
    model: Optional[str],
    correlation_id: str = "",
) -> ComplianceJsonExtractResult:
    """
    1) LLM con ``format=json``; valida con ``ComplianceMapChunkOutputStrict``.
    2) Un reintento con resumen de ``ValidationError`` si falla.
    3) Fallback ``ComplianceMapChunkOutputLoose`` para no devolver vacío si hay JSON parcial.

    Telemetría: ``result_type`` en {``success_first_try``, ``success_on_retry``,
    ``fail_schema_mismatch``, ``llm_error``, ``empty_response``}.
    """
    raw = await client.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        format="json",
    )
    if "error" in raw:
        return ComplianceJsonExtractResult(
            data=None,
            result_type="llm_error",
            error=str(raw.get("error", "LLM error")),
        )

    raw_str = raw.get("response", "") or ""
    if not str(raw_str).strip():
        return ComplianceJsonExtractResult(data=None, result_type="empty_response", error="empty")

    preview = (raw_str[:400] + "…") if len(raw_str) > 400 else raw_str

    d1 = _coerce_llm_text_to_dict(raw_str)
    ok1, err1 = _strict_validate(d1)
    if ok1 is not None:
        logger.info(
            "compliance_map_json_extract",
            result_type="success_first_try",
            correlation_id=correlation_id,
        )
        return ComplianceJsonExtractResult(data=ok1, result_type="success_first_try", raw_preview=preview)

    summary = _validation_error_summary(err1) if err1 is not None else "JSON ilegible o no es objeto con claves esperadas"
    retry_prompt = prompt + RETRY_PROMPT_SUFFIX_ES.format(summary=summary)

    raw2 = await client.generate(
        prompt=retry_prompt,
        system_prompt=system_prompt,
        model=model,
        format="json",
    )
    if "error" in raw2:
        loose = _try_loose(d1)
        if loose is not None:
            logger.warning(
                "compliance_map_json_extract",
                result_type="fail_schema_mismatch",
                correlation_id=correlation_id,
                note="retry_llm_failed_using_loose",
            )
            return ComplianceJsonExtractResult(
                data=loose,
                result_type="fail_schema_mismatch",
                error=str(raw2.get("error")),
                raw_preview=preview,
            )
        return ComplianceJsonExtractResult(
            data=None,
            result_type="llm_error",
            error=str(raw2.get("error", "LLM error")),
            raw_preview=preview,
        )

    raw_str2 = raw2.get("response", "") or ""
    d2 = _coerce_llm_text_to_dict(raw_str2)
    ok2, err2 = _strict_validate(d2)
    if ok2 is not None:
        logger.info(
            "compliance_map_json_extract",
            result_type="success_on_retry",
            correlation_id=correlation_id,
        )
        return ComplianceJsonExtractResult(
            data=ok2,
            result_type="success_on_retry",
            raw_preview=(raw_str2[:400] + "…") if len(raw_str2) > 400 else raw_str2,
        )

    loose = _try_loose(d2) or _try_loose(d1)
    if loose is not None:
        logger.warning(
            "compliance_map_json_extract",
            result_type="fail_schema_mismatch",
            correlation_id=correlation_id,
            second_err=_validation_error_summary(err2) if err2 else None,
        )
        return ComplianceJsonExtractResult(
            data=loose,
            result_type="fail_schema_mismatch",
            error=_validation_error_summary(err2) if err2 else summary,
            raw_preview=preview,
        )

    return ComplianceJsonExtractResult(
        data=None,
        result_type="fail_schema_mismatch",
        error=_validation_error_summary(err2) if err2 else summary,
        raw_preview=preview,
    )
