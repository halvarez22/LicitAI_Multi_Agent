# Economic Pipeline Implementation Plan

## Fase 1: Dotar de Herramientas al ChatbotRAGAgent (La Solución a la Amnesia)
- [ ] Modificar `ChatbotRAGAgent` o `intake_planner.py` para incluir una directiva estructurada de extracción de precios.
- [ ] Crear un mecanismo en `Orchestrator` o en el propio Chatbot que, al detectar datos económicos, inyecte un diccionario estructurado en `session["state_data"]["economic_parameters"]`.
- [ ] Validar con un caso de prueba local ("Guardar precio de Zona 1 a $150").

## Fase 2: Refactorización del EconomicAgent (El Validador)
- [ ] Limpiar `EconomicAgent` para que deje de depender del texto de la conversación y en su lugar exija que `economic_parameters` esté poblado.
- [ ] Asegurar que el RAG del `EconomicAgent` filtre correctamente restricciones presupuestales y salariales.
- [ ] Implementar la función de cálculo de IVA e impuestos básicos.
- [ ] Ajustar las transiciones de estado (`ECONOMIC_VALIDATED` o `ECONOMIC_ERROR`) para que el frontend reaccione.

## Fase 3: Conexión del EconomicWriterAgent (El Renderizador)
- [ ] Programar al `EconomicWriterAgent` para que consuma los datos validados y el contexto RAG.
- [ ] Implementar prompt estricto Anti-Alucinación: Solo usar los números presentes en la memoria MCP.
- [ ] Formatear salida en tabla Markdown, detallando Precio Unitario, Subtotal, IVA y Total.

## Fase 4: Pruebas End-to-End
- [ ] Simular el flujo completo para la Licitación de Limpieza (ISAPEG / IMSS).
- [ ] Proveer precios, verificar que no haya bucles infinitos y revisar el anexo final.
