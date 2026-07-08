import os
import requests
import json
import time

API_URL = "http://localhost:8001/api/v1"
# Rutas relativas para que funcione dentro del contenedor Docker
BASES_FILE = "/data/uploads/T1_Bases_Provisional.pdf" # Mock o ruta real montada
COTIZACION_FILE = "/data/uploads/T2_Cotizacion_Provisional.xlsx"
SESSION_ID = "final_battle_v6"

def main():
    print(f"=== INICIANDO PRUEBA MAESTRA MULTI-AGENTE (Session: {SESSION_ID}) ===")
    
    # 2. Ejecutar Orquestador
    print("\n[ORQUESTADOR] Iniciando Pipeline MAS...")
    start_time = time.time()
    res = requests.post(f"{API_URL}/agents/process", json={
        "session_id": SESSION_ID,
        "company_id": "test_company_01",
        "company_data": {"mode": "analysis_only"}
    })
    
    if res.status_code == 200:
        result = res.json()
        duration = time.time() - start_time
        print(f"\n=== RESULTADOS RECUPERADOS (Tiempo: {duration:.2f}s) ===")
        
        data_results = result.get("data", {})

        # Analista
        analysis = data_results.get("analysis", {})
        print("\n--- AGENTE 1: ANALISTA TÉCNICO ---")
        print(json.dumps(analysis, indent=2, ensure_ascii=False))
        
        # Económico
        economic = data_results.get("economic", {})
        print("\n--- AGENTE 2: AUDITOR ECONÓMICO ---")
        print(json.dumps(economic.get("data", {}), indent=2, ensure_ascii=False))
        
        summary = economic.get("summary", {})
        if summary:
            print(f"\n[SUMMARY ECONOMIC]")
            print(f"Estado: {summary.get('estado')}")
            print(f"Veredicto: {summary.get('veredicto')}")
            print(f"Items: {summary.get('total_partidas')}")
        
        print("\n[VEREDICTO FINAL] Proceso de Orquestación MAS concluido exitosamente.")
    else:
        print(f"Error en orquestación ({res.status_code}): {res.text}")

if __name__ == "__main__":
    main()
