import requests
import json
import time

url = "http://localhost:8001/api/v1/chatbot/ask"
session_id = "vigilancia_hospital_regional_issste_leon"

headers = {
    "Content-Type": "application/json"
}

# Wait for server to be responsive
print("Comprobando disponibilidad del servidor backend...")
for i in range(15):
    try:
        r = requests.get("http://localhost:8001/api/v1/health", timeout=3)
        if r.status_code == 200:
            print("¡Servidor en línea!")
            break
    except Exception:
        pass
    print("Esperando a que el backend responda en el puerto 8001...")
    time.sleep(2)

q1 = "¿Cuál es la fecha y hora de la Junta de Aclaraciones?"
payload1 = {
    "session_id": session_id,
    "query": q1
}

print(f"\n--- ENVIANDO PREGUNTA 1: {q1} ---")
try:
    r1 = requests.post(url, headers=headers, json=payload1, timeout=60)
    if r1.status_code == 200:
        res = r1.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 1) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r1.status_code}: {r1.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 1: {e}")

q2 = "¿Cuál es la consecuencia si no asiste a la Visita de Instalaciones?"
payload2 = {
    "session_id": session_id,
    "query": q2
}

print(f"\n--- ENVIANDO PREGUNTA 2: {q2} ---")
try:
    r2 = requests.post(url, headers=headers, json=payload2, timeout=60)
    if r2.status_code == 200:
        res = r2.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 2) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r2.status_code}: {r2.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 2: {e}")

q3 = "¿Cuál es el monto mínimo que se debe presentar en la póliza de seguro de responsabilidad civil y cuándo se debe entregar?"
payload3 = {
    "session_id": session_id,
    "query": q3
}

print(f"\n--- ENVIANDO PREGUNTA 3: {q3} ---")
try:
    r3 = requests.post(url, headers=headers, json=payload3, timeout=60)
    if r3.status_code == 200:
        res = r3.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 3) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r3.status_code}: {r3.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 3: {e}")

q4 = "¿Cuántos elementos de vigilancia se solicitan en total para el turno de 24 horas en el área específica de \"Entrada Principal\"?"
payload4 = {
    "session_id": session_id,
    "query": q4
}

print(f"\n--- ENVIANDO PREGUNTA 4: {q4} ---")
try:
    r4 = requests.post(url, headers=headers, json=payload4, timeout=60)
    if r4.status_code == 200:
        res = r4.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 4) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r4.status_code}: {r4.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 4: {e}")

q5 = "Qué acreditaciones o registros especializados de seguridad privada (como el REPSE) se exigen entregar obligatoriamente en el punto 6.1?"
payload5 = {
    "session_id": session_id,
    "query": q5
}

print(f"\n--- ENVIANDO PREGUNTA 5: {q5} ---")
try:
    r5 = requests.post(url, headers=headers, json=payload5, timeout=180)
    if r5.status_code == 200:
        res = r5.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 5) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r5.status_code}: {r5.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 5: {e}")

q6 = "¿Qué moneda y qué formato de precios son de cumplimiento obligatorio para presentar nuestra propuesta económica?"
payload6 = {
    "session_id": session_id,
    "query": q6
}

print(f"\n--- ENVIANDO PREGUNTA 6: {q6} ---")
try:
    r6 = requests.post(url, headers=headers, json=payload6, timeout=180)
    if r6.status_code == 200:
        res = r6.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 6) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r6.status_code}: {r6.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 6: {e}")

q7 = "¿Qué porcentaje de la propuesta económica se debe calcular como Garantía de Cumplimiento del contrato y qué formas de pago acepta la convocante?"
payload7 = {
    "session_id": session_id,
    "query": q7
}

print(f"\n--- ENVIANDO PREGUNTA 7: {q7} ---")
try:
    r7 = requests.post(url, headers=headers, json=payload7, timeout=180)
    if r7.status_code == 200:
        res = r7.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 7) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r7.status_code}: {r7.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 7: {e}")

q8 = "¿Cuáles son las penalizaciones o deducciones específicas contempladas si un elemento de vigilancia falta a su turno asignado?"
payload8 = {
    "session_id": session_id,
    "query": q8
}

print(f"\n--- ENVIANDO PREGUNTA 8: {q8} ---")
try:
    r8 = requests.post(url, headers=headers, json=payload8, timeout=180)
    if r8.status_code == 200:
        res = r8.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 8) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r8.status_code}: {r8.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 8: {e}")

q9 = "¿A cuántos anexos totales hace referencia el pliego de condiciones de esta licitación y qué documento exacto corresponde al Anexo 9?"
payload9 = {
    "session_id": session_id,
    "query": q9
}

print(f"\n--- ENVIANDO PREGUNTA 9: {q9} ---")
try:
    r9 = requests.post(url, headers=headers, json=payload9, timeout=180)
    if r9.status_code == 200:
        res = r9.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 9) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r9.status_code}: {r9.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 9: {e}")

q10 = "¿Existe un presupuesto mínimo o máximo establecido por el ISSSTE para esta partida que determine el techo de nuestra propuesta económica?"
payload10 = {
    "session_id": session_id,
    "query": q10
}

print(f"\n--- ENVIANDO PREGUNTA 10: {q10} ---")
try:
    r10 = requests.post(url, headers=headers, json=payload10, timeout=180)
    if r10.status_code == 200:
        res = r10.json()
        print("\n=== RESPUESTA DEL BOT (PREGUNTA 10) ===")
        print(res.get("reply"))
        print("\nCitas:")
        citations = res.get("citations") or []
        for cit in citations:
            if cit:
                print(f"- [Pág {cit.get('pagina')}]: {cit.get('documento')}")
    else:
        print(f"Error {r10.status_code}: {r10.text}")
except Exception as e:
    print(f"Excepción al procesar Pregunta 10: {e}")
