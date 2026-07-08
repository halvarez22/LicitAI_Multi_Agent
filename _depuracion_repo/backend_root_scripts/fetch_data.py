import fitz
import re

def main():
    p = "/data/uploads/00165194-7328-4bb5-a235-7f10ce882cf6_bases_servicio_limpieza_2024_issste_bcs.pdf"
    doc = fitz.open(p)
    text = "\n".join([page.get_text() for page in doc])
    
    # 1. Calendario
    print("--- CALENDARIO DE EVENTOS ---")
    months = r"(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)"
    date_regex = rf"\d{{1,2}}\s+DE\s+{months}\s+DE\s+2024"
    matches = re.finditer(date_regex, text.upper())
    for m in matches:
        print(f"Encontrado: {m.group(0)}")

    # 2. Secciones Clave
    keywords = ["JUNTA DE ACLARACIONES", "PRESENTACIÓN", "PROPOSICIONES", "FALLO", "GARANTÍA", "CRITERIOS DE EVALUACIÓN"]
    for kw in keywords:
        pos = text.upper().find(kw)
        if pos != -1:
            print(f"\n--- {kw} ---")
            print(text[pos:pos+500])

    # 3. Requisitos Filtro
    print("\n--- REQUISITOS PARA PARTICIPAR ---")
    pos = text.upper().find("REQUISITOS PARA PARTICIPAR")
    if pos != -1:
        print(text[pos:pos+1500])

if __name__ == "__main__":
    main()
