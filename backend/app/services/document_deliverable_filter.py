"""
Filtros universales para separar entregables reales de causales/prohibiciones del pliego.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

_CAUSAL_RE = re.compile(
    r"(?i)\b("
    r"no\s+presentar|no\s+deber[aá]\s+presentar|prohibido\s+presentar|"
    r"no\s+ser[aá]\s+solvente|desechamiento|descalific|causa\s+de\s+desech|"
    r"datos\s+contradictorios|"
    r"documentaci[oó]n\s+distinta\s+a\s+la\s+propuesta|"
    r"engrapad|mica[s]?\s+transparentes|broches|"
    r"presentaci[oó]n\s+y\s+apertura\s+de\s+proposiciones|"
    r"lugar\s+y\s+tiempo\s+de\s+entrega|"
    r"adjudicaci[oó]n\s+por\s+zona|"
    r"penas\s+convencionales\s*\(detalle\)|"
    r"grupos\s+de\s+ofertas|"
    r"sobres\s+o\s+empaques\s+cerrados|"
    r"causa\s*\d|causas?\s+de\s+incumplimiento|causas?\s+de\s+rescis"
    r")\b"
)

_PROCEDURAL_NOISE_RE = re.compile(
    r"(?i)\b("
    r"dolo\s+o\s+mala\s+fe|irregularidad\s+legal|irregularidades\s+graves|"
    r"presunci[oó]n\s+de\s+falsedad|documentos?\s+no\s+legibles|"
    r"documentos?\s+oficiales\s+alterados|prohibici[oó]n\s+de\s+duplicar|"
    r"el\s+comit[eé]\s+no\s+se\s+hace\s+responsable|el\s+comit[eé]\s+podr[aá],"
    r"cuando\s+lo\s+considere\s+conveniente|junta\s+de\s+aclaraciones|"
    r"criterios?\s+de\s+evaluaci[oó]n|criterio\s+binario|criterio\s+para\s+adjudicaci[oó]n|"
    r"fecha\s+y\s+hora\s+del\s+acto|procedimiento\s+para\s+ordenar|"
    r"acuerdo\s+entre\s+licitantes|aceptaci[oó]n\s+plena|disposiciones?\s+de\s+la\s+ley|"
    r"no\s+se\s+recibir[aá]n\s+proposiciones|no\s+retirar\s+o\s+dejar|"
    r"ofertas\s+no\s+objeto|no\s+cotizar\s+todos|no\s+indicar\s+montos|"
    r"comunicaci[oó]n\s+de\s+problemas|indemnizaci[oó]n\s+por|"
    r"penalizaci[oó]n\s+por\s+infracci[oó]n|reuniones\s+peri[oó]dicas|"
    r"supervisi[oó]n\s+y\s+evaluaci[oó]n|validaci[oó]n\s+de\s+constancia|"
    r"presentaci[oó]n\s+de\s+documentaci[oó]n|documentaci[oó]n\s+presentada|"
    r"documentaci[oó]n\s+debidamente|documentaci[oó]n\s+preferentemente|"
    r"documentos?\s+solicitados|omitir\s+entregar|omisi[oó]n\s+de|"
    r"formatos?\s+con\s+anotaciones|fotograf[ií]as\s+reveladas|"
    r"horarios?\s+de\s+atenci[oó]n|idioma\s+de\s+presentaci[oó]n|"
    r"deber[aá]\s+cotizar\s+todos|facilidades\s+para\s+personal|"
    r"notificaci[oó]n\s+de\s+procedencia|notificaci[oó]n\s+de\s+pr[oó]rroga|"
    r"presentaci[oó]n\s+de\s+propuestas|presenten\s+los\s+formatos|"
    r"presentar\s+diferentes\s+opciones|presentar\s+fecha\s+de\s+entrega|"
    r"precio\s+no\s+aceptable|pruebas\s+destructivas|"
    r"solicitud\s+de\s+aclaraciones|las\s+proposiciones\s+t[eé]cnica\s+y\s+econ[oó]mica\s+no\s+cuenten|"
    r"designaci[oó]n\s+del\s+representante\s+com[uú]n|ajuste\s+presupuestal|"
    r"listado\s+de\s+productos|^fallo$|\bfallo\s+de\s+licitaci[oó]n|"
    r"organigrama|plantilla\s+promedio|registro\s+patronal|"
    r"relaci[oó]n\s+de\s+los\s+veh[ií]culos|representaci[oó]n\s+legal|"
    r"requisitos\s+para\s+la\s+reducci[oó]n|se[nñ]al[eé]tica\s*\(|sucursales\s*\(|"
    r"tel[eé]fono,\s*correo|datos\s+de\s+facturaci[oó]n|domicilio\s+fiscal\s*\(|"
    r"nombre\s+del\s+director|nombre\s+de\s+supervisores|pagos?\s+de\s+los\s+bienes|"
    r"pago\s+condicionado|garant[ií]as\s+solicitadas\s+en\s+el\s+contrato|"
    r"facturaci[oó]n\s+conforme|exenci[oó]n\s+de\s+responsabilidad|"
    r"congruencia\s+de\s+los\s+servicios|especificaciones\s+t[eé]cnicas\s+y\s+requisitos\s+solicitados|"
    r"capacidad\s+y\s+caracter[ií]sticas\s+del\s+equipo|explosivo\s+de\s+insumos|"
    r"programa\s+de\s+ejecuci[oó]n\s+de\s+obra|programa\s+de\s+utilizaci[oó]n\s+de\s+maquinaria|"
    r"condiciones\s+para\s+la\s+in|documentos?\s+donde\s+se\s+requiera\s+la\s+leyenda|"
    r"dichas\s+muestras\s+deberan|deberan\s+estar\s+debidamente\s+identificadas|"
    r"presentaci[oó]n\s+de\s+m[aá]s\s+de\s+una\s+propuesta|"
    r"no\s+aceptaci[oó]n\s+de\s+modificaciones|modificaci[oó]n\s+correspondiente\s+a\s+la\s+fianza|"
    r"deber[aá]n\s+estar\s+debidamente|presentar\s+propuesta\s+t[eé]cnica\s+describ|"
    r"^manifiestos$|modelo\s+de\s+contrato\s*$"
    r")\b"
)

_PROCEDURAL_ONLY_RE = re.compile(
    r"(?i)^("
    r"presentaci[oó]n\s+de\s+m[aá]s\s+de\s+una\s+propuesta|"
    r"presentar\s+documentaci[oó]n\s+distinta|"
    r"fallo|junta\s+de\s+aclaraciones|"
    r"criterios?\s+de\s+evaluaci[oó]n|criterio\s+binario|"
    r"lugar\s+y\s+tiempo\s+de\s+entrega|"
    r"fecha\s+y\s+hora\s+del\s+acto|"
    r"manifiestos|modelo\s+de\s+contrato"
    r")$"
)

_DELIVERABLE_POSITIVE_RE = re.compile(
    r"(?i)\b("
    r"anexo\s+[a-z0-9]{1,4}|\[\s*anexo\s+|formato\s+[a-z]{1,4}\]|formato\s+[a-z]{1,4}\b|"
    r"carta\s+(de\s+)?(declaraci[oó]n|compromiso|presentaci[oó]n|protesta)|"
    r"declaraci[oó]n\s+(de\s+)?(integridad|bajo\s+protesta)|"
    r"acta\s+constitutiva|instrumento\s+jur[ií]dico|opini[oó]n\s+del\s+cumplimiento|"
    r"opini[oó]n\s+positiva|constancia\s+de\s+|constancia\s+infonavit|"
    r"identificaci[oó]n\s+oficial|identificaci[oó]n\s+personal|credencial\s+para\s+votar|"
    r"curriculum|cur[ií]culum|manifestaci[oó]n|relaci[oó]n\s+de\s+anexos|"
    r"propuesta\s+t[eé]cnica|programa\s+calendarizado|at-?\s*\d+|"
    r"certificado\s+iso|certificados?\s+de\s+biodegrad|certificados?\s+de\s+reto|"
    r"manual\s+de\s+(contingencias|procedimientos)|plan\s+de\s+manejo|"
    r"p[oó]liza|fianza|comprobante\s+de\s+domicilio|c[eé]dula\s+de\s+identificaci[oó]n\s+fiscal|"
    r"recibo\s+de\s+muestras|caracter[ií]sticas\s+de\s+muestras|"
    r"integraci[oó]n\s+del\s+costo|cat[aá]logo\s+de\s+conceptos|"
    r"an[aá]lisis\s+de\s+precios|oferta\s+econ[oó]mica|tabla\s+de\s+precios|"
    r"comprobante\s+fiscal|cfdi|dc-4|formato\s+dc|formato\s+de\s+acreditaci[oó]n|"
    r"formato\s+entrega|registro\s+en\s+el\s+padr[oó]n|padr[oó]n\s+de\s+proveedores|"
    r"visita\s+a\s+instalaciones|constancia\s+de\s+situaci[oó]n\s+fiscal|"
    r"impresi[oó]n\s+de\s+credencial|avisos\s+de\s+modificaci[oó]n"
    r")\b"
)

_LEGAL_FISICO_RE = re.compile(
    r"(?i)\b(sat|imss|infonavit|acta\s+constitutiva|identificaci[oó]n|opini[oó]n|constancia|"
    r"comprobante\s+de\s+domicilio|p[oó]liza|fianza|poder\s+notarial)"
)

# Documentos del expediente del licitante: nunca se redactan con plantilla del sistema.
_FISCAL_PHYSICAL_RE = re.compile(
    r"(?i)\b("
    r"declaraci[oó]n\s+anual|declaraci[oó]n\s+fiscal|"
    r"opini[oó]n\s+del\s+cumplimiento|opini[oó]n\s+positiva|"
    r"constancia\s+de\s+situaci[oó]n\s+fiscal"
    r")\b"
)

_COMPANY_CREDENTIAL_ONLY_RE = re.compile(
    r"(?i)\b("
    r"identificaci[oó]n\s+oficial|credencial\s+para\s+votar|\bine\b|"
    r"constancia\s+de\s+situaci[oó]n\s+fiscal|\bcsf\b|cedula\s+de\s+identificaci[oó]n\s+fiscal|\bcif\b|"
    r"opini[oó]n\s+(del\s+)?cumplimiento\s+de\s+obligaciones\s+fiscales|opini[oó]n\s+positiva\s+del\s+sat|"
    r"constancia\s+infonavit|constancia\s+imss|\bimss\b|\binfonavit\b|registro\s+patronal|"
    r"declaraci[oó]n\s+anual|declaraci[oó]n\s+de\s+impuestos|recibo\s+de\s+n[oó]mina|comprobante\s+de\s+n[oó]mina|"
    r"comprobante\s+fiscal\s+digital|\bcfdi\b|comprobante\s+de\s+domicilio|"
    r"acta\s+constitutiva|poder\s+notarial|instrumento\s+notarial|"
    r"comprobante\s+de\s+inscripci[oó]n\s+en\s+el\s+sat|curp\s+oficial|"
    r"recibo\s+de\s+honorarios|constancia\s+de\s+no\s+inhabilitaci[oó]n"
    r")\b"
)

# Formatos del pliego que sí se rellenan (carta/declaración), no certificados corporativos.
_CONVOCANTE_FILLIN_EXEMPT_RE = re.compile(
    r"(?i)\b("
    r"declaraci[oó]n\s+de\s+integridad|declaraci[oó]n\s+bajo\s+protesta|"
    r"carta\s+de\s+(declaraci[oó]n|compromiso|presentaci[oó]n|protesta)|"
    r"manifestaci[oó]n\s+de\s+integridad|formato\s+(dd|fo|dc)\b|\bfo[-_]\d|"
    r"relaci[oó]n\s+de\s+anexos|manifiesto\s+de\s+entrega"
    r")\b"
)

# Entregables que EconomicWriter materializa; no deben duplicarse en FormatsAgent.
_ECONOMIC_WRITER_DOMAIN_RE = re.compile(
    r"(?i)\b("
    r"propuesta\s+econ[oó]mica|forma\s+ae\b|anexo\s+ae\b|tabla\s+de\s+precios|"
    r"cat[aá]logo\s+de\s+conceptos.*precios|carta\s+de\s+compromiso\s+de\s+precios|"
    r"oferta\s+econ[oó]mica|an[aá]lisis\s+de\s+precios\s+unitarios"
    r")\b"
)

_ADMIN_FORMAT_TEMPLATE_RE = re.compile(
    r"(?i)\b("
    r"forma\s+(dd|at|ae|fo|dc)\b|formato\s+(dd|at|ae|fo|dc)\b|"
    r"\b(dd|fo|dc)[-_]\d{1,2}\b|\[\s*anexo\s+|formato\s+[a-z]{1,4}\]|"
    r"carta\s+(de\s+)?(declaraci[oó]n|compromiso|presentaci[oó]n|protesta)|"
    r"declaraci[oó]n\s+(de\s+)?(integridad|bajo\s+protesta)|"
    r"manifestaci[oó]n|relaci[oó]n\s+de\s+anexos|"
    r"integraci[oó]n\s+del\s+costo|formato\s+entrega"
    r")\b"
)

_GENERABLE_ACTIONS = frozenset({"generar", "requiere_datos_licitante"})


def _normalize_text(text: str) -> str:
    t = (text or "").lower().strip()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t)


def is_pliego_causal_or_prohibition(
    nombre: str, descripcion: str = "", snippet: str = ""
) -> bool:
    """
    True si el ítem describe una prohibición o causal de desechamiento, no un formato a elaborar.
    """
    blob = " ".join((nombre, descripcion, snippet)).strip()
    if not blob:
        return False
    norm_name = _normalize_text(nombre)
    if _PROCEDURAL_ONLY_RE.search(norm_name):
        return True
    if _CAUSAL_RE.search(blob):
        return True
    if norm_name.startswith("no presentar") or norm_name.startswith("no debera presentar"):
        return True
    if re.search(r"(?i)^causa\s*\d", nombre.strip()):
        return True
    return False


def is_procedural_noise_not_deliverable(
    nombre: str, descripcion: str = "", snippet: str = ""
) -> bool:
    """True si el texto es procedimiento/cronograma/regla, no un documento a elaborar o presentar."""
    blob = " ".join((nombre, descripcion, snippet)).strip()
    if not blob:
        return True
    if is_pliego_causal_or_prohibition(nombre, descripcion, snippet):
        return True
    return bool(_PROCEDURAL_NOISE_RE.search(blob))


def looks_like_actionable_deliverable(
    nombre: str,
    descripcion: str = "",
    snippet: str = "",
    tipo_accion: Optional[str] = None,
) -> bool:
    """
    True si el ítem parece un entregable real (formato, anexo, carta, opinión, etc.).
    """
    if is_procedural_noise_not_deliverable(nombre, descripcion, snippet):
        return False
    blob = " ".join((nombre, descripcion, snippet)).strip()
    if _DELIVERABLE_POSITIVE_RE.search(blob):
        return True
    action = str(tipo_accion or "").strip().lower()
    if action == "presentar_fisico" and _LEGAL_FISICO_RE.search(blob):
        return True
    return False


def should_show_deliverable_in_ui(
    nombre: str,
    descripcion: str = "",
    snippet: str = "",
    tipo_accion: Optional[str] = None,
) -> bool:
    """Política final para listas de Documentos detectados y CCC."""
    return looks_like_actionable_deliverable(nombre, descripcion, snippet, tipo_accion)


# Anexos/formatos del pliego que el licitante rellena — no credenciales empresariales.
_PLIEGO_FORMAT_ANEXO_RE = re.compile(
    r"(?i)^(\d+\.\s*)?(anexo\s+[a-z]{1,4}[\-\s]|formato\s+(de\s+)?|modelo\s+contrato|anexo\s+t[eé]cnico)"
)

# Pólizas, garantías, certificaciones bancarias (presentación física del expediente).
_CORPORATE_EXTENDED_PHYSICAL_RE = re.compile(
    r"(?i)\b("
    r"p[oó]liza|fianza|garant[ií]a\s+(de\s+)?(cumplimiento|seriedad|anticipo|vicios|laboral)|"
    r"certificaci[oó]n|certificado\s+(iso|de\s+calidad|de\s+cumplimiento)|"
    r"carta\s+bancaria|estado\s+de\s+cuenta|l[ií]nea\s+de\s+cr[eé]dito|"
    r"afianzadora|cartas?\s+de\s+cr[eé]dito|comprobante\s+bancario"
    r")\b"
)

# Anexos operativos del procedimiento, no expediente corporativo.
_NON_CORPORATE_PLIEGO_RE = re.compile(
    r"(?i)\b("
    r"constancia de visitas|comprobante de muestras|datos de facturaci|formato de registro|"
    r"formato de preguntas|integraci[oó]n del costo|manifiestos|modelo contrato|"
    r"acreditaci[oó]n de personalidad|declaraci[oó]n de intereses|antisoborno|"
    r"comprobante de entrega de muestra|formato entrega de preguntas"
    r")\b"
)


def is_corporate_physical_credential_for_panel(
    nombre: str,
    descripcion: str = "",
    snippet: str = "",
    tipo_accion: Optional[str] = None,
) -> bool:
    """
    True si el ítem es credencial/expediente empresarial que el licitante aporta en físico
    (IMSS, SAT, acta, póliza, certificación, etc.), excluyendo anexos rellenables del pliego.
    """
    if is_pliego_causal_or_prohibition(nombre, descripcion, snippet):
        return False
    blob = " ".join((nombre, descripcion, snippet)).strip()
    if not blob:
        return False
    if _NON_CORPORATE_PLIEGO_RE.search(blob):
        return False
    if _CONVOCANTE_FILLIN_EXEMPT_RE.search(blob):
        return False
    if _PLIEGO_FORMAT_ANEXO_RE.search(str(nombre or "").strip()):
        if not is_company_credential_present_only(nombre, descripcion, snippet):
            return False
    if _ADMIN_FORMAT_TEMPLATE_RE.search(blob) and re.search(r"(?i)\banexo\s+[a-z]", blob):
        if not is_company_credential_present_only(nombre, descripcion, snippet):
            return False
    if is_company_credential_present_only(nombre, descripcion, snippet):
        return True
    if _FISCAL_PHYSICAL_RE.search(blob):
        return True
    if _CORPORATE_EXTENDED_PHYSICAL_RE.search(blob):
        return True
    if _LEGAL_FISICO_RE.search(blob) and re.search(
        r"(?i)\b(acta constitutiva|identificaci[oó]n|poder notarial|opini[oó]n)\b", blob
    ):
        if not _ADMIN_FORMAT_TEMPLATE_RE.search(blob):
            return True
    return False


def filter_corporate_physical_consolidated(
    consolidated: Dict[str, Any],
) -> Dict[str, Any]:
    """Reduce CCC a credenciales empresariales de presentación física (panel Documentos detectados)."""
    if not isinstance(consolidated, dict):
        return {"candidate_document_list": [], "_meta": {"filtered_corporate_physical_only": True, "total": 0}}
    buckets = (
        "sobre_1_tecnico",
        "sobre_2_economico",
        "requisitos_legales",
        "otros_requisitos_criticos",
    )
    picked: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in buckets:
        for item in consolidated.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            nombre = str(item.get("nombre_canonico") or item.get("nombre") or "")
            snippet = str(item.get("snippet_representativo") or item.get("snippet") or "")
            tipo = str(item.get("tipo_accion_final") or item.get("tipo") or "")
            if not is_corporate_physical_credential_for_panel(nombre, "", snippet, tipo):
                continue
            key = normalize_deliverable_key(nombre, bucket)
            if key in seen:
                continue
            seen.add(key)
            picked.append(
                {
                    **item,
                    "tipo_accion_final": "presentar_fisico",
                    "tipo": "presentar_fisico",
                    "categoria": "expediente_empresarial",
                }
            )
    flat = [
        {
            "document_id": str(it.get("id") or f"corp-{i+1:02d}"),
            "nombre": str(it.get("nombre_canonico") or it.get("nombre") or "Documento"),
            "categoria": "expediente_empresarial",
            "tipo_accion_propuesto": "presentar_fisico",
            "tipo_accion_final": "presentar_fisico",
            "confidence": float(it.get("confidence") or 0.75),
            "evidence_snippet": str(it.get("snippet_representativo") or it.get("snippet") or "")[:600],
            "provenance_ui": {
                "source": "corporate_physical_filter",
                "reason": "credential_or_fiscal_physical_only",
            },
        }
        for i, it in enumerate(picked)
    ]
    return {
        "candidate_document_list": flat,
        "_meta": {
            "filtered_corporate_physical_only": True,
            "total": len(flat),
        },
    }


def filter_corporate_physical_from_compliance_list(
    items: List[Dict[str, Any]],
    categoria: str = "administrativo",
) -> List[Dict[str, Any]]:
    """Filtra filas de compliance_master_list a credenciales empresariales físicas."""
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("nombre") or item.get("descripcion") or "")
        desc = str(item.get("descripcion") or "")
        snippet = str(item.get("snippet") or "")
        tipo = str(item.get("tipo_accion") or "")
        if not is_corporate_physical_credential_for_panel(nombre, desc, snippet, tipo):
            continue
        key = normalize_deliverable_key(nombre, categoria)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


_STOPWORDS = frozenset(
    {
        "de",
        "la",
        "el",
        "los",
        "las",
        "en",
        "y",
        "o",
        "a",
        "del",
        "por",
        "con",
        "al",
        "su",
        "sus",
        "que",
        "para",
    }
)


def normalize_deliverable_key(nombre: str, categoria: str = "") -> str:
    """Clave de deduplicación por tokens significativos (fusiona variantes del mismo documento)."""
    toks = [
        t
        for t in _normalize_text(nombre).split()
        if t not in _STOPWORDS and len(t) > 2
    ]
    sig = " ".join(toks[:5]) or _normalize_text(nombre)[:48]
    return f"{_normalize_text(categoria)}|{sig}"


def is_company_credential_present_only(
    nombre: str, descripcion: str = "", snippet: str = ""
) -> bool:
    """
    True si el ítem es un certificado/constancia del licitante (IMSS, CIF, INE, etc.).
    No debe generarse Word automático; el usuario lo aporta físicamente o en portal.
    Excepción: cartas/declaraciones/manifiestos del pliego que se rellenan en plantilla.
    """
    blob = " ".join((nombre, descripcion, snippet)).strip()
    if not blob:
        return False
    if _CONVOCANTE_FILLIN_EXEMPT_RE.search(blob):
        return False
    return bool(_COMPANY_CREDENTIAL_ONLY_RE.search(blob))


def is_generable_tipo_accion(tipo_accion: Optional[str]) -> bool:
    """True si el ítem puede encolar generación automática de Word/Excel."""
    return str(tipo_accion or "").strip().lower() in _GENERABLE_ACTIONS


def is_economic_writer_domain(nombre: str, descripcion: str = "", snippet: str = "") -> bool:
    """True si el entregable pertenece al sobre económico (EconomicWriter, no Formats)."""
    blob = " ".join((nombre, descripcion, snippet)).strip()
    return bool(blob and _ECONOMIC_WRITER_DOMAIN_RE.search(blob))


def has_admin_format_template_evidence(item: Dict[str, Any]) -> bool:
    """
    True si hay señal de plantilla administrativa real (inventario, código de forma, carta/manifiesto).
    Excluye AD-* que son solo cláusulas de pliego sin formato asociado.
    """
    if item.get("from_document_inventory") or item.get("inventory_synthetic"):
        return True
    nombre = str(item.get("nombre") or "")
    desc = str(item.get("descripcion") or "")
    snippet = str(item.get("snippet") or "")
    blob = " ".join((nombre, desc, snippet)).strip()
    if not blob:
        return False
    if is_economic_writer_domain(nombre, desc, snippet):
        return False
    if is_company_credential_present_only(nombre, desc, snippet):
        return False
    rid = str(item.get("id") or "")
    if rid.startswith("1_") or re.search(r"^\s*1[_\.\-]", rid):
        return True
    if _ADMIN_FORMAT_TEMPLATE_RE.search(blob):
        return True
    if re.search(r"(?i)\banexo\s+[a-z0-9]{1,4}\b", blob):
        return True
    return False


def enforce_deterministic_tipo_accion(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-proceso universal tras Compliance LLM: corrige tipo_accion sin acoplar a una licitación.
    """
    out = dict(item)
    nombre = str(out.get("nombre") or out.get("descripcion") or "")
    desc = str(out.get("descripcion") or "")
    snippet = str(out.get("snippet") or "")
    flags = list(out.get("quality_flags") or [])

    if is_pliego_causal_or_prohibition(nombre, desc, snippet):
        if str(out.get("tipo_accion") or "").lower() != "informativo":
            out["tipo_accion"] = "informativo"
            if "enforced_causal_informativo" not in flags:
                flags.append("enforced_causal_informativo")
    elif _FISCAL_PHYSICAL_RE.search(" ".join((nombre, desc, snippet))):
        action = str(out.get("tipo_accion") or "").lower()
        if action in ("generar", "requiere_datos_licitante", "unknown", ""):
            out["tipo_accion"] = "presentar_fisico"
            if "enforced_fiscal_physical" not in flags:
                flags.append("enforced_fiscal_physical")
    elif is_company_credential_present_only(nombre, desc, snippet):
        action = str(out.get("tipo_accion") or "").lower()
        if action in ("generar", "requiere_datos_licitante", "unknown", ""):
            out["tipo_accion"] = "presentar_fisico"
            if "enforced_company_credential_fisico" not in flags:
                flags.append("enforced_company_credential_fisico")
    elif is_economic_writer_domain(nombre, desc, snippet):
        action = str(out.get("tipo_accion") or "").lower()
        if action in ("generar", "unknown", ""):
            out["tipo_accion"] = "requiere_datos_licitante"
            if "enforced_economic_domain" not in flags:
                flags.append("enforced_economic_domain")
    else:
        action = str(out.get("tipo_accion") or "").lower()
        blob = " ".join((nombre, desc, snippet))
        if action == "generar" and _LEGAL_FISICO_RE.search(blob):
            if not _ADMIN_FORMAT_TEMPLATE_RE.search(blob) and not re.search(
                r"(?i)\b(carta|declaraci[oó]n|manifiesto|anexo)\b", blob
            ):
                out["tipo_accion"] = "presentar_fisico"
                if "enforced_legal_fisico" not in flags:
                    flags.append("enforced_legal_fisico")

    if flags:
        out["quality_flags"] = flags
    return out


