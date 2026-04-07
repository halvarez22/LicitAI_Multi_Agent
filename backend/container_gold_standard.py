import requests
import base64
from pdf2image import convert_from_path
import io
import os

# inside container mapping
pdf_path = "/C:/LicitAI_Multi_Agent/bases y convocatorias de prueba/Bases licitacion OPM-001-2026.pdf"
pages_to_extract = [2, 4, 11, 15]

for p_num in pages_to_extract:
    try:
        images = convert_from_path(pdf_path, first_page=p_num, last_page=p_num, dpi=130)
        img = images[0]
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        
        # Use host Ollama (host.docker.internal)
        res = requests.post("http://host.docker.internal:11434/api/generate", json={
            "model": "llama3.2-vision:11b",
            "prompt": "Extract the literal technical and administrative requirements from this page correctly. Focus on identifying specific articles or numbered sections.",
            "images": [b64],
            "stream": False
        })
        text = res.json().get("response", "")
        print(f"\n[GOLD STANDARD PAGE {p_num}]")
        print(text)
        print("-" * 50)
    except Exception as e:
        print(f"Error extracting page {p_num}: {e}")
