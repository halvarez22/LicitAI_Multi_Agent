from typing import Any, Dict, List, Optional
import re
import logging
from app.services.economic_calculator_engine import EconomicCalculatorEngine

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:
    _rf_fuzz = None

class EconomicRefresherService:
    def __init__(self):
        self.calculator = EconomicCalculatorEngine()

    def _normalize_label(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _calculate_similarity(self, a: str, b: str) -> float:
        if not a or not b: return 0.0
        if _rf_fuzz is not None:
            return max(
                _rf_fuzz.partial_ratio(a, b) / 100.0,
                _rf_fuzz.token_sort_ratio(a, b) / 100.0,
                _rf_fuzz.token_set_ratio(a, b) / 100.0,
            )
        return 0.0 # Fallback simple si no hay rapidfuzz (aunque lo tenemos)

    def apply_overrides(
        self, 
        items: List[Dict[str, Any]], 
        user_inputs: Dict[str, Any],
        tech_requirements: List[Dict[str, Any]],
        state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Aplica overrides de chat a los items de la propuesta usando Fuzzy Match."""
        latest_inputs = user_inputs
        
        # 3. Aplicar Totales Manuales (Override Maestro)
        for key in ["subtotal_propuesta", "iva_propuesta", "total_propuesta"]:
            if key in latest_inputs:
                val = latest_inputs[key]
                if isinstance(val, (int, float)):
                    # Forzamos la actualización en el estado maestro
                    state[key] = val
                    logger.info(f"[Refresher] Override MAESTRO aplicado: {key} = {val}")

        # 4. Sincronizar conceptos individuales
        concept_prices = latest_inputs.get("concept_prices") or {}
        if not concept_prices or not items:
            return items

        req_by_id = {str(r.get("id")): r for r in tech_requirements if r.get("id")}
        
        # Normalizar inputs del usuario
        norm_overrides = {self._normalize_label(k): float(v) for k, v in concept_prices.items()}
        
        updated_items = []
        for item in items:
            new_item = dict(item)
            candidates = []
            if new_item.get("concepto"):
                candidates.append(self._normalize_label(new_item["concepto"]))
            
            cid = new_item.get("concepto_id")
            if cid and str(cid) in req_by_id:
                req = req_by_id[str(cid)]
                lbl = req.get("label") or req.get("descripcion") or req.get("titulo") or req.get("texto")
                if lbl:
                    candidates.append(self._normalize_label(lbl))

            # 0) Match por ID TÉCNICO (Máxima Precisión) — lookup en mapa crudo (sin normalizar).
            price_val: Optional[float] = None
            detail_key = ""
            concept_id = new_item.get("concepto_id")
            if concept_id:
                technical_key = f"price_{concept_id}"
                if technical_key in concept_prices:
                    try:
                        price_val = float(concept_prices[technical_key])
                        detail_key = technical_key
                    except (TypeError, ValueError):
                        price_val = None

            hit_norm: Optional[str] = None
            if price_val is None:
                # 1) Exacto / Subcadena (Label matching) sobre claves normalizadas
                for c in candidates:
                    for k in norm_overrides.keys():
                        if c == k or (len(c) >= 8 and c in k) or (len(k) >= 8 and k in c):
                            hit_norm = k
                            break
                    if hit_norm:
                        break

            if price_val is None and not hit_norm:
                # 2) Fuzzy Match (Threshold 0.70)
                best_sc = 0.0
                for c in candidates:
                    for k in norm_overrides.keys():
                        sc = self._calculate_similarity(c, k)
                        if sc > best_sc:
                            best_sc = sc
                            hit_norm = k
                if best_sc < 0.70:
                    hit_norm = None

            if price_val is None and hit_norm and hit_norm in norm_overrides:
                price_val = norm_overrides[hit_norm]
                detail_key = hit_norm

            if price_val is not None:
                from datetime import datetime
                price = price_val
                qty = float(new_item.get("cantidad") or 1.0)
                
                # Hito 3: Inyectar metadatos de Autoridad y Fuente Híbrida
                new_item["precio_unitario"] = price
                new_item["subtotal"] = qty * price
                new_item["status"] = "matched"
                new_item["price_source"] = "chat_user_override"
                
                # Nueva estructura polimórfica de evidencia
                new_item["evidence_source"] = {
                    "source_type": "CHAT",
                    "authority_level": 3, # Usuario = Máxima Autoridad
                    "timestamp": datetime.utcnow().isoformat(),
                    "detail": f"Precio validado por usuario para '{detail_key}' vía chat."
                }
                
                # UI Legacy compatibility
                new_item["provenance_ui"] = {
                    "source_key": "chat",
                    "source_label": "Usuario (Chat)",
                    "source_icon": "👤",
                    "detail": f"Dato confirmado manualmente por el usuario."
                }
            
            updated_items.append(new_item)
            
        return updated_items
