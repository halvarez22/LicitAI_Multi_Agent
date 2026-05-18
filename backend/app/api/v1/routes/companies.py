from fastapi import APIRouter, HTTPException, File, UploadFile, Form, BackgroundTasks
from typing import Dict, List, Any
import uuid
import os
import shutil
import json
import re

from pydantic import BaseModel
from app.api.v1.routes.sessions import get_repository
from app.services.ocr_service import OCRServiceClient
from app.services.vector_service import VectorDbServiceClient
from app.services.llm_service import LLMServiceClient
from app.services.cif_profile_extract import extract_cif_company_profile_patch
from app.services.legal_representative_parser import (
    detect_cif_contribuyente_name,
    detect_legal_representative,
    is_constancia_cif_text,
    resolve_rfc_persona_moral,
)
from app.utils.ocr_quality import looks_like_low_signal_ocr

router = APIRouter()

BASE_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join("/data", "uploads") if os.path.exists("/.dockerenv") or os.environ.get("ENVIRONMENT") == "development" else os.path.join(BASE_PATH, "data", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

class CompanyData(BaseModel):
    id: str | None = None
    name: str = "Unknown"
    type: str = "moral"
    docs_metadata: Dict = {}
    master_profile: Dict = {}

def _chunk_text(text: str, chunk_size: int = 4000, overlap: int = 400) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]


def _extraction_quality(ocr_ctx: Dict) -> Dict:
    """Evalua calidad de extracción para decidir si un documento es analizable."""
    extracted_text = (ocr_ctx.get("extracted_text") or "").strip()
    pages = ocr_ctx.get("pages", []) or []
    pages_with_text = sum(1 for p in pages if (p.get("text") or "").strip())
    chars = len(extracted_text)
    min_chars = int(os.getenv("COMPANY_OCR_MIN_CHARS", "120"))
    min_pages_with_text = int(os.getenv("COMPANY_OCR_MIN_PAGES_WITH_TEXT", "1"))
    low_signal = looks_like_low_signal_ocr(extracted_text)
    is_ok = chars >= min_chars and pages_with_text >= min_pages_with_text and not low_signal
    return {
        "ok": is_ok,
        "chars": chars,
        "pages_with_text": pages_with_text,
        "min_chars": min_chars,
        "min_pages_with_text": min_pages_with_text,
        "low_signal": low_signal,
    }



def _company_doc_title_suggests_cif(doc_title: str) -> bool:
    """True si el título de carga del documento sugiere CIF / constancia / situación fiscal."""
    t = (doc_title or "").lower()
    keys = (
        "cif",
        "constancia",
        "situacion",
        "situación",
        "csf",
        "cedula",
        "cédula",
        "identificacion fiscal",
        "identificación fiscal",
    )
    return any(k in t for k in keys)


def _build_company_queries(is_fisica: bool) -> List[str]:
    """Construye consultas robustas para recuperar contexto corporativo."""
    if is_fisica:
        return [
            "NOMBRE COMPLETO RFC CURP IDENTIDAD DIRECCION ACTIVIDAD ECONOMICA CEDULA FISCAL",
            "persona fisica representante legal nombre completo rfc",
            "domicilio fiscal codigo postal constancia situacion fiscal",
        ]
    return [
        "representante legal vigente administrador unico",
        "nuevo administrador unico nombramiento asamblea",
        "se designa apoderado legal",
        "asamblea general revocacion poderes nombramiento nuevo",
        "facultades para pleitos y cobranzas actos de administracion actos de dominio",
        "QUINTA resolucion asamblea socios accionistas",
        "objeto de la sociedad sera OBJETO SOCIAL TERCERA",
        "prestacion de servicios profesionales tecnicos operativos comercializacion",
        "recoleccion y reciclado de basura residuos limpieza mantenimiento",
        "MODIFICACION OBJETO SOCIAL REFORMA ESTATUTOS AMPLIACION",
        "actividad principal objeto social acta constitutiva clausula SEGUNDA",
        "razon social rfc objeto social domicilio",
        "domicilio fiscal codigo postal colonia constancia situacion fiscal cedula identificacion",
    ]


import re as _re

