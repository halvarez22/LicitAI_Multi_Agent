"""
numeric_validator.py — Validador y normalizador de valores numéricos.

Python puro, sin LLM. Valida y normaliza valores numéricos extraídos por el LLM,
incluyendo formatos monetarios mexicanos y distribuciones mensuales.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """Resultado de la validación de un valor numérico."""
    normalized_value: Optional[str]     # Valor normalizado como string (ej: "1234567.89")
    numeric_value: Optional[float]      # Valor como float, None si no parseable
    is_valid: bool
    validation_notes: str
    adjustment_applied: bool = False


@dataclass
class DistributionResult:
    """Resultado de la validación de una distribución mensual."""
    is_valid: bool
    adjusted_values: List[float] = field(default_factory=list)
    adjustment_applied: bool = False
    discrepancy: float = 0.0


class NumericValidator:
    """
    Valida y normaliza valores numéricos. Python puro — sin LLM.
    
    Soporta formatos monetarios mexicanos:
    - "$1,234,567.89" → 1234567.89
    - "1.234.567,89" → 1234567.89  (formato europeo)
    - "1,234,567" → 1234567.0
    - "1234567" → 1234567.0
    - "1234567.89" → 1234567.89
    """

    def validate_and_normalize(
        self,
        raw_value: str,
        field_type: str = "text",
    ) -> ValidationResult:
        """
        Valida y normaliza un valor según su tipo.

        Args:
            raw_value: Valor crudo extraído por el LLM.
            field_type: Tipo del campo: "currency" | "integer" | "percentage" | "text".

        Returns:
            ValidationResult. Nunca lanza excepciones.
        """
        try:
            if not raw_value or not str(raw_value).strip():
                return ValidationResult(
                    normalized_value=None,
                    numeric_value=None,
                    is_valid=False,
                    validation_notes="Valor vacío",
                )

            raw = str(raw_value).strip()

            if field_type == "currency":
                return self._validate_currency(raw)
            elif field_type == "integer":
                return self._validate_integer(raw)
            elif field_type == "percentage":
                return self._validate_percentage(raw)
            else:
                # field_type == "text" o desconocido: retornar limpio sin validación numérica
                return ValidationResult(
                    normalized_value=raw,
                    numeric_value=None,
                    is_valid=True,
                    validation_notes="Valor de texto aceptado sin validación numérica",
                )

        except Exception as e:
            logger.warning("numeric_validator_unexpected_error", error=str(e)[:80])
            return ValidationResult(
                normalized_value=None,
                numeric_value=None,
                is_valid=False,
                validation_notes=f"Error inesperado: {str(e)[:60]}",
            )

    def validate_monthly_distribution(
        self,
        monthly_values: List[float],
        total: float,
        tolerance: float = 0.01,
    ) -> DistributionResult:
        """
        Verifica que sum(monthly_values) == total (con tolerancia).
        Si hay discrepancia, aplica ajuste proporcional al último mes.

        Invariante: si adjustment_applied=True,
        entonces abs(sum(adjusted_values) - total) <= tolerance.

        Args:
            monthly_values: Lista de valores mensuales.
            total: Total esperado.
            tolerance: Tolerancia para la comparación (default: 0.01).

        Returns:
            DistributionResult. Nunca lanza excepciones.
        """
        try:
            if not monthly_values:
                return DistributionResult(
                    is_valid=total == 0.0,
                    adjusted_values=[],
                    adjustment_applied=False,
                    discrepancy=abs(total),
                )

            # Limpiar NaN e infinitos
            safe_values = [
                float(v) if (v == v and abs(v) != float("inf")) else 0.0
                for v in monthly_values
            ]
            safe_total = float(total) if (total == total and abs(total) != float("inf")) else 0.0

            current_sum = sum(safe_values)
            discrepancy = abs(current_sum - safe_total)

            if discrepancy <= tolerance:
                return DistributionResult(
                    is_valid=True,
                    adjusted_values=list(safe_values),
                    adjustment_applied=False,
                    discrepancy=discrepancy,
                )

            # Hay discrepancia: ajustar el último mes
            adjusted = list(safe_values)
            sum_without_last = sum(adjusted[:-1])
            adjusted[-1] = safe_total - sum_without_last

            # Verificar invariante
            new_sum = sum(adjusted)
            new_discrepancy = abs(new_sum - safe_total)

            logger.info(
                "numeric_validator_distribution_adjusted",
                original_sum=current_sum,
                total=safe_total,
                discrepancy=discrepancy,
                new_discrepancy=new_discrepancy,
            )

            return DistributionResult(
                is_valid=new_discrepancy <= tolerance,
                adjusted_values=adjusted,
                adjustment_applied=True,
                discrepancy=new_discrepancy,
            )

        except Exception as e:
            logger.warning("numeric_validator_distribution_error", error=str(e)[:80])
            return DistributionResult(
                is_valid=False,
                adjusted_values=list(monthly_values) if monthly_values else [],
                adjustment_applied=False,
                discrepancy=0.0,
            )

    # -------------------------------------------------------------------------
    # Métodos privados
    # -------------------------------------------------------------------------

    def _validate_currency(self, raw: str) -> ValidationResult:
        """Valida y normaliza un valor monetario mexicano."""
        numeric = self._parse_mexican_currency(raw)
        if numeric is None:
            return ValidationResult(
                normalized_value=None,
                numeric_value=None,
                is_valid=False,
                validation_notes=f"No se pudo parsear como monto: '{raw[:40]}'",
            )
        return ValidationResult(
            normalized_value=f"{numeric:,.2f}",
            numeric_value=numeric,
            is_valid=True,
            validation_notes="Monto normalizado correctamente",
        )

    def _validate_integer(self, raw: str) -> ValidationResult:
        """Valida y normaliza un valor entero."""
        # Limpiar separadores de miles y símbolo de moneda
        cleaned = re.sub(r"[$,.\s]", "", raw)
        cleaned = re.sub(r"[^\d\-]", "", cleaned)
        try:
            value = int(cleaned)
            return ValidationResult(
                normalized_value=str(value),
                numeric_value=float(value),
                is_valid=True,
                validation_notes="Entero normalizado correctamente",
            )
        except (ValueError, OverflowError):
            return ValidationResult(
                normalized_value=None,
                numeric_value=None,
                is_valid=False,
                validation_notes=f"No se pudo parsear como entero: '{raw[:40]}'",
            )

    def _validate_percentage(self, raw: str) -> ValidationResult:
        """Valida y normaliza un porcentaje."""
        cleaned = re.sub(r"[%\s]", "", raw).replace(",", ".")
        try:
            value = float(cleaned)
            return ValidationResult(
                normalized_value=f"{value:.2f}%",
                numeric_value=value,
                is_valid=True,
                validation_notes="Porcentaje normalizado correctamente",
            )
        except (ValueError, OverflowError):
            return ValidationResult(
                normalized_value=None,
                numeric_value=None,
                is_valid=False,
                validation_notes=f"No se pudo parsear como porcentaje: '{raw[:40]}'",
            )

    @staticmethod
    def _parse_mexican_currency(raw: str) -> Optional[float]:
        """
        Parsea un valor monetario en formato mexicano/español.

        Soporta:
        - "$1,234,567.89" → 1234567.89
        - "1.234.567,89" → 1234567.89  (formato europeo con coma decimal)
        - "1,234,567" → 1234567.0
        - "1234567.89" → 1234567.89
        - "MXN 1,234,567" → 1234567.0
        - "1,234,567.89 MXN" → 1234567.89
        """
        if not raw:
            return None

        # Limpiar símbolo de moneda y espacios
        cleaned = re.sub(r"[$MXNmxn\s]", "", str(raw)).strip()

        if not cleaned:
            return None

        try:
            # Detectar formato europeo: punto como separador de miles, coma como decimal
            # Patrón: dígitos.dígitos.dígitos,dígitos (ej: 1.234.567,89)
            if re.match(r"^\d{1,3}(\.\d{3})+,\d+$", cleaned):
                cleaned = cleaned.replace(".", "").replace(",", ".")
                return float(cleaned)

            # Formato estándar: coma como separador de miles, punto como decimal
            # Eliminar comas de miles
            cleaned = cleaned.replace(",", "")
            return float(cleaned)

        except (ValueError, OverflowError):
            return None
