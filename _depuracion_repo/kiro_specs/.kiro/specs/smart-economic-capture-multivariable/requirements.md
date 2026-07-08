# Spec: Smart Economic Capture & Multivariable Intake

## 1. Contexto y Objetivos
El flujo económico de LicitAI presentaba un bloqueo crítico (ECONOMIC_GAP) causado por la incapacidad del ChatbotRAG de procesar lenguaje natural complejo para la entrada de precios.

### Objetivos:
- Eliminar el "Loop del Subtotal" (donde un campo calculado bloquea la captura de sus componentes).
- Migrar de extracción basada en Regex a Extracción Estructurada mediante LLM.
- Habilitar la captura de múltiples precios en una sola frase (Multivariable Intake).

## 2. Escenarios de Usuario
- **Escenario A (Normalización):** El usuario dice "Zona A: 85000" y el sistema mapea "A" al concepto interno "Limpieza en Unidades Médicas (Zona A)".
- **Escenario B (Resiliencia):** El usuario dice "son 85,400 sin iva para la zona a" y el sistema extrae el número limpiamente.
- **Escenario C (Batch):** El usuario entrega todas las zonas (A, B, C, D) de un solo golpe y el sistema las persiste masivamente.

## 3. Restricciones
- No "casar" la lógica con una licitación específica (Universalidad).
- Mantener compatibilidad con el motor de cuadratura financiera (`refresh_economic_validations`).
