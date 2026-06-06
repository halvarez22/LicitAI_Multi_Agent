"""
Batería universal de utterances para chat (SUPER ISSUE S.6).

Generada por plantillas — sin nombres de licitación, archivos fijos ni IDs de sesión.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product
from typing import Any, Dict, List


@dataclass(frozen=True)
class ChatIntentBatteryCase:
    """Caso de prueba: frase de usuario + intención esperada."""

    case_id: str
    utterance: str
    expected_intent: str
    context: Dict[str, Any] = field(default_factory=dict)
    sample_bad_response: str = ""


def _bad(code: str) -> str:
    """Respuesta simulada con código interno (debe quedar limpia tras sanitizar)."""
    return f"Estado: {code} — Gate 12.1 bloqueó 401 ítems en _compliance_truth"


def _expand(
    prefix: str,
    items: List[str],
    intent: str,
    *,
    bad_code: str = "MISSING_ECONOMIC_PROPOSAL",
) -> List[ChatIntentBatteryCase]:
    out: List[ChatIntentBatteryCase] = []
    for i, text in enumerate(items):
        out.append(
            ChatIntentBatteryCase(
                case_id=f"{prefix}_{i:03d}",
                utterance=text,
                expected_intent=intent,
                sample_bad_response=_bad(bad_code),
            )
        )
    return out


def build_chat_intent_battery() -> List[ChatIntentBatteryCase]:
    """
    Construye ≥150 casos cubriendo paráfrasis, typos y mezclas comunes en español MX.
    """
    cases: List[ChatIntentBatteryCase] = []

    bare_generar = [
        "generar",
        "genera",
        "GENERAR",
        "  generar  ",
        "adelante",
        "listo",
        "vamos",
        "dale",
        "ok",
        "de acuerdo",
        "continuar",
        "continua",
        "sigue",
        "generar ya",
        "generar por favor",
        "generar ahora",
        "generar todo",
        "generar lo que falta",
        "generar lo pendiente",
        "genrar",
        "generar plis",
        "a ver generar",
        "bueno generar",
        "simon generar",
        "órale generar",
        "va generar",
        "pues generar",
        "generar !!!",
        "generar...",
        "generar ??",
    ]
    cases.extend(_expand("disambig", bare_generar, "DESAMBIGUAR_GENERAR"))

    status = [
        "como vamos",
        "cómo vamos",
        "como vamos?",
        "que tal vamos",
        "qué tal vamos",
        "como va",
        "cómo va",
        "como va todo",
        "como llevamos",
        "en que vamos",
        "en qué vamos",
        "estatus",
        "estatus del proceso",
        "estado del proceso",
        "estado de la licitacion",
        "estado de la licitación",
        "avance",
        "avance del expediente",
        "progreso",
        "progreso general",
        "que sigue",
        "qué sigue",
        "que sigue ahora",
        "que falta",
        "qué falta",
        "que falta por hacer",
        "que hace falta",
        "que hace falta todavia",
        "donde vamos",
        "dónde vamos",
        "como vamos con esto",
        "como vamos con la propuesta",
        "reporte de avance",
        "me das un resumen del avance",
        "en que paso vamos",
        "cual es el siguiente paso",
        "cuál es el siguiente paso",
    ]
    cases.extend(_expand("status", status, "VER_ESTADO", bad_code="ANALYSIS_COMPLETED"))

    help_phrases = [
        "no entiendo",
        "no entiendo nada",
        "no te entiendo",
        "no entiendo que necesitas",
        "no entiendo qué necesitas",
        "que necesitas de mi",
        "qué necesitas de mí",
        "que ocupas",
        "qué ocupas",
        "que requieres",
        "qué requieres",
        "que debo hacer",
        "qué debo hacer",
        "que hago ahora",
        "qué hago ahora",
        "en que me ayudas",
        "en qué me ayudas",
        "no se que hacer",
        "no sé qué hacer",
        "necesito ayuda",
        "ayuda por favor",
        "ayuda!",
        "ayuda",
        "me puedes ayudar",
        "estoy perdido",
        "no se por donde empezar",
        "no sé por dónde empezar",
        "no me queda claro",
        "estoy confundido",
        "help",
    ]
    cases.extend(_expand("help", help_phrases, "AYUDA", bad_code="IDLE"))

    cotizar = [
        "generar propuesta economica",
        "generar propuesta económica",
        "genera propuesta economica",
        "generar propuesta",
        "genera propuesta",
        "calcular propuesta economica",
        "armar propuesta economica",
        "cotizar propuesta economica",
        "cotizar",
        "cotizacion economica",
        "cotización económica",
        "capturar precios",
        "captura precio unitario",
        "matriz de precios",
        "matriz de precio",
        "generar cotizacion",
        "generar cotización",
        "quiero cotizar",
        "vamos a cotizar",
        "cerrar cotizacion",
        "cerrar cotización",
        "recalcular propuesta economica",
        "validar propuesta economica",
        "generar la propuesta economica final",
        "generar propuesta economica por favor",
        "genera la propuesta economica ya",
        "CMD_TRIGGER_ECONOMIC_PROPOSAL",
        "CMD_TRIGGER_GENERATION",
    ]
    cases.extend(_expand("cotizar", cotizar, "COTIZAR", bad_code="MISSING_PRICES"))

    expediente = [
        "generar documentos",
        "generar documento",
        "generar expediente",
        "generar anexos",
        "generar anexo",
        "generar formatos",
        "generar sobres",
        "empaquetar",
        "empaquetar sobres",
        "crear expediente",
        "armar expediente",
        "generar entrega compranet",
        "generar paquete final",
        "generar los documentos finales",
        "generar documentos finales",
        "generar todo el expediente",
        "generar sobres administrativos",
        "generar sobre tecnico",
        "generar sobre economico",
        "generar propuesta tecnica y formatos",
        "quiero generar documentos",
        "listo para generar documentos",
        "generar documentos ya",
        "generar documentos por favor",
        "CMD_TRIGGER_DOC_GEN",
    ]
    cases.extend(_expand("expediente", expediente, "GENERAR_EXPEDIENTE", bad_code="INCOMPLETE_FORMATS_DATA"))

    anexo_nums = ("1", "2", "3", "4", "5", "7", "9", "12", "17")
    topics = (
        "garantías",
        "solvencia",
        "cronograma",
        "muestras",
        "penalizaciones",
        "requisitos técnicos",
        "documentación complementaria",
        "precios unitarios",
        "vigencia de la oferta",
    )
    bases_templates = [
        "¿Qué dice el anexo {n} sobre {t} en las bases?",
        "Según el pliego, ¿qué establece el anexo {n} sobre {t}?",
        "¿Dónde dice la convocatoria lo de {t}?",
        "¿Cuál es el apartado de {t} en las bases?",
        "Necesito el extracto literal de {t} en el pliego",
    ]
    idx = 0
    for n, t, tmpl in product(anexo_nums[:6], topics[:5], bases_templates[:2]):
        utterance = tmpl.format(n=n, t=t)
        cases.append(
            ChatIntentBatteryCase(
                case_id=f"bases_{idx:03d}",
                utterance=utterance,
                expected_intent="PREGUNTAR_BASES",
                sample_bad_response=_bad("COMPLIANCE_GATE_BLOCKING"),
            )
        )
        idx += 1

    eco_inputs = [
        "45250",
        "$45,250.00",
        "45250 mxn",
        "1234.56",
        "0.85",
        "Zona A 45250",
        "concepto A; 1200",
        "1200.00",
        "no aplica",
        "N/A",
        "45250 por favor",
        "te paso 9876",
        "9876.50",
        "150000",
        "$1,500.00",
    ]
    for i, val in enumerate(eco_inputs):
        cases.append(
            ChatIntentBatteryCase(
                case_id=f"eco_pending_{i:03d}",
                utterance=val,
                expected_intent="RESPONDER_PENDIENTE",
                context={
                    "has_economic_pending": True,
                    "has_any_pending": True,
                    "current_pending_type": "economic_price",
                },
                sample_bad_response=_bad("MISSING_PRICES"),
            )
        )

    profile_inputs = [
        "RFC123456789",
        "mi rfc es ABC123456XYZ",
        "5551234567",
        "contacto@empresa.com.mx",
    ]
    for i, val in enumerate(profile_inputs):
        cases.append(
            ChatIntentBatteryCase(
                case_id=f"profile_pending_{i:03d}",
                utterance=val,
                expected_intent="RESPONDER_PENDIENTE",
                context={
                    "has_economic_pending": False,
                    "has_any_pending": True,
                    "current_pending_type": "profile_field",
                },
            )
        )

    unknown = [
        "hola",
        "buenos dias",
        "gracias",
        "perfecto",
        "entendido",
        "👍",
        "si",
        "sí",
        "ok gracias",
        "muchas gracias",
        "bye",
        "saludos",
        "excelente",
        "de nada",
        "listo gracias",
    ]
    cases.extend(_expand("unknown", unknown, "UNKNOWN"))

    demo_status = [
        "y ahora",
        "y ahora?",
        "ahora que",
        "que procede",
        "como sigo",
        "como continuo",
        "cuanto falta",
        "todavia falta algo",
        "aun falta algo",
        "que toca ahora",
        "y luego que sigue",
        "listo que sigue",
        "ok que sigue",
        "va que sigue",
        "terminamos esto que sigue",
        "en que estamos",
        "como vamos hasta ahora",
        "dame el estatus",
        "resumen rapido",
        "resumen rápido del avance",
    ]
    cases.extend(_expand("demo_status", demo_status, "VER_ESTADO", bad_code="ANALYSIS_COMPLETED"))

    demo_help = [
        "empezar",
        "iniciar",
        "arrancar",
        "comenzar",
        "y ahora que hago",
        "no se como empezar",
        "no se como continuar",
        "que hago con esto",
        "por donde empiezo",
        "orientame",
        "oríentame",
        "guiame",
        "guíame",
        "explicame el proceso",
        "explícame el proceso",
        "que es lo primero",
        "qué es lo primero",
        "como funciona esto",
        "cómo funciona esto",
        "no se usar esto",
        "no sé usar esto",
    ]
    cases.extend(_expand("demo_help", demo_help, "AYUDA", bad_code="IDLE"))

    demo_disambig = [
        "simon",
        "sip",
        "confirmo",
        "hazlo",
        "haz lo",
        "procede",
        "mandale",
        "mándale",
        "dale con todo",
        "siguiente",
    ]
    cases.extend(_expand("demo_disambig", demo_disambig, "DESAMBIGUAR_GENERAR"))

    return cases


def battery_as_dicts() -> List[Dict[str, Any]]:
    """Serializa la batería para JSON / auditoría."""
    return [asdict(c) for c in build_chat_intent_battery()]


BATTERY_MIN_CASES = 150
