import asyncio
import os
import sys

# La carpeta /app ya está en el path en el contenedor
from app.agents.extractor_vision import VisionExtractorAgent

async def search_rep_legal():
    agent = VisionExtractorAgent(ollama_url="http://host.docker.internal:11434")
    os.environ["VISION_MAX_PAGES"] = "8"
    
    file_path = "/app/acta_to_analyze.pdf"
    result = await agent.extract(file_path)
    
    if not result.get("success"):
        print("FAILED OCR")
        return

    text = result.get("extracted_text", "")
    keywords = ["ADMINISTRADOR", "REPRESENTANTE", "PODER", "PRESIDENTE", "TRANSITORIA", "NOMBRAMIENTO"]
    
    found = False
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if any(key in line.upper() for key in keywords):
            print(f"L{i}: {line}")
            # Mostrar contexto
            for j in range(max(0, i-2), min(len(lines), i+5)):
                if j != i:
                    print(f"  [{j}] {lines[j]}")
            print("-" * 20)
            found = True
            
    if not found:
        print("No keywords found in OCR text.")

if __name__ == "__main__":
    asyncio.run(search_rep_legal())
