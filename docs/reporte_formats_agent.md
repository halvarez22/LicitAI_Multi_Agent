# Reporte Detallado: Refactorización FormatsAgent

**Archivo principal:** `backend/app/agents/formats.py`  
**Tests:** `backend/tests/test_formats_agent_behavior.py`  
**Fecha:** 2026-03-28

---

## Contexto y Motivación

El `FormatsAgent` es el agente de **Fase 2** responsable de generar un DOCX por cada requisito administrativo o de formato detectado por el `ComplianceAgent`. Sus documentos van al **Sobre 1 (Administrativo)** del expediente final que empaqueta el `DocumentPackagerAgent`.

Se identificaron **5 defectos** en el código original, desde bugs críticos de integración hasta anti-patrones de código, que se detallan a continuación.

---

## Fix 1 — CRÍTICO: Contrato de salida roto con el Orquestador y Packager

### Problema
El orquestador, en la línea ~213, construye el payload para el `DocumentPackagerAgent` así:
```python
input_data["documentos_generados"]["administrativa"] = (
    execution_results.get("formats", {}).get("data", {}).get("documentos", [])
)
```
Es decir, el orquestador espera que `FormatsAgent` devuelva `data.documentos`.  
Sin embargo, `FormatsAgent` devolvía:
```python
return {"status": "success", "files": generated_files, "count": len(generated_files)}
```
**Resultado:** `data.documentos` era siempre `None → []`. El Sobre 1 Administrativo llegaba vacío al Packager en **100% de los casos**, independientemente de cuántos documentos hubieran sido generados.

### Fix Aplicado
```python
# ANTES
return {
    "status": "success",
    "files": generated_files,
    "count": len(generated_files)
}

# DESPUÉS
result_data = {
    "documentos": generated_files,
    "count": len(generated_files),
    "folder": output_dir
}
await self.context_manager.record_task_completion(
    session_id, "formats_generation_COMPLETED", result_data
)
return {"status": "success", "data": result_data}
```

---

## Fix 2 — Anti-patrón: LLM instanciado dentro de `process()`

### Problema
```python
async def process(self, session_id, input_data):
    from app.services.llm_service import LLMServiceClient  # ← importación lazy
    llm = LLMServiceClient()  # ← nueva instancia en cada invocación
```
Esto impedía hacer `patch.object(agent, "llm")` en tests, forzando mocks complicados o pruebas que realmente llamaban a Ollama.

### Fix Aplicado
```python
def __init__(self, context_manager):
    super().__init__(...)
    # Instanciado en constructor para que sea mockeable en tests unitarios
    self.llm = LLMServiceClient()

async def process(self, session_id, input_data):
    llm = self.llm  # alias local para legibilidad
```
El import de `LLMServiceClient` se elevó al bloque de imports del módulo.

---

## Fix 3 — Fallback de compliance_data ignoraba el path del Orquestador

### Problema
El código original sólo buscaba `compliance_master_list` en `input_data` o en `tasks_completed`:
```python
compliance_data = input_data.get("compliance_master_list", {})
if not compliance_data:
    # buscar en tasks...
```
Sin embargo, cuando el Orquestador invoca a los agentes de Fase 2 tras la Fase 1, los resultados de compliance van en `results.compliance.data` — igual que ya sucedía con `TechnicalWriterAgent`.

### Fix Aplicado
Cadena de resolución con 3 prioridades, documentada con comentarios:
```python
# Orden de prioridad:
# a) Inyección directa del orquestador via compliance_master_list
# b) Resultados de Fase 1 via results.compliance.data
# c) Tarea persistida master_compliance_list en tasks_completed
compliance_data = (
    input_data.get("compliance_master_list")
    or input_data.get("results", {}).get("compliance", {}).get("data")
    or {}
)
if not compliance_data:
    # buscar en tasks...
```

---

## Fix 4 — Filtro de IDs perdía ítems sin prefijo estándar

### Problema
El filtro de `reqs_to_process` era:
```python
if rid.startswith("1_") or any(x in rid.upper() for x in ["AT", "AE", "DECL", "ANEXO"]):
```
Si el `ComplianceAgent` entregaba un ítem con `tipo: "administrativo"` pero un ID que no empezara por `"1_"` ni contuviera las palabras clave (e.g. `"admin_003"`, `"req_0042"`), el ítem se ignoraba silenciosamente y **no se generaba el documento**.

