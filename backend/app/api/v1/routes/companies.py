from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from typing import Dict, List
import uuid
import os
import shutil
import json

from pydantic import BaseModel
from app.api.v1.routes.sessions import get_repository
from app.services.ocr_service import OCRServiceClient
from app.services.vector_service import VectorDbServiceClient
from app.services.llm_service import LLMServiceClient

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

def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]

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
async def upload_company_doc(company_id: str, docTitle: str = Form(...), file: UploadFile = File(...), preview: str = Form(None)):
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
            "status": "UPLOADED" # Marcar como cargado pero no procesado
        }

        # Update company object
        if not company.get("docs"):
            company["docs"] = {}
        company["docs"][docTitle] = file_metadata
        
        # Save updated company
        await repo.save_company(company_id, company)
        updated_company = await repo.get_company(company_id)

        return {"success": True, "data": updated_company}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()

@router.post("/{company_id}/analyze", response_model=Dict)
async def analyze_company(company_id: str):
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
        
        for doc_title, doc_info in docs_to_process.items():
            if doc_title != 'LOGOTIPO' and doc_info.get("status") == "UPLOADED":
                print(f"[*] Procesando OCR diferido para: {doc_title} ({doc_info['name']})")
                file_path = doc_info["path"]
                ocr_ctx = await ocr_client.scan_document(file_path)
                
                if "error" not in ocr_ctx:
                    pages = ocr_ctx.get("pages", [])
                    for page in pages:
                        p_text = page.get("text", "")
                        if p_text:
                            chunks = _chunk_text(p_text, 1500, 200)
                            metadatas = [{"source": doc_info["name"], "company": company_id, "doc_type": doc_title} for _ in chunks]
                            vector_client.add_texts(vector_session, chunks, metadatas)
                    doc_info["status"] = "ANALYZED"
                    doc_info["ocr_pages"] = len(pages)
        
        # Guardar estados de procesamiento
        await repo.save_company(company_id, company)

        # Diferenciar búsqueda según tipo de empresa
        is_fisica = company.get("type") == "fisica"
        
        if is_fisica:
            query = "NOMBRE COMPLETO, RFC, CURP, IDENTIDAD, DIRECCIÓN, ACTIVIDAD ECONÓMICA, CEDULA IDENTIFICACIÓN FISCAL"
        else:
            query = (
                "NUEVO ADMINISTRADOR ÚNICO, DESIGNACIÓN DE NUEVO REPRESENTANTE, NOMBRAR COMO NUEVO, "
                "ASAMBLEA GENERAL, ORDEN DEL DÍA, REVOCACIÓN DE PODERES, "
                "ADMINISTRADOR UNICO, ADMINISTRADOR ÚNICO, PRESIDENTE DEL CONSEJO, REPRESENTANTE LEGAL, "
                "APODERADO LEGAL, NOMBRAMIENTOS, CLAUSULA DE ADMINISTRACIÓN Y VIGILANCIA, "
                "designando para tal cargo al señor, se designa a, FACULTADES PARA PLEITOS Y COBRANZAS, "
                "ACTOS DE ADMINISTRACIÓN, ACTOS DE DOMINIO, RAZÓN SOCIAL, OBJETO SOCIAL, RFC"
            )
        
        results = vector_client.query_texts(vector_session, query, n_results=80)
        
        docs = results.get("documents", [])
        context = "\n---\n".join(docs) if docs else "No context found."

        # Extraer usando LLM
        if is_fisica:
            system_prompt = (
                "Eres un experto legal auditando documentos de Personas Físicas mexicanas (INE/CIF).\n"
                "Tu tarea es identificar los datos fiscales y personales del individuo."
            )
            prompt = (
                "Con base en los documentos proporcionados (INE/CIF):\n"
                f"{context}\n\n"
                "Extrae la siguiente información y devuélvela ESTRICTAMENTE como un JSON válido:\n"
                "{\n"
                '  "rfc": "El RFC de la persona",\n'
                '  "razon_social": "Nombre completo de la persona física (nombre y apellidos)",\n'
                '  "representante_legal": "Mismo nombre completo de la persona física",\n'
                '  "poderes": "Actuación en nombre propio",\n'
                '  "objeto_social": "Actividad económica principal del SAT"\n'
                "}\n"
                "Si no encuentras algún dato, escribe 'No encontrado'."
            )
        else:
            system_prompt = (
                "Eres un experto legal auditando documentos corporativos mexicanos y ASAMBLEAS.\n"
                "REGLA CRÍTICA: Debes identificar al representante legal VIGENTE.\n"
                "A menudo, el Acta Constitutiva original es modificada por ASAMBLEAS posteriores.\n"
                "Busca frases como 'Nombramiento de un NUEVO Administrador Único' o 'Se designa como NUEVO...'.\n"
                "Si encuentras una sección de 'ORDEN DEL DÍA' con 'Nombramiento', esa persona es la que firma actualmente.\n"
                "PRIORIDAD ABSOLUTA: Si hay varios nombres, quédate con el que sea nombrado como 'NUEVO' o el que aparezca al final de la cronología del documento."
            )
            prompt = (
                "Analiza TODOS estos fragmentos de actas y asambleas:\n"
                f"{context}\n\n"
                "Extrae los datos en este JSON:\n"
                "{\n"
                '  "rfc": "RFC de la empresa",\n'
                '  "razon_social": "Razón Social completa",\n'
                '  "representante_legal": "Nombre COMPLETO de la persona designada como NUEVO ADMINISTRADOR o REPRESENTANTE VIGENTE (ej. YUNUEN IVON ACEVES SANCHEZ)",\n'
                '  "poderes": "Resumen de las facultades vigentes",\n'
                '  "objeto_social": "Objeto social resumido"\n'
                "}\n"
                "OJO: No pongas al Notario, busca al ACCIONISTA o PERSONA designada en la Asamblea."
            )
        
        llm = LLMServiceClient()
        response = await llm.generate(prompt=prompt, system_prompt=system_prompt, format="json")
        
        raw_json_text = response.get("response", "").strip()
        
        try:
            profile_data = json.loads(raw_json_text)
        except:
            profile_data = {"raw_llm_output": raw_json_text}

        # Pequeña lógica de limpieza para Persona Física si falló el nombre
        if is_fisica and profile_data.get("representante_legal") == "No encontrado":
             profile_data["representante_legal"] = company.get("name")
             profile_data["razon_social"] = company.get("name")

        # Preservar campos de dirección si ya existían (adicionados manualmente)
        existing_profile = company.get("master_profile", {})
        for field in ["calle", "numero", "colonia", "ciudad", "cp", "telefono", "web", "logo", "tipo"]:
            if existing_profile.get(field) and not profile_data.get(field):
                profile_data[field] = existing_profile[field]

        # Inyectar logo desde docs si existe
        logotipo_doc = company.get("docs", {}).get("LOGOTIPO", {})
        if logotipo_doc and logotipo_doc.get("path"):
            profile_data["logo"] = logotipo_doc["path"]

        company["master_profile"] = profile_data
        await repo.save_company(company_id, company)
        updated_company = await repo.get_company(company_id)

        return {"success": True, "data": updated_company, "profile": profile_data}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.disconnect()
