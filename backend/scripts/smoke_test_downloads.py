import asyncio
import os
import sys
import httpx
import json

# Configuración básica (Ajustar según entorno)
BASE_URL = "http://localhost:8000/api/v1"
TEST_SESSION_ID = "licitacin_pblica_nacional_presencial__40004001-003-24_"

async def smoke_test_downloads():
    """
    Script de Verificación Industrial de Descargas (Anti-Ghost ZIP).
    Certifica que la API sirve archivos reales tras la generación.
    """
    print(f"\n🧪 [LicitAI QA] INICIANDO SMOKE TEST DE DESCARGAS: {TEST_SESSION_ID}\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. LISTAR ARCHIVOS (GET /downloads/list)
        try:
            print(f"📡 [1/2] Consultando lista de archivos para {TEST_SESSION_ID}...")
            list_res = await client.get(f"{BASE_URL}/downloads/list?session_id={TEST_SESSION_ID}")
            
            if list_res.status_code == 200:
                files = list_res.json().get("files", [])
                if any(f.endswith(('.docx', '.pdf', '.xlsx')) for f in files):
                    print(f"   ✅ OK: Se encontraron {len(files)} archivos generados.")
                else:
                    print(f"   ❌ FAIL: La lista de archivos está vacía o no tiene formatos esperados.")
                    return False
            else:
                print(f"   ❌ FAIL: HTTP {list_res.status_code} al listar archivos.")
                return False
        except Exception as e:
            print(f"   ❌ ERROR: Falló conexión a la API de listas: {e}")
            return False

        # 2. DESCARGAR ZIP (GET /downloads/zip)
        try:
            print(f"📡 [2/2] Solicitando empaquetado ZIP para {TEST_SESSION_ID}...")
            # IMPORTANTE: Usamos la URL que el backend espera (con session_id como query param)
            zip_res = await client.get(f"{BASE_URL}/downloads/zip?session_id={TEST_SESSION_ID}")
            
            if zip_res.status_code == 200:
                zip_size = len(zip_res.content)
                if zip_size > 0:
                    print(f"   ✅ OK: ZIP obtenido con éxito ({zip_size / 1024:.2f} KB).")
                else:
                    print(f"   ❌ FAIL: El ZIP está vacío.")
                    return False
            elif zip_res.status_code == 404:
                print(f"   ⚠️  AVISO (404): La carpeta física no existe en /data/outputs. Requiere re-generación.")
                return False
            else:
                print(f"   ❌ FAIL: HTTP {zip_res.status_code} al solicitar el ZIP.")
                return False
        except Exception as e:
            print(f"   ❌ ERROR: Falló conexión a la API de descarga: {e}")
            return False

    print("\n✨ [SMOKE TEST PASADO] El pipeline de entrega industrial es robusto.")
    return True

if __name__ == "__main__":
    asyncio.run(smoke_test_downloads())