def filter_compliance_master_list(
    compliance_master_list: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """Elimina causales/prohibiciones/ruido de las listas administrativo/tecnico/formatos."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cat in ("administrativo", "tecnico", "formatos"):
        filtered: List[Dict[str, Any]] = []
        for item in compliance_master_list.get(cat, []) or []:
            if not isinstance(item, dict):
                continue
            nombre = str(item.get("nombre") or item.get("descripcion") or "")
            desc = str(item.get("descripcion") or "")
            snippet = str(item.get("snippet") or "")
            tipo = str(item.get("tipo_accion") or "")
            if not should_show_deliverable_in_ui(nombre, desc, snippet, tipo):
                continue
            filtered.append(item)
        out[cat] = filtered
    return out


def filter_compliance_for_generation(
    compliance_master_list: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Lista mínima para TechnicalWriter / Formats: solo acciones generables, sin físicos ni causales.
    Aplica filtro de entregables, deduplicación por firma y metadatos de conteo para auditoría.
    """
    base = filter_compliance_master_list(compliance_master_list)
    out: Dict[str, List[Dict[str, Any]]] = {}
    stats = {
        "input_after_ui_filter": sum(len(base.get(c) or []) for c in ("administrativo", "tecnico", "formatos")),
        "output_generable": 0,
        "skipped_action": 0,
        "skipped_causal": 0,
        "skipped_economic_domain_in_admin": 0,
        "skipped_no_template_evidence": 0,
        "skipped_company_credential": 0,
        "deduped": 0,
    }

    for cat in ("administrativo", "tecnico", "formatos"):
        kept: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in base.get(cat, []) or []:
            if not isinstance(item, dict):
                continue
            nombre = str(item.get("nombre") or item.get("descripcion") or "")
            desc = str(item.get("descripcion") or "")
            snippet = str(item.get("snippet") or "")
            tipo = str(item.get("tipo_accion") or "")

            if not is_generable_tipo_accion(tipo):
                stats["skipped_action"] += 1
                continue
            if is_pliego_causal_or_prohibition(nombre, desc, snippet):
                stats["skipped_causal"] += 1
                continue
            if is_company_credential_present_only(nombre, desc, snippet):
                stats["skipped_company_credential"] += 1
                continue
            if cat in ("administrativo", "formatos"):
                if is_economic_writer_domain(nombre, desc, snippet):
                    stats["skipped_economic_domain_in_admin"] += 1
                    continue
                if not has_admin_format_template_evidence(item):
                    stats["skipped_no_template_evidence"] += 1
                    continue
            sig = _dedup_signature(nombre)
            if sig in seen:
                stats["deduped"] += 1
                continue
            seen.add(sig)
            kept.append(item)

        out[cat] = kept
        stats["output_generable"] += len(kept)

    out["_generation_filter_meta"] = stats
    return out


def _filter_deliverable_dict_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("nombre_canonico") or item.get("nombre") or "")
        snippet = str(item.get("snippet_representativo") or item.get("snippet") or "")
        tipo = str(item.get("tipo") or item.get("tipo_accion_final") or "")
        if should_show_deliverable_in_ui(nombre, "", snippet, tipo):
            out.append(item)
    return out


