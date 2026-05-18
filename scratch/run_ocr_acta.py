import asyncio
import os
import sys

# Añadir el backend al path para que encuentre 'app'
sys.path.append(r"c:\LicitAI_Multi_Agent\licitaciones-ai\backend")

from app.agents.extractor_vision import VisionExtractorAgent

async def main():
    agent = VisionExtractorAgent(ollama_url="http://localhost:11434")
    # Solo procesar las primeras 3 páginas para rapidez y detectar al representante
    os.environ["VISION_MAX_PAGES"] = "3"
    
    file_path = r"C:\LicitAI_Multi_Agent\Documentos de empresa participante\sertei\Acta Constitutiva.pdf"
    result = await agent.extract(file_path)
    
    if result.get("success"):
        print("EXTRACTION SUCCESSFUL")
        print(result.get("extracted_text"))
    else:
        print("EXTRACTION FAILED")
        print(result.get("error"))

if __name__ == "__main__":
    asyncio.run(main())
