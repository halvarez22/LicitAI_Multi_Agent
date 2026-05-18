from pypdf import PdfReader
import sys

pdf_path = r"C:\LicitAI_Multi_Agent\Documentos de empresa participante\sertei\Acta Constitutiva.pdf"

try:
    reader = PdfReader(pdf_path)
    text = ""
    for i in range(len(reader.pages)):
        text += f"\n--- PAGE {i+1} ---\n"
        text += reader.pages[i].extract_text()
    
    print(text)
except Exception as e:
    print(f"Error reading PDF: {e}")
