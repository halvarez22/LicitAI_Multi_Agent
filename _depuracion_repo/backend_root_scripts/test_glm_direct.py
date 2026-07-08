"""
Test directo de glm-ocr con la CLI de Ollama vía subprocess.
El modelo usa un RENDERER y PARSER custom que solo funciona bien con la CLI.
"""
import subprocess
import tempfile
import os
from pdf2image import convert_from_path

PDF_PATH = "/data/uploads/7d400ae0-7ca7-446e-ab19-c95c2335e685_bases_licitacion_opm-001-2026.pdf"

# Convertir solo página 1 para la prueba
print("[*] Convirtiendo página 1 a imagen...")
images = convert_from_path(PDF_PATH, dpi=200, first_page=1, last_page=1, fmt="jpeg")
img = images[0]

# Guardar imagen temporal
with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
    img.save(f, format="JPEG")
    img_path = f.name

print(f"[*] Imagen guardada en: {img_path}")
print("[*] Llamando a glm-ocr via Ollama CLI...")

# Llamada CLI directa: este es el formato que glm-ocr fue diseñado para recibir
result = subprocess.run(
    ["ollama", "run", "glm-ocr", f"Text Recognition: {img_path}"],
    capture_output=True,
    text=True,
    timeout=120,
    encoding="utf-8"
)

print(f"[*] Return code: {result.returncode}")
print(f"[*] Stderr: {result.stderr[:300] if result.stderr else 'None'}")
print(f"\n✅ TEXTO EXTRAÍDO ({len(result.stdout)} chars):")
print("-" * 60)
print(result.stdout[:3000])
print("-" * 60)

os.unlink(img_path)
