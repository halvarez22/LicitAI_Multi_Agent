import asyncio
import os
import sys

# Agregar el path del backend para poder importar modulos
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

from app.agents.extractor_vision import VisionExtractorAgent
from app.agents.extractor_digital import DigitalExtractorAgent

async def run_test():
    file_name = "7d400ae0-7ca7-446e-ab19-c95c2335e685_bases_licitacion_opm-001-2026.pdf"
    file_path = os.path.join("/data/uploads", file_name)
    
    print("==================================================")
    print("🛠️ INICIANDO PRUEBA DE LABORATORIO: DOBLE AGENTE")
    print(f"📄 Archivo Objetivo: {file_name}")
    print("==================================================\n")

    # 1. Prueba Lector Digital (debería fallar rápido por ser imágenes)
    print("▶️ PASO 1: Disparando DigitalExtractorAgent (Bisturí)...")
    digital_agent = DigitalExtractorAgent()
    result_digital = await digital_agent.extract(file_path)
    
    if result_digital.get("success"):
        print("❌ FALLO DE LÓGICA: El agente digital extrajo texto de un PDF pesado de imágenes.")
        print(f"Texto extraído (muestra): {result_digital.get('extracted_text','')[:200]}")
        return
    else:
        print(f"✅ COMPORTAMIENTO ESPERADO: El Bisturí detectó el escaneo y abortó. Razón: {result_digital.get('reason')}")
    
    # 2. Prueba Ojo Forense (Pesado)
    print("\n▶️ PASO 2: Lanzando VisionExtractorAgent (Tanque Forense)...")
    print("⏳ Esto puede tomar varios minutos debido a las pausas de limpieza de RAM...")
    
    vision_agent = VisionExtractorAgent()
    result_vision = await vision_agent.extract(file_path)
    
    if result_vision.get("success"):
        print("\n🏆 ¡EXTRACCIÓN EXITOSA!")
        total_chars = len(result_vision.get("extracted_text", ""))
        total_pages = result_vision.get("total_pages", "N/A")
        print(f"📊 Estadísticas: {total_pages} páginas, {total_chars} caracteres.")
        print(f"\n📝 MUESTRA DEL TEXTO EXTRAÍDO (Primeros 1500 chars):")
        print("--------------------------------------------------")
        print(result_vision.get("extracted_text", "")[:1500])
        print("--------------------------------------------------")
    else:
        print(f"\n❌ FALLO DE EXTRACCIÓN VISUAL: {result_vision.get('error')}")

if __name__ == "__main__":
    asyncio.run(run_test())
