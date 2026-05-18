import asyncio
import os
import sys

# La carpeta /app ya está en el path en el contenedor
from app.agents.extractor_vision import VisionExtractorAgent

async def run_extraction():
    # En el contenedor, host.docker.internal es el host (Ollama)
    agent = VisionExtractorAgent(ollama_url="http://host.docker.internal:11434")
    # Analizar las primeras 10 páginas para estar seguros
    os.environ["VISION_MAX_PAGES"] = "10"
    
    file_path = "/app/acta_to_analyze.pdf"
    print(f"[*] Procesando {file_path}...")
    result = await agent.extract(file_path)
    
    if result.get("success"):
        print("EXTRACTION SUCCESSFUL")
        print("---")
        print(result.get("extracted_text"))
        print("---")
    else:
        print("EXTRACTION FAILED")
        print(result.get("error"))

if __name__ == "__main__":
    asyncio.run(run_extraction())
