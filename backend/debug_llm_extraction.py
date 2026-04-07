import asyncio
import json
from app.services.llm_service import LLMServiceClient

MARKDOWN_TABLE = """
### ARCHIVO: CALCULO COSTO ISSSTE VIGILANCIA 2024.xlsx | HOJA: Hoja2
CONTENIDO TABULAR:
| DESGLOSE DE PRECIO MENSUAL POR ELEMENTO | Unnamed: 2 | Unnamed: 3 | Unnamed: 4 |
|:------------------------------------------|:-----------|:-----------|:-----------|
| PERSONAL OPERADOR | nan | nan | nan |
| Sueldo base | 11474.48 | 1 | 11474.48 |
| Vacaciones | % | 1 | 235.0848 |
| Prima Vacacional | % | 1 | 58.7712 |
| Aguinaldo | % | 1 | 471.5512 |
| Guarderías | % | 1 | 2883.5594757999997 |
| T O T A L | nan | nan | 15123.4466758 |
"""

async def test():
    llm = LLMServiceClient()
    phase_key = "cotizaciones"
    
    system_prompt = (
        "Eres un Ingeniero de Costos Senior especializado en licitaciones públicas. "
        "Tu objetivo es extraer datos financieros precisos de documentos (PDF o Excel). "
        "REGLAS CRÍTICAS:\n"
        "1. Si ves valores 'nan', 'Unnamed' o celdas vacías, IGNÓRALOS. No los incluyas en el JSON.\n"
        "2. Prioriza PRECIOS UNITARIOS, CANTIDADES, IMPORTES TOTALES y NÚMEROS DE PARTIDA.\n"
        "3. Si el documento es una tabla (Markdown), identifica las cabeceras correctamente.\n"
        "4. Responde ÚNICAMENTE con el objeto JSON solicitado."
    )
    
    user_prompt = (
        f"Extrae la información de '{phase_key}' en formato JSON estructurado.\n\n"
        f"CONTEXTO RECUPERADO:\n{MARKDOWN_TABLE}\n\n"
        "INSTRUCCIÓN ESTRUCTURADA:\n"
        f"- Para 'catálogo' o 'cotizaciones', devuelve una lista de objetos con: partida, descripcion, cantidad, unidad, precio_unitario, importe.\n"
        "Solo JSON."
    )
    
    print("Enviando a LLM...")
    res = await llm.generate(prompt=user_prompt, system_prompt=system_prompt)
    print("RESULTADO LLM:")
    print(res.get("response"))

if __name__ == "__main__":
    asyncio.run(test())
