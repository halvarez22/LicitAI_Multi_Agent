# Estado Actual (NOW)

## Sprint Actual: Cierre V1.0 (E2E + UAT)
- **Objetivo principal:** Ejecutar y validar una prueba End-to-End real desde la web con insumos representativos de licitación.
- **Foco operativo:** UX de recuperación ante error (timeouts/fallas de red) y continuidad completa del flujo de generación.

## Estado de módulos (Semáforo)
- 🟢 **Agente de Cumplimiento:** Estabilizado y con gate activo.
- 🟢 **Agente Económico:** Estabilizado (ingesta tabular + fallback controlado).
- 🟢 **Frontend (dashboards clave):** Flujo principal funcional.
- 🟡 **Infraestructura Docker:** Pendiente validación bajo carga/estrés.

## Prohibiciones actuales
- No refactorizar lógica central de extracción/orquestación salvo falla crítica reproducible.
- No introducir cambios de alcance mayor durante ventana de validación E2E.

## Criterio de avance
- Completar E2E con evidencia (logs + artefactos) y cerrar incidencias bloqueantes antes de ampliar alcance.