# Prefijos honoríficos / tratamientos que el OCR incluye pero NO deben ir en el nombre
_HONORIFIC_PREFIX_RE = _re.compile(
    r"^(?:"
    r"el\s+se[ñn]or|la\s+se[ñn]ora|se[ñn]or(?:ita)?|se[ñn]ora"
    r"|el\s+c\.|la\s+c\.|c\.\s*"
    r"|el\s+ing\.|la\s+ing\.|ing\.?\s*"
    r"|el\s+lic\.|la\s+lic\.|lic\.?\s*"
    r"|el\s+dr\.|la\s+dra?\.|dr\.?\s*|dra\.?\s*"
    r"|el\s+arq\.|arq\.?\s*"
    r"|el\s+mtro\.|la\s+mtra\.|mtro\.?\s*|mtra\.?\s*"
    r"|se[ñn]or\s+ingeniero|se[ñn]ora\s+ingeniera?"
    r"|se[ñn]or\s+licenciado|se[ñn]ora\s+licenciada?"
    r"|se[ñn]or\s+doctor|se[ñn]ora\s+doctora?"
    r")\s+",
    _re.IGNORECASE,
)


def _strip_honorifics(name: str) -> str:
    """Elimina prefijos de tratamiento del nombre del representante legal.

    Ejemplo: 'el señor ENRIQUE TADEO TORRES DORANTES' → 'ENRIQUE TADEO TORRES DORANTES'
    """
    if not name:
        return name
    cleaned = _HONORIFIC_PREFIX_RE.sub("", name.strip())
    return cleaned.strip()



def _is_llm_placeholder_profile_value(value: Any) -> bool:
    """
    Detecta texto que el modelo usa como negación narrada en lugar de ``No encontrado``.

    Esos valores no deben fusionarse al perfil (evitan pisar datos válidos previos).
    """
    if not isinstance(value, str):
        return False
    s = value.strip().lower()
    if len(s) < 12:
        return False
    needles = (
        "no se especifica",
        "no consta",
        "no aparece",
        "no se encuentra",
        "sin información",
        "sin informacion",
        "documentos proporcionados",
        "no hay información",
        "no hay informacion",
        "no se identifica",
        "no fue posible",
        "no se localiza",
        "no se observa",
        "fragmentos proporcionados",
        "en los documentos",
        "según los fragmentos",
    )
    return any(n in s for n in needles)


def _sanitize_llm_profile_placeholders(profile_data: Dict[str, Any]) -> None:
    """Normaliza campos de texto del JSON del LLM antes de fusionar con el perfil."""
    keys = (
        "representante_legal",
        "objeto_social",
        "poderes",
        "razon_social",
        "domicilio_fiscal",
    )
    for k in keys:
        v = profile_data.get(k)
        if isinstance(v, str) and _is_llm_placeholder_profile_value(v):
            profile_data[k] = "No encontrado"


