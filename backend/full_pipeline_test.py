import os
import requests
import json
import time

API_URL = "http://localhost:8001/api/v1"
BASES_FILE = r"C:\LicitAI_Multi_Agent\bases y convocatorias de prueba\T5 BASES DD-PM-ILUM-2019-SUM CAMBIO ILUMINACION.pdf"
COTIZACION_FILE = r"C:\LicitAI_Multi_Agent\cotizaciones\CALCULO COSTO ISSSTE VIGILANCIA 2024.xlsx"
SESSION_ID = "final_battle_v5"

def upload_and_process(file_path):
    filename = os.path.basename(file_path)
    print(f"\n[*] Subiendo: {filename}")
    
    # Upload
    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {"session_id": SESSION_ID}
        res = requests.post(f"{API_URL}/upload/document", files=files, data=data)
        doc_id = res.json().get("data", {}).get("doc_id")
    
    # Process
    print(f"[*] Procesando: {filename} (doc_id: {doc_id})...")
    res = requests.post(f"{API_URL}/upload/process/{doc_id}", data={"session_id": SESSION_ID})
    print(f"[OK] {filename} listo.")
    return doc_id

def main():
    print(f"=== INICIANDO PRUEBA MAESTRA MULTI-AGENTE (Session: {SESSION_ID}) ===")
    
    # 1. Preparar Documentos
    upload_and_process(BASES_FILE)
    upload_and_process(COTIZACION_FILE)
    
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
        
        # El campo 'data' ahora tiene los resultados de los agentes
        data_results = result.get("data", {})

        # Analista
        analysis = data_results.get("analysis", {})
        print("\n--- AGENTE 1: ANALISTA TÉCNICO ---")
        print(json.dumps(analysis, indent=2, ensure_ascii=False)[:3000])
        
        # Económico
        economic = data_results.get("economic", {})
        print("\n--- AGENTE 2: AUDITOR ECONÓMICO ---")
        # El económico tiene sumario y data
        e_data = economic.get("data", {})
        print(json.dumps(e_data, indent=2, ensure_ascii=False)[:3000])
        
        summary = economic.get("summary", {})
        if summary:
            print(f"\n[SUMMARY ECONOMIC]")
            print(f"Estado: {summary.get('estado')}")
            print(f"Veredicto: {summary.get('veredicto')}")
            print(f"Partidas Detectadas: {summary.get('total_partidas')}")
        
        print("\n[VEREDICTO FINAL] Proceso de Orquestación MAS concluido exitosamente.")
    else:
        print(f"Error en orquestación ({res.status_code}): {res.text}")

if __name__ == "__main__":
    main()