# Alias semánticos para fusionar variantes del mismo entregable en la UI.
_DEDUP_ALIASES: Dict[str, str] = {
    "acta constitutiva": "acta constitutiva",
    "curriculum": "curriculum vitae",
    "curriculum vitae": "curriculum vitae",
    "carta declaracion integridad": "carta declaracion integridad",
    "declaracion bajo protesta": "declaracion bajo protesta",
    "propuesta tecnica": "propuesta tecnica",
    "presentar propuesta tecnica": "propuesta tecnica",
    "integracion costo servicio limpieza": "integracion costo limpieza",
    "presentar d iii integracion": "integracion costo limpieza",
    "anexo d integracion": "integracion costo limpieza",
    "identificacion oficial": "identificacion oficial",
    "constancia situacion fiscal": "constancia situacion fiscal",
    "registro padron proveedores": "registro padron proveedores",
}


def _dedup_signature(nombre: str) -> str:
    norm = _normalize_text(nombre)
    for prefix, alias in sorted(_DEDUP_ALIASES.items(), key=lambda x: -len(x[0])):
        if prefix in norm:
            return alias
    toks = [t for t in norm.split() if t not in _STOPWORDS and len(t) > 2]
    return " ".join(toks[:6]) or norm[:48]


def _merge_deliverable_items(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    merged["items_fusionados"] = int(existing.get("items_fusionados") or 1) + int(
        incoming.get("items_fusionados") or 1
    )
    if len(str(incoming.get("nombre_canonico") or "")) > len(
        str(existing.get("nombre_canonico") or "")
    ):
        merged["nombre_canonico"] = incoming.get("nombre_canonico")
    ev = list(existing.get("evidencia_original") or [])
    ev.extend(incoming.get("evidencia_original") or [])
    if ev:
        merged["evidencia_original"] = ev[:12]
    return merged


def _dedupe_deliverable_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_sig: Dict[str, Dict[str, Any]] = {}
    for item in items:
        nombre = str(item.get("nombre_canonico") or item.get("nombre") or "")
        sig = _dedup_signature(nombre)
        if sig in by_sig:
            by_sig[sig] = _merge_deliverable_items(by_sig[sig], item)
        else:
            by_sig[sig] = item
    return list(by_sig.values())


def _rebucket_filtered_deliverables(
    sobre_1: List[Dict[str, Any]],
    sobre_2: List[Dict[str, Any]],
    legales: List[Dict[str, Any]],
    otros: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    from app.services.compliance_consolidation_service import classify_deliverable_sobre

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "sobre_1_tecnico": [],
        "sobre_2_economico": [],
        "requisitos_legales": [],
        "otros_requisitos_criticos": [],
    }
    for item in sobre_1 + sobre_2 + legales + otros:
        nombre = str(item.get("nombre_canonico") or "")
        snippet = str(item.get("snippet_representativo") or "")
        key = classify_deliverable_sobre(nombre, snippet)
        item = dict(item)
        item["sobre_clasificado"] = key
        buckets[key].append(item)
    return (
        _dedupe_deliverable_list(buckets["sobre_1_tecnico"]),
        _dedupe_deliverable_list(buckets["sobre_2_economico"]),
        _dedupe_deliverable_list(buckets["requisitos_legales"]),
        _dedupe_deliverable_list(buckets["otros_requisitos_criticos"]),
    )


def filter_consolidated_document_candidates(
    consolidated: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Filtra la salida CCC (sobre_1, sobre_2, requisitos_legales) a entregables accionables.
    Reclasifica por sobre, deduplica variantes y marca meta para la UI.
    """
    if not consolidated or not isinstance(consolidated, dict):
        return consolidated or {}
    meta = consolidated.get("_meta") if isinstance(consolidated.get("_meta"), dict) else {}
    sobre_1 = _filter_deliverable_dict_list(consolidated.get("sobre_1_tecnico") or [])
    sobre_2 = _filter_deliverable_dict_list(consolidated.get("sobre_2_economico") or [])
    legales = _filter_deliverable_dict_list(consolidated.get("requisitos_legales") or [])
    otros = _filter_deliverable_dict_list(consolidated.get("otros_requisitos_criticos") or [])
    sobre_1, sobre_2, legales, otros = _rebucket_filtered_deliverables(
        sobre_1, sobre_2, legales, otros
    )
    total = len(sobre_1) + len(sobre_2) + len(legales) + len(otros)
    new_meta = dict(meta)
    new_meta["total_consolidados"] = total
    new_meta["filtered_actionable_only"] = True
    new_meta["rebucketed_and_deduped"] = True
    return {
        "sobre_1_tecnico": sobre_1,
        "sobre_2_economico": sobre_2,
        "requisitos_legales": legales,
        "otros_requisitos_criticos": otros,
        "_meta": new_meta,
    }
