from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form
from pdf2image import convert_from_bytes, pdfinfo_from_path
from PIL import Image
import io
import os
import uuid
import tempfile
import asyncio
import torch
from transformers import AutoModel, AutoTokenizer

app = FastAPI(title="GLM-OCR VLM Engine - LicitAI", version="4.0.0")

# Almacén de tareas en memoria
tasks: Dict[str, Any] = {}

# Variables globales para el VLM
vlm_model = None
vlm_tokenizer = None
device = "cuda" if torch.cuda.is_available() else "cpu"
MODEL_NAME = os.getenv("MODEL_NAME", "zai-org/GLM-OCR")

@app.on_event("startup")
async def load_model():
    """Carga el modelo VLM en la GPU de manera asíncrona solo si no se ha cargado."""
    global vlm_model, vlm_tokenizer
    print(f"[*] Inicializando Motor VLM OCR: {MODEL_NAME} en {device.upper()}")
    try:
        import transformers.models.glm_ocr.modeling_glm_ocr as mod
        vlm_model = mod.GlmOcrForConditionalGeneration.from_pretrained(
            MODEL_NAME, 
            trust_remote_code=True,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            low_cpu_mem_usage=True,
            device_map="cuda" if device == "cuda" else None
        )
        if device == "cuda":
            vlm_model = vlm_model.eval()
            
        vlm_tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
        print(f"[+] VLM {MODEL_NAME} Cargado Correctamente. Listo para procesamiento de alta fidelidad.")
    except Exception as e:
        print(f"[!] Error crítico al cargar el modelo VLM: {e}")
        vlm_model = "ERROR"

@app.get("/health")
def health_check():
    loaded = (vlm_model is not None and vlm_model != "ERROR")
    return {"status": "ok", "version": "4.0-vlm", "model_loaded": loaded, "device": device}

@app.post("/api/v1/extract")
async def extract_text_async(
    background_tasks: BackgroundTasks, 
    file_path: str = Form(...)
):
    """Inicia una tarea de OCR con VLM."""
    task_id = str(uuid.uuid4())
    if not os.path.exists(file_path): raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if vlm_model == "ERROR": raise HTTPException(status_code=503, detail="El modelo VLM no disponible.")

    try:
        with open(file_path, "rb") as f:
            content = f.read()
            
        tasks[task_id] = {"status": "pending", "progress": 0, "filename": os.path.basename(file_path), "result": None}
        background_tasks.add_task(process_ocr_vlm_task, task_id, content, os.path.basename(file_path))
        return {"task_id": task_id, "status": "processing"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return tasks[task_id]

def perform_vlm_inference(img: Image.Image) -> str:
    """Extrae texto de la imagen usando el modelo VLM GLM-OCR o Fallback EasyOCR."""
    global vlm_model, vlm_tokenizer
    try:
        if vlm_model is None or vlm_model == "ERROR":
            raise ValueError("VLM no disponible")
            
        query = "Extráe todo el texto de la imagen de forma exacta."
        inputs = vlm_tokenizer.apply_chat_template([{"role": "user", "image": img.convert("RGB"), "content": query}], add_generation_prompt=True, tokenize=True, return_tensors="pt", return_dict=True)
        inputs = inputs.to("cuda" if torch.cuda.is_available() else "cpu")
        
        gen_kwargs = {"max_new_tokens": 2048, "do_sample": False}
        with torch.no_grad():
            if hasattr(vlm_model, 'generate'):
                outputs = vlm_model.generate(**inputs, **gen_kwargs)
                response = vlm_tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
                return response
            else:
                raise AttributeError("El modelo cargado no tiene el método 'generate'")
                
    except Exception as e:
        print(f"[!] Fallo VLM ({e}). Activando Fallback EasyOCR Militar...")
        try:
            import easyocr
            import numpy as np
            import warnings
            warnings.filterwarnings("ignore", category=UserWarning)
            reader = easyocr.Reader(['es'], gpu=(torch.cuda.is_available()), verbose=False)
            results = reader.readtext(np.array(img.convert('RGB')))
            text = "\n".join([r[1] for r in results])
            del reader
            return text if text.strip() else "[Página Vacía / Solo Imagen]"
        except Exception as fallback_e:
            print(f"Error Crítico OCR Fallback: {fallback_e}")
            return f"[Error VLM y Fallback: {str(fallback_e)}]"

async def process_ocr_vlm_task(task_id: str, content: bytes, filename: str):
    print(f"START: [VLM OCR] Task {task_id} processing {filename} ({len(content)} bytes)")
    try:
        ext = filename.lower().split(".")[-1]
        extracted_pages = []
        full_text = ""

        if ext == "pdf":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                info = pdfinfo_from_path(tmp_path)
                total_pages = int(info['Pages'])
                batch_size = 1 # Reducimos batch a 1 para VLM (más pesado en VRAM que EasyOCR)
                
                print(f"[*] Procesando {total_pages} páginas de {filename} con GLM-OCR...")
                
                import gc
                from pdf2image import convert_from_path
                for start in range(1, total_pages + 1, batch_size):
                    end = min(start + batch_size - 1, total_pages)
                    
                    try:
                        # Usamos DPI 200, pero leyendo desde disco, no desde RAM (convert_from_path)
                        images = convert_from_path(tmp_path, dpi=200, first_page=start, last_page=end, fmt="jpeg")
                    except Exception:
                        print(f"[!] Fallo en DPI 200, reintentando con DPI 150 para pág {start}")
                        images = convert_from_path(tmp_path, dpi=150, first_page=start, last_page=end, fmt="jpeg")
                    
                    for i, img in enumerate(images):
                        curr_page = start + i
                        
                        # Inferencia VLM real
                        await asyncio.sleep(0.01)
                        # Llamamos al modelo VLM
                        text = perform_vlm_inference(img)
                        
                        extracted_pages.append({
                            "page": curr_page,
                            "text": text.strip()
                        })
                        full_text += f"\n--- PÁGINA {curr_page} ---\n{text.strip()}\n"
                        tasks[task_id]["progress"] = round((curr_page / total_pages) * 100)
                        print(f"[+] Pág {curr_page}/{total_pages} (VLM) OK - {len(text)} chars.")

                        # Liberación agresiva de VRAM por cada página
                        del img
                    
                    del images
                    gc.collect() # Liberación RAM sistema fuerte
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    await asyncio.sleep(0.05)

                tasks[task_id]["result"] = {
                    "total_pages": total_pages,
                    "extracted_text": full_text.strip(),
                    "pages": extracted_pages
                }
                tasks[task_id]["status"] = "completed"
                tasks[task_id]["progress"] = 100
                print(f"🥇 ÉXITO VLM: {filename} extraído con GLM-OCR ({len(full_text)} chars)")

            finally:
                if os.path.exists(tmp_path): os.remove(tmp_path)

        else:
            # Procesamiento de imágenes (PNG, JPG)
            img = Image.open(io.BytesIO(content)).convert('RGB')
            text = perform_vlm_inference(img)
            tasks[task_id]["result"] = {
                "total_pages": 1,
                "extracted_text": text.strip(),
                "pages": [{"page": 1, "text": text.strip()}]
            }
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["progress"] = 100

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)
        import traceback
        traceback.print_exc()
