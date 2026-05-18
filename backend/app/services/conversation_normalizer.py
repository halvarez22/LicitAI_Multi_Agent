from __future__ import annotations

import re
from typing import Optional


class ConversationNormalizer:
    """
    Normaliza mensajes de captura HITL para voz de copiloto.

    Esta capa evita que el usuario vea redacción técnica/cruda del pipeline
    y fuerza una micro-secuencia accionable (un dato a la vez).
    """

    _TECH_TERMS = (
        "blocking_issues",
        "price_missing",
        "economic_validation_blocking",
        "precios_positivos",
        "validation_rule_",
    )

    def normalize_capture_message(
        self,
        field_label: str,
        question: str,
        intent_type: Optional[str] = None,
        state_hint: Optional[str] = None,
    ) -> str:
        label = self._clean(field_label or "dato pendiente")
        q = self._clean(question or "")

        intro = self._intro_for_state(state_hint)
        instruction = self._instruction_for_intent(intent_type)
        example = self._example_for_intent(intent_type)
        promise = self._promise_for_state(state_hint)

        intro_section = f"{intro}\n\n" if intro else ""
        body = f"{intro_section}{q}"
        if instruction or example:
            body += f"\n\n*(Nota: {instruction} {example})*"
        
        return body.strip()

    def normalize_saved_transition(
        self,
        saved_label: str,
        next_label: str,
        next_question: str,
        *,
        next_intent_type: Optional[str] = None,
    ) -> str:
        head = f"Listo, guardé **{self._clean(saved_label)}**."
        next_msg = self.normalize_capture_message(
            field_label=next_label,
            question=next_question,
            intent_type=next_intent_type,
            state_hint="follow_up",
        )
        return f"{head}\n\n{next_msg}"

    @classmethod
    def _clean(cls, text: str) -> str:
        t = str(text or "")
        for term in cls._TECH_TERMS:
            t = t.replace(term, "")
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @staticmethod
    def _intro_for_state(state_hint: Optional[str]) -> str:
        sh = (state_hint or "").strip().lower()
        if sh == "first_item":
            return "Para continuar armando tu propuesta, vamos paso a paso."
        if sh == "blocked_by_pending":
            return "Antes de abrir otra consulta, necesito cerrar este dato contigo."
        if sh == "clarification":
            return "Claro. Te repito el dato actual:"
        return ""

    @staticmethod
    def _instruction_for_intent(intent_type: Optional[str]) -> str:
        it = (intent_type or "").strip().lower()
        if it == "economic_price":
            return "Responde solo con el número, en pesos sin IVA."
        if it == "economic_validation_blocking":
            return "Si tienes el importe, responde con el número en pesos sin IVA."
        return ""

    @staticmethod
    def _example_for_intent(intent_type: Optional[str]) -> str:
        it = (intent_type or "").strip().lower()
        if it == "economic_price":
            return "Ej: 12500 (o 0 si no aplica)."
        return "Si no aplica, responde N/A."

    @staticmethod
    def _promise_for_state(state_hint: Optional[str]) -> str:
        return ""

