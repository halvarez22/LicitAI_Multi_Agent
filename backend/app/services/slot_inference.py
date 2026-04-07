import logging, re, json
from typing import List, Dict, Any, Optional
from app.services.llm_service import LLMServiceClient

logger = logging.getLogger(__name__)

# Vocabulario Cerrado de Slots (Data points obligatorios en licitaciones)
SLOT_VOCABULARY = {
    "tax_id": ["RFC", "Cédula de Identificación Fiscal", "CIF", "R.F.C."],
    "legal_address": ["Domicilio Fiscal", "Dirección", "Calle", "Colonia", "C.P."],
    "legal_representative": ["Representante Legal", "Apoderado", "Firma autorizada"],
    "rep_id_number": ["INE", "Cédula Profesional", "Pasaporte", "Identificación oficial"],
    "phone": ["Teléfono", "Celular", "Contacto"],
    "email": ["Correo", "E-mail", "Email"],
    "company_experience_years": ["Experiencia", "Años en el giro", "Antigüedad"],
    "employee_count": ["Número de empleados", "Plantilla", "Trabajadores"],
    "social_security_id": ["Registro Patronal", "IMSS", "Alta patronal"]
}

# Mapeo de Vocabulario Inferred -> Master Profile Keys (Hito 5.1)
INFERRED_TO_PROFILE_MAP = {
    "tax_id": "rfc",
    "legal_address": "domicilio_fiscal",
    "legal_representative": "representante_legal",
    "rep_id_number": "cedula_representante",
    "phone": "telefono",
    "email": "email",
    "company_experience_years": "anos_experiencia",
    "employee_count": "numero_empleados",
    "social_security_id": "registro_patronal"
}

class SlotInferenceService:
    """
    Servicio para inferir qué datos (slots) requiere un requisito de compliance.
    Hito 5: Inferencia desde heterogeneidad de bases.
    """
    
    def __init__(self):
        self.llm = LLMServiceClient()

    def infer_slots_rules(self, text: str) -> List[str]:
        """Inferencia basada en reglas de palabras clave (rápida)."""
        text_lower = text.lower()
        detected = []
        
        for slot, keywords in SLOT_VOCABULARY.items():
            if any(k.lower() in text_lower for k in keywords):
                detected.append(slot)
                
        return sorted(list(set(detected)))

    async def infer_slots_llm(self, text: str, original_id: str = "") -> List[str]:
        """Inferencia profunda usando el LLM (exhaustiva)."""
        
        prompt = f"""Analiza el siguiente extracto de un requisito de licitación e identifica qué datos ESPECÍFICOS de la empresa oferente se necesitan para cumplirlo o redactarlo.
        
Extracto: "{text}"
ID: {original_id}

Escoge SOLO de esta lista de slots válidos:
{', '.join(SLOT_VOCABULARY.keys())}

Responde ÚNICAMENTE un JSON con la lista de slots encontrados, ej: ["tax_id", "legal_address"]. 
Si no requiere ningún dato de perfil, devuelve []."""

        try:
            resp = await self.llm.generate(
                prompt=prompt,
                system_prompt="Eres un clasificador de requisitos legales. Respondes exclusivamente en JSON válido de strings.",
                options={"temperature": 0.0}
            )
            
            raw_content = resp.get("response", "[]")
            # Limpiar posibles bloques de código markdown
            clean_json = re.sub(r'```json|```', '', raw_content).strip()
            
            slots = json.loads(clean_json)
            if not isinstance(slots, list): return []
            
            # Validar contra vocabulario
            valid_slots = [s for s in slots if s in SLOT_VOCABULARY]
            return valid_slots
        except Exception as e:
            logger.error(f"[SlotInference] Error LLM inferring slots: {e}")
            return []

    async def infer_all(self, text: str, original_id: str = "") -> List[str]:
        """Estrategia híbrida: Reglas -> LLM (Hito 5)."""
        rules_slots = self.infer_slots_rules(text)
        
        # Si las reglas son muy claras y detectaron algo, podemos confiar o usar LLM para confirmar.
        # Por ahora, usamos LLM si el texto es complejo o si queremos máxima precisión.
        llm_slots = await self.infer_slots_llm(text, original_id)
        
        return sorted(list(set(rules_slots + llm_slots)))