def _merge_profile_with_hitl(existing_profile: Dict[str, Any], new_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge con precedencia mínima HITL:
    - no sobrescribe campos confirmados/manuales del usuario.
    """
    merged = dict(existing_profile or {})
    protected = set((existing_profile or {}).get("_manual_locked_fields", []))
    for key, value in (new_profile or {}).items():
        if key in protected and merged.get(key):
            continue
        if value in (None, "", "No encontrado"):
            continue
        if isinstance(value, str) and _is_llm_placeholder_profile_value(value):
            continue
        merged[key] = value
    return merged


def _meta_priority(meta: Dict[str, Any], text_chunk: str = "") -> int:
    """
    Prioriza fragmentos societarios en el contexto del LLM.
    Da prioridad máxima (10) a modificaciones y reformas recientes.
    """
    doc_type = (meta.get("doc_type") or "").lower()
    source = (meta.get("source") or "").lower()
    text = (text_chunk or "").lower()
    blob = f"{doc_type} {source} {text}"
    
    # PRIORIDAD MÁXIMA: Modificaciones y reformas legales (Universales)
    if any(k in blob for k in ("modificacion", "reforma", "ampliacion", "actualizacion", "estatutos", "objeto social", "actividades")):
        return 10
    
    if "asamblea" in blob:
        return 5
    if "poder" in blob or "apoderado" in blob:
        return 4
    if "acta" in blob:
        return 3
    if any(
        k in blob
        for k in (
            "cif",
            "constancia",
            "situacion",
            "situación",
            "csf",
            "identificacion fiscal",
            "identificación fiscal",
        )
    ):
        return 1
    return 0


_FORBIDDEN_RAZON_SOCIAL_TOKENS = (
    "INSTITUTO NACIONAL ELECTORAL",
    "CREDENCIAL PARA VOTAR",
    "CLAVE DE ELECTOR",
)
_WEAK_INE_CONTEXT_PATTERNS = (
    r"\bNOMBRE\s*[:\n]",
    r"\bDOMICILIO\s*[:\n]",
    r"\bA[ÑN]O\s+DE\s+REGISTRO\b",
)


def _apply_cif_constancia_patch(
    profile_data: Dict[str, Any],
    cif_blob: str,
    *,
    is_fisica: bool,
    existing_profile: Dict[str, Any],
) -> None:
    """
    Completa ``domicilio_fiscal`` y, en moral, ``razon_social`` desde texto CIF/constancia.

    No pisa campos bloqueados por HITL ni valores ya útiles del LLM.
    """
    blob = (cif_blob or "").strip()
    if not blob:
        return
    locked = set((existing_profile or {}).get("_manual_locked_fields", []))
    patch = extract_cif_company_profile_patch(blob, is_fisica=is_fisica)
    weak = {"", "no encontrado", "no encontrado.", "n/a", "s/d", "sd", "...", "no especificado"}

    if "domicilio_fiscal" not in locked:
        dom = (patch.get("domicilio_fiscal") or "").strip()
        if dom and len(dom) >= 10:
            cur = (profile_data.get("domicilio_fiscal") or "").strip()
            if not cur or cur.lower() in weak:
                profile_data["domicilio_fiscal"] = dom

    if not is_fisica and "razon_social" not in locked:
        rz = (patch.get("razon_social") or "").strip()
        if rz and _looks_like_valid_corporate_name(rz):
            cur = (profile_data.get("razon_social") or "").strip()
            if not cur or cur.lower() in weak:
                profile_data["razon_social"] = rz


# Triggers del parser con señal societaria fuerte: no dejar que el LLM pise con apoderado del acta viejo.
_MORAL_PARSER_TRIGGERS_OVERRIDE_LLM = frozenset(
    {
        "nombrar_como_nuevo_admin_unico",
        "se_nombra_admin_unico",
        "c_comparece_delegado_especial",
        "nombre_coma_caracter_delegado_especial",
        "c_nombre_hasta_caracter_delegado_especial",
        "delegado_especial_el_c_nombre",
        "presidente_asamblea_el_c",
        "presidente_mesa_directiva_el_c",
        "se_designa",
    }
)


def _apply_moral_representante_from_parser(
    profile_data: Dict[str, Any],
    parser_result: Dict[str, Any],
    existing_profile: Dict[str, Any],
) -> None:
    """
    Si el determinista detecta asamblea / delegado / designación explícita, prevalece
    sobre el nombre que devolvió el LLM (suele quedarse en apoderado del acta fundador).
    Respeta ``representante_legal`` bloqueado por HITL.
    """
    if not parser_result.get("found"):
        return
    locked = set((existing_profile or {}).get("_manual_locked_fields", []))
    if "representante_legal" in locked and (existing_profile.get("representante_legal") or "").strip():
        return
    llm_rep = (profile_data.get("representante_legal") or "").strip()
    parser_rep = (parser_result.get("representative") or "").strip()
    if not parser_rep:
        return
    trig = str(parser_result.get("trigger") or "")
    weak_llm = (not llm_rep) or llm_rep.lower() in {"no encontrado", "...", "no especificado"}
    if weak_llm or trig in _MORAL_PARSER_TRIGGERS_OVERRIDE_LLM:
        profile_data["representante_legal"] = parser_rep


def _looks_like_valid_corporate_name(value: str) -> bool:
    """Valida de forma conservadora si una razón social parece corporativa."""
    v = (value or "").strip()
    if len(v) < 5:
        return False
    upper = v.upper()
    corporate_hints = ("S.A.", "SAPI", "S DE", "DE C.V", "SOCIEDAD", "COMPAÑ", "COMPANIA", "SERVICIOS")
    has_hint = any(h in upper for h in corporate_hints)
    # Regla positiva explícita: si parece razón social corporativa, no bloquear por tokens débiles.
    if has_hint:
        return True
    if any(tok in upper for tok in _FORBIDDEN_RAZON_SOCIAL_TOKENS):
        return False
    if any(re.search(pat, upper) for pat in _WEAK_INE_CONTEXT_PATTERNS):
        return False
    # Fallback conservador: si huele a INE pero sin sufijo corporativo, rechazar.
    return " INE " not in f" {upper} "


def _sanitize_razon_social_for_moral(
    profile_data: Dict[str, Any],
    existing_profile: Dict[str, Any],
    company_name: str,
) -> None:
    """Evita contaminar razón social con texto de documentos personales (INE/CIF)."""
    rz = str(profile_data.get("razon_social") or "").strip()
    if _looks_like_valid_corporate_name(rz):
        return

    existing_rz = str((existing_profile or {}).get("razon_social") or "").strip()
    if _looks_like_valid_corporate_name(existing_rz):
        profile_data["razon_social"] = existing_rz
        return

    profile_data["razon_social"] = (company_name or rz or "No encontrado").strip()

@router.get("/", response_model=Dict)
async def list_companies():
    repo = await get_repository()
    try:
        companies = await repo.get_companies()
        return {"success": True, "data": companies}
    except AttributeError:
        # Fallback if MemoryRepository does not implement companies yet
        return {"success": False, "message": "Companies not implemented in adapter"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()

@router.post("/", response_model=Dict)
async def save_company(company: CompanyData):
    repo = await get_repository()
    try:
        company_id = company.id or str(uuid.uuid4())
        await repo.save_company(company_id, company.model_dump())
        updated = await repo.get_company(company_id)
        return {"success": True, "data": updated}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()

@router.get("/{company_id}", response_model=Dict)
async def get_company(company_id: str):
    repo = await get_repository()
    try:
        company = await repo.get_company(company_id)
        if not company:
            return {"success": False, "message": "Company not found"}
        return {"success": True, "data": company}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()

@router.delete("/{company_id}", response_model=Dict)
async def delete_company(company_id: str):
    repo = await get_repository()
    try:
        success = await repo.delete_company(company_id)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()

@router.post("/{company_id}/upload", response_model=Dict)
async def upload_company_doc(
    company_id: str, 
    background_tasks: BackgroundTasks,
    docTitle: str = Form(...), 
    file: UploadFile = File(...), 
    preview: str = Form(None)
):
    repo = await get_repository()
    try:
        company = await repo.get_company(company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        safe_filename = file.filename.replace(" ", "_").lower()
        file_path = os.path.join(UPLOAD_DIR, f"comp_{company_id}_{uuid.uuid4()}_{safe_filename}")
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_metadata = {
            "name": file.filename,
            "path": file_path,
            "date": "NOW",
            "preview": preview,
            "status": "UPLOADED" # Marcar como cargado para que el analista lo tome
        }

        # Update company object
        if not company.get("docs"):
            company["docs"] = {}
        company["docs"][docTitle] = file_metadata
        
        # ── FIX LOGO: Inyectar ruta en master_profile inmediatamente al subir ──
        # No esperar a analyze_company: si el usuario solo sube el logo sin otros
        # documentos, analyze_company retorna antes de llegar al bloque de inyección.
        if docTitle == "LOGOTIPO" and file_path:
            if not company.get("master_profile"):
                company["master_profile"] = {}
            company["master_profile"]["logo"] = file_path

        # Guardar estado de la empresa
        await repo.save_company(company_id, company)
        
        # Guardar estado de la empresa
        await repo.save_company(company_id, company)
        
        # Lanzar análisis en segundo plano (Background Task)
        background_tasks.add_task(analyze_company, company_id)
        
        # Retornar de inmediato para que el frontend no bloquee
        return {"success": True, "data": company}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()

@router.post("/{company_id}/analyze", response_model=Dict)
async def analyze_company(company_id: str, force_refresh: bool = False):
    repo = await get_repository()
    try:
        company = await repo.get_company(company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        # 1. Asegurar que todos los documentos nuevos tengan OCR e Indexación
        docs_to_process = company.get("docs", {})
        ocr_client = OCRServiceClient()
        vector_client = VectorDbServiceClient()
        vector_session = f"company_{company_id}"
        cif_text_blobs: List[str] = []

        processing_report: List[Dict] = []
        for doc_title, doc_info in docs_to_process.items():
            if doc_title != 'LOGOTIPO' and doc_info.get("status") in ["UPLOADED", "PROCESSING"]:
                print(f"[*] Procesando OCR diferido para: {doc_title} ({doc_info['name']})")
                doc_info["status"] = "PROCESSING"
                await repo.save_company(company_id, company) # Persistir estado intermedio
                
                file_path = doc_info["path"]
                ocr_ctx = await ocr_client.scan_document(file_path)

                if "error" in ocr_ctx or not ocr_ctx.get("success", False):
                    doc_info["status"] = "OCR_FAILED"
                    doc_info["ocr_error_type"] = "OCR_FAILED"
                    doc_info["ocr_error_message"] = ocr_ctx.get("error", "Fallo en cadena OCR.")
                    processing_report.append(
                        {
                            "doc_title": doc_title,
                            "filename": doc_info.get("name"),
                            "status": doc_info["status"],
                            "reason": doc_info["ocr_error_message"],
                            "method": ocr_ctx.get("method"),
                        }
                    )
                    continue

                quality = _extraction_quality(ocr_ctx)
                if not quality["ok"]:
                    doc_info["status"] = "LOW_TEXT_QUALITY"
                    doc_info["ocr_error_type"] = "LOW_TEXT_QUALITY"
                    doc_info["ocr_error_message"] = (
                        "Extracción insuficiente. Sube un PDF más legible o reintenta OCR."
                    )
                    doc_info["ocr_chars"] = quality["chars"]
                    doc_info["ocr_pages_with_text"] = quality["pages_with_text"]
                    processing_report.append(
                        {
                            "doc_title": doc_title,
                            "filename": doc_info.get("name"),
                            "status": doc_info["status"],
                            "reason": doc_info["ocr_error_message"],
                            "method": ocr_ctx.get("method"),
                            "chars": quality["chars"],
                            "pages_with_text": quality["pages_with_text"],
                        }
                    )
                    continue

                pages = ocr_ctx.get("pages", [])
                full_doc_text = (ocr_ctx.get("extracted_text") or "").strip()
                if not full_doc_text:
                    full_doc_text = "\n".join(
                        (p.get("text") or "").strip()
                        for p in pages
                        if (p.get("text") or "").strip()
                    )
                if (
                    _company_doc_title_suggests_cif(doc_title)
                    or is_constancia_cif_text(full_doc_text)
                ) and len(full_doc_text) >= 40:
                    cif_text_blobs.append(full_doc_text[:80000])

                for page in pages:
                    p_text = page.get("text", "")
                    if p_text:
                        chunks = _chunk_text(p_text, 1500, 200)
                        metadatas = [
                            {
                                "source": doc_info["name"],
                                "company": company_id,
                                "doc_type": doc_title,
                                "method": ocr_ctx.get("method", "unknown"),
                            }
                            for _ in chunks
                        ]
                        vector_client.add_texts(vector_session, chunks, metadatas)
                doc_info["status"] = "ANALYZED"
                doc_info["ocr_pages"] = len(pages)
                doc_info["ocr_chars"] = quality["chars"]
                doc_info["ocr_pages_with_text"] = quality["pages_with_text"]
                processing_report.append(
                    {
                        "doc_title": doc_title,
                        "filename": doc_info.get("name"),
                        "status": doc_info["status"],
                        "method": ocr_ctx.get("method"),
                        "chars": quality["chars"],
                        "pages_with_text": quality["pages_with_text"],
                    }
                )
        
        # Guardar estados de procesamiento
        await repo.save_company(company_id, company)

        # Diferenciar búsqueda según tipo de empresa
        is_fisica = company.get("type") == "fisica"

        queries = _build_company_queries(is_fisica)
        docs: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        seen_doc_chunks = set()
        for query in queries:
            results = vector_client.query_texts(vector_session, query, n_results=25)
            q_docs = results.get("documents", []) or []
            q_metas = results.get("metadatas", []) or []
            for idx, qdoc in enumerate(q_docs):
                doc_key = (qdoc or "").strip()
                if not doc_key or doc_key in seen_doc_chunks:
                    continue
                seen_doc_chunks.add(doc_key)
                docs.append(qdoc)
                metadatas.append(q_metas[idx] if idx < len(q_metas) else {})

        if docs and metadatas and len(docs) == len(metadatas):
            pairs = list(zip(docs, metadatas))
            pairs.sort(key=lambda p: _meta_priority(p[1], p[0]), reverse=True)
            docs = [p[0] for p in pairs]
            metadatas = [p[1] for p in pairs]

        if not docs:
            await repo.save_company(company_id, company)
            updated_company = await repo.get_company(company_id)
            return {
                "success": False,
                "message": "No hay contexto textual suficiente para extraer perfil corporativo. Verifica calidad OCR de documentos.",
                "data": updated_company,
                "profile": company.get("master_profile", {}),
                "processing_report": processing_report,
            }
        if docs:
            # Optimizado para Gemini 1.5: 50 fragmentos de alta calidad (4k cada uno)
            docs = docs[:50]
            metadatas = metadatas[:50]
            
        context = "\n---\n".join(docs) if docs else "No context found."

        parser_result = detect_legal_representative(context)

        # Extraer usando LLM
        if is_fisica:
            system_prompt = (
                "Eres un experto legal auditando documentos de Personas Físicas mexicanas (INE/CIF).\n"
                "Tu tarea es identificar los datos fiscales y personales del individuo.\n"
                "En el JSON escribe solo datos literales; si falta un dato usa exactamente: No encontrado"
            )
            prompt = (
                "Con base en los documentos proporcionados (INE/CIF):\n"
                f"{context}\n\n"
                "Extrae la siguiente información y devuélvela ESTRICTAMENTE como un JSON válido:\n"
                "{\n"
                '  "rfc": "El RFC de la persona",\n'
                '  "razon_social": "Nombre completo de la persona física (nombre y apellidos)",\n'
                '  "representante_legal": "Mismo nombre completo de la persona física",\n'
                '  "domicilio_fiscal": "Domicilio fiscal completo según constancia/CIF (calle, colonia, CP, ciudad/estado) si consta",\n'
                '  "poderes": "Actuación en nombre propio",\n'
                '  "objeto_social": "Actividad económica principal del SAT"\n'
                "}\n"
                "Si no encuentras algún dato, escribe 'No encontrado'."
            )
        else:
            system_prompt = (
                "Eres un experto legal auditando documentos corporativos mexicanos y ASAMBLEAS.\n"
                "REGLA DE VERDAD: Las MODIFICACIONES de estatutos invalidan el acta original. Si encuentras fragmentos de una 'Modificación', 'Reforma', 'Ampliación' o 'Asamblea Extraordinaria', usa ESE objeto social y descarta el original.\n"
                "REGLA DE OBJETO: Prohibido resumir. Si el objeto social tiene categorías o encabezados internos (ej: 'En Seguridad y Servicio', 'En Construcción', 'Servicios Técnicos'), asume que son parte del objeto de ESTA empresa y transcríbelos íntegros.\n"
                "REGLA DE ORO: Si ves las palabras 'basura', 'limpieza', 'recolección', 'reciclaje' o 'mantenimiento', DEBES incluirlas en el objeto_social. Ignora si el título parece referirse a otra entidad; en estos documentos suelen listarse así las ramas de la misma empresa.\n"
                "REGLA CRÍTICA: Debes identificar al representante legal VIGENTE.\n"
                "En cada clave del JSON escribe SOLO el dato literal. "
                "Prohibido narrar, justificar o usar lenguaje genérico; si no hay dato usa exactamente: No encontrado"
            )
            prompt = (
                "Analiza TODOS estos fragmentos de actas, asambleas y anexos societarios:\n"
                f"{context}\n\n"
                "TAREA DE PENSAMIENTO (Chain of Thought):\n"
                "1. Haz una lista mental de TODAS las actividades mencionadas en las cláusulas de objeto social o reformas.\n"
                "2. Busca específicamente si se menciona 'recolección de basura', 'reciclaje', 'limpieza' o 'mantenimiento'.\n"
                "3. Consolida todo en el campo 'objeto_social' del JSON.\n\n"
                "Genera el JSON final con esta estructura:\n"
                "{\n"
                '  "rfc": "RFC de la empresa",\n'
                '  "razon_social": "Razón social completa",\n'
                '  "representante_legal": "Nombre COMPLETO del representante VIGENTE",\n'
                '  "domicilio_fiscal": "Domicilio fiscal o No encontrado",\n'
                '  "poderes": "Facultades vigentes",\n'
                '  "objeto_social": "TEXTO LITERAL COMPLETO"\n'
                "}\n"
                "REGLAS CRÍTICAS:\n"
                "1. RFC (persona moral): exactamente 3 letras iniciales (ej. SPI060200AG5). NO uses RFC de persona física (4 letras).\n"
                "2. Representante legal VIGENTE: DEBE SER UN NOMBRE HUMANO (Ej: Juan Pérez García). Busca a la persona designada como Administrador Único o Apoderado en la asamblea más reciente.\n"
                "3. Objeto social: TRANSCRIPCIÓN LITERAL Y COMPLETA. Prioriza siempre las MODIFICACIONES o REFORMAS estatutarias sobre el acta original. Si un fragmento menciona 'recolección de basura' o 'limpieza', inclúyelo palabra por palabra. NO resumas ni uses frases como 'gestión empresarial' si el texto es específico. PROHIBIDO RESUMIR.\n"
                "4. EXCLUSIONES ESTRICTAS: No pongas al Notario. NO extraigas frases notariales como 'quien acepta dicho nombramiento' o 'se le otorga poder'. Si no encuentras un nombre humano claro, escribe 'No encontrado'."
            )
        
        profile_data: Dict[str, Any] = {}
        raw_json_text = ""
        llm = LLMServiceClient()
        response = await llm.generate(prompt=prompt, system_prompt=system_prompt, format="json")
        raw_json_text = response.get("response", "").strip()
        try:
            profile_data = json.loads(raw_json_text) if raw_json_text else {}
        except Exception:
            profile_data = {"raw_llm_output": raw_json_text}

        if isinstance(profile_data, dict) and "raw_llm_output" not in profile_data:
            _sanitize_llm_profile_placeholders(profile_data)

        existing_profile = company.get("master_profile", {}) or {}
        cif_blob = "\n\n---CIF---\n\n".join(cif_text_blobs)
        if cif_blob.strip():
            _apply_cif_constancia_patch(
                profile_data,
                cif_blob,
                is_fisica=is_fisica,
                existing_profile=existing_profile,
            )

        # Persona física: ancla desde CIF/constancia (etiquetas SAT) antes del nombre genérico de la empresa
        if is_fisica:
            cif_name = detect_cif_contribuyente_name(context)
            if cif_name.get("found"):
                fn = (cif_name.get("full_name") or "").strip()
                if fn:
                    rep = (profile_data.get("representante_legal") or "").strip()
                    rz = (profile_data.get("razon_social") or "").strip()
                    if not rep or rep.lower() == "no encontrado":
                        profile_data["representante_legal"] = fn
                    if not rz or rz.lower() == "no encontrado":
                        profile_data["razon_social"] = fn

        # Persona física: último recurso, nombre registrado en la ficha de empresa
        if is_fisica:
            rep = (profile_data.get("representante_legal") or "").strip()
            rz = (profile_data.get("razon_social") or "").strip()
            if not rep or rep.lower() == "no encontrado":
                profile_data["representante_legal"] = company.get("name")
            if not rz or rz.lower() == "no encontrado":
                profile_data["razon_social"] = company.get("name") or profile_data.get(
                    "representante_legal"
                )

        # Parser determinista: persona moral prioriza asamblea / delegado sobre salida del LLM.
        if not is_fisica:
            _apply_moral_representante_from_parser(profile_data, parser_result, existing_profile)

        # Persona moral: sanea razón social para evitar contaminación por OCR de INE.
        if not is_fisica:
            _sanitize_razon_social_for_moral(
                profile_data=profile_data,
                existing_profile=existing_profile,
                company_name=company.get("name", ""),
            )

        rfc_resolution: Dict[str, Any] = {}
        if not is_fisica:
            rfc_resolution = resolve_rfc_persona_moral(context, profile_data.get("rfc"))
            locked_fields = set((existing_profile or {}).get("_manual_locked_fields", []))
            if "rfc" not in locked_fields:
                final_rfc = (rfc_resolution.get("value") or "").strip()
                if final_rfc:
                    profile_data["rfc"] = final_rfc.upper()
            elif existing_profile.get("rfc"):
                # Coherencia de procedencia: no sustituir valor bloqueado por HITL.
                profile_data["rfc"] = existing_profile.get("rfc")

        # Preservar campos de dirección si ya existían (adicionados manualmente)
        for field in ["calle", "numero", "colonia", "ciudad", "cp", "telefono", "web", "logo", "tipo"]:
            if existing_profile.get(field) and not profile_data.get(field):
                profile_data[field] = existing_profile[field]

        # Inyectar logo desde docs si existe
        logotipo_doc = company.get("docs", {}).get("LOGOTIPO", {})
        if logotipo_doc and logotipo_doc.get("path"):
            profile_data["logo"] = logotipo_doc["path"]

        # Limpiar honoríficos del nombre del representante legal
        if profile_data.get("representante_legal"):
            profile_data["representante_legal"] = _strip_honorifics(profile_data["representante_legal"])

        representative_value = profile_data.get("representante_legal")
        representative_meta: Dict[str, Any] = {}
        if representative_value:
            # Heurística de vigencia documental: asamblea > poder > acta.
            if metadatas:
                representative_meta = sorted(metadatas, key=lambda m: _meta_priority(m), reverse=True)[0]

        rfc_value = profile_data.get("rfc")
        rfc_meta: Dict[str, Any] = {}
        if rfc_value and metadatas:
            rfc_meta = sorted(metadatas, key=lambda m: _meta_priority(m), reverse=True)[0]

        provenance_ui: Dict[str, Any] = {
            "representante_legal": {
                "field": "representante_legal",
                "value": representative_value,
                "source_doc": representative_meta.get("source"),
                "page": representative_meta.get("page"),
                "method": representative_meta.get("method"),
                "confidence": parser_result.get("confidence", 0.0) if parser_result.get("found") else 0.6,
                "evidence_snippet": parser_result.get("evidence", "") if parser_result.get("found") else (docs[0][:280] if docs else ""),
                "strategy": parser_result.get("strategy", "llm") if parser_result.get("found") else "llm",
            }
        }
        if not is_fisica and rfc_resolution:
            prev_llm = rfc_resolution.get("previous_llm")
            provenance_ui["rfc"] = {
                "field": "rfc",
                "value": rfc_value,
                "source_doc": rfc_meta.get("source"),
                "page": rfc_meta.get("page"),
                "method": rfc_meta.get("method"),
                "confidence": 0.92 if rfc_resolution.get("strategy", "").startswith("deterministic") else 0.72,
                "evidence_snippet": (rfc_resolution.get("evidence_snippet") or "")[:320],
                "strategy": rfc_resolution.get("strategy", "llm"),
                "previous_llm_value": prev_llm if rfc_resolution.get("changed") else None,
            }
        elif rfc_value:
            provenance_ui["rfc"] = {
                "field": "rfc",
                "value": rfc_value,
                "source_doc": rfc_meta.get("source"),
                "page": rfc_meta.get("page"),
                "method": rfc_meta.get("method"),
                "confidence": 0.65,
                "evidence_snippet": (docs[0][:280] if docs else ""),
                "strategy": "llm",
                "previous_llm_value": None,
            }

        profile_data["provenance_ui"] = provenance_ui

        merged_profile = _merge_profile_with_hitl(existing_profile, profile_data)
        company["master_profile"] = merged_profile
        await repo.save_company(company_id, company)
        updated_company = await repo.get_company(company_id)

        out: Dict[str, Any] = {
            "success": True,
            "data": updated_company,
            "profile": merged_profile,
            "processing_report": processing_report,
        }
        if not is_fisica and rfc_resolution:
            resolved_val = str(rfc_resolution.get("value") or "").strip().upper()
            saved_val = str(merged_profile.get("rfc") or "").strip().upper()
            correction_applied = bool(resolved_val and saved_val == resolved_val)
            out["rfc_resolution"] = {
                "final_rfc": merged_profile.get("rfc"),
                "previous_llm_rfc": rfc_resolution.get("previous_llm"),
                "strategy": rfc_resolution.get("strategy"),
                "changed_from_llm": bool(rfc_resolution.get("changed")) and correction_applied,
                "evidence_snippet": (rfc_resolution.get("evidence_snippet") or "")[:320],
                "reanalyze_hint": (
                    "Tras actualizar documentos en el expediente, usa de nuevo «RE-ANALIZAR EXPEDIENTE» "
                    "para refrescar el perfil con el OCR más reciente."
                ),
            }
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()
