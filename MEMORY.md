# Registro de Conocimiento Persistente (Memory)

## 1) Manejo del Agente Económico
- **Problema histórico:** Fallas silenciosas al extraer datos tabulares de Excels complejos.
- **Decisión vigente:** Primero ingestión tabular estructurada; después fallback controlado en texto/anexos para faltantes.
- **Regla:** No volver a extracción plana de texto desde Excel como estrategia principal.

## 2) Sincronización del Orquestador (motivos de corte)
- **Caso A - `INVALID_MODE`:** Entrada con `mode` no soportado desde cliente/integración. Debe fallar rápido y retornar razón explícita.
- **Caso B - `COMPLIANCE_GATE_BLOCKING`:** La etapa de compliance no cumple mínimos de continuidad (por ejemplo, salida inválida/vacía según gate). Debe cortar el pipeline de forma segura.
- **Regla:** Consumidores UI/API deben interpretar `stop_reason` para mostrar estado correcto y acción recomendada.

## 3) Dependencias de testing
- **Incidente histórico:** Incompatibilidades entre stack de pruebas web y versiones antiguas de `httpx`.
- **Decisión vigente:** Mantener versión de `httpx` compatible con el stack FastAPI/Starlette del repositorio.
- **Regla:** Al actualizar dependencias de test, ejecutar smoke de API y tests focalizados de orquestador/chatbot.
