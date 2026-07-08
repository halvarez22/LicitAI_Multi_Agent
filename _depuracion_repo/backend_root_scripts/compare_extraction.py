import fitz
import asyncio
from app.services.ocr_service import OCRServiceClient
import time
import os

async def main():
    pdf_path = "data/uploads/test.pdf"
    
    print("=== EXTRACCIÓN MANUAL (FITZ) ===")
    start = time.time()
    try:
        doc = fitz.open(pdf_path)
        manual_pages = []
        for i in range(len(doc)):
            manual_pages.append(doc[i].get_text())
        manual_text = "\n".join(manual_pages)
        print(f"Páginas detectadas: {len(doc)} | Caracteres extraídos: {len(manual_text)} | Tiempo: {time.time()-start:.2f}s")
    except Exception as e:
        print(f"Error extrayendo manualmente: {e}")
        return

    print("\n=== EXTRACCIÓN DEL AGENTE (OCR-VLM) ===")
    start = time.time()
    ocr = OCRServiceClient()
    # Path inside container must be absolute or relative to where backend is. data/uploads is inside backend.
    result = await ocr.scan_document(pdf_path)
    if "error" in result:
        print(f"Error en OCR: {result['error']}")
        return
    
    agent_pages = result.get("pages", [])
    agent_text_list = []
    for page in agent_pages:
        agent_text_list.append(page.get("text", ""))
    
    agent_text = "\n".join(agent_text_list)
    print(f"Páginas detectadas: {len(agent_pages)} | Caracteres extraídos: {len(agent_text)} | Tiempo: {time.time()-start:.2f}s")

    print("\n=== DIAGNÓSTICO DE EXTRACCIÓN ===")
    print(f"Longitud Manual: {len(manual_text)}")
    print(f"Longitud Agente: {len(agent_text)}")
    
    diff = len(agent_text) - len(manual_text)
    if diff > 0:
        print(f"Diferencia: {diff} caracteres a FAVOR del agente (El agente extrajo MÁS que mi script).")
    elif diff < 0:
        print(f"Diferencia: {abs(diff)} caracteres de DEFICIT del agente (El agente es INCOMPLETO comparado conmigo).")
    else:
        print("¡EXACTAMENTE LOS MISMOS CARACTERES!")
        
    # Comprobar si hay vacíos puros
    empty_agent_pages = [i+1 for i, text in enumerate(agent_text_list) if not text.strip()]
    if empty_agent_pages:
        print(f"¡ALERTA ROJA! El agente devolvió páginas VACÍAS y perdió texto: {empty_agent_pages}")
    else:
        print("✅ No se detectaron páginas vacías en el Agente.")
    
    # Comprobar secciones principales
    keywords_to_check = ["LIMPIEZA", "ISSSTE", "CONVOCATORIA", "ANEXO", "GARANTÍA"]
    print("\nVerificando palabras clave críticas en la extracción del Agente:")
    ag_upper = agent_text.upper()
    for kw in keywords_to_check:
        print(f" - {kw}: {'✅ PRESENTE' if kw in ag_upper else '❌ FALTANTE'}")
        
    print("\n== Comparación Letra por Letra (Muestra primeros 200 caracteres de Pag 2 si existe) ==")
    if len(manual_pages) > 1 and len(agent_text_list) > 1:
        print(f">>> MANUAL:\n{repr(manual_pages[1][:250])}\n")
        print(f">>> AGENTE:\n{repr(agent_text_list[1][:250])}\n")

if __name__ == "__main__":
    asyncio.run(main())