### Fix Aplicado
```python
is_admin = (
    rid.startswith("1_")
    or any(x in rid.upper() for x in ["AT", "AE", "DECL", "ANEXO"])
    or req.get("tipo", "").lower() in ("administrativo", "formato", "formatos")
)
if is_admin:
    reqs_to_process.append(req)
```
Ahora cualquier ítem con `tipo` explícitamente administrativo o formato se captura aunque su ID no siga la convención de prefijo.

---

## Fix 5 — Error LLM grabado como contenido válido

### Problema
```python
content = resp.get("response", "Error en generación.")
```
Si el LLM caía (Ollama timeout, red) y devolvía `{"error": "..."}`, `resp.get("response")` retornaba `None` → se usaba el fallback literal `"Error en generación."` como texto del documento. El DOCX se creaba con ese string en el cuerpo — ningún error se registraba, el archivo parecía válido.

### Fix Aplicado
```python
if "error" in resp:
    print(f"[FormatsAgent] ⚠️ LLM error en '{raw_name}': {resp['error']}")
    continue   # ← salta este ítem, no crea el archivo
content = resp.get("response", "")
if not content.strip():
    print(f"[FormatsAgent] ⚠️ Respuesta vacía del LLM para '{raw_name}'.")
    continue   # ← respuesta vacía, también se salta
```

---

## Fix 6 — Sin persistencia en `tasks_completed`

### Problema
`TechnicalWriterAgent` persiste sus resultados con `record_task_completion`, permitiendo que un futuro `generation_only` o el `DocumentPackagerAgent` los recuperen de la sesión. `FormatsAgent` no lo hacía, por lo que en modo `generation_only` no quedaba huella de los documentos administrativos generados.

### Fix Aplicado
```python
await self.context_manager.record_task_completion(
    session_id, "formats_generation_COMPLETED", result_data
)
```
Añadido justo antes del `return`, guardando `documentos`, `count` y `folder` en el historial de tareas de sesión.

---

## Fix 7 — Bug heredado en `_save_docx`: `domicilio_fiscal`

### Problema
La función `_save_docx` tenía:
```python
lugar = metadata.get("domicilio_fiscal", "México").split(",")[0]
```
Pero `doc_metadata` **no contiene** la clave `"domicilio_fiscal"` — contiene `"footer_text"` con el formato `"Empresa | RFC: xxx | Domicilio: Calle 123, Ciudad"`. El resultado era siempre `lugar = "México"` de manera silenciosa.

### Fix Aplicado  
(Idéntico al aplicado en `TechnicalWriterAgent`):
```python
footer_text = metadata.get("footer_text", "") if metadata else ""
lugar = (
    footer_text.split("Domicilio:")[-1].split(",")[0].strip()
    if "Domicilio:" in footer_text
    else "México"
)
```
Extrae la ciudad real del domicilio si está disponible en el footer.

---

## Tests — De 3 a 5 casos (+ 2 nuevos)

| Test | Qué valida |
|---|---|
| `test_sin_formatos_devuelve_success_vacio` | Lista vacía → `data.count == 0`, LLM no invocado |
| `test_con_formatos_llm_invocado_y_success` | Ítem `"1.1"` → 1 llamada LLM, `data.documentos` tiene 1 ítem |
| `test_fallback_compliance_desde_results_orquestador` | Sin `compliance_master_list`, lee `results.compliance.data` |
| **`test_llm_error_no_genera_archivo_y_sigue`** *(nuevo)* | LLM devuelve `{"error": "..."}` → `_save_docx` NO llamado, `count == 0` |
| **`test_item_sin_prefijo_pero_tipo_administrativo_se_incluye`** *(nuevo)* | ID `"admin_003"` sin prefijo `1_` pero `tipo="administrativo"` → se genera |

---

## Estado Final de la Suite

```
pytest tests/ → 28 passed in ~19s  (Exit code: 0)

Distribución:
  6  test_compliance_llm_telemetry
  6  test_economic_agent_behavior
  6  test_orchestrator_behavior
  2  test_economic_writer_behavior
  3  test_technical_writer_behavior
  5  test_formats_agent_behavior
  ──
  28 TOTAL
```

> **Nota operativa:** Para que estos cambios sean visibles en el E2E contra `localhost:8001`, reiniciar el proceso Uvicorn/contenedor Docker que sirve la API.
