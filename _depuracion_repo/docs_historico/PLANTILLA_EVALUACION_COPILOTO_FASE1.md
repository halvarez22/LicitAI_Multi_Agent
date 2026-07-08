# Plantilla de Evaluacion Copiloto (Fase 1)

Objetivo: validar en campo si la nueva "voz de copiloto" reduce confusion y acelera captura de datos.

Uso: una hoja por sesion de prueba (10-15 min).

---

## 1) Datos de la prueba

- Fecha:
- Persona que prueba:
- Sesion/licitation_id:
- Empresa seleccionada:
- Version app visible:
- Backend URL: `http://127.0.0.1:8001/api/v1`
- Frontend URL: `http://127.0.0.1:8504`

---

## 2) Checklist previo (Go / No-Go)

Marca SI/NO:

- [ ] Ollama activo en host.
- [ ] Frontend abre y carga sesion.
- [ ] Empresa seleccionada en UI.
- [ ] Bases indexadas/analizadas.
- [ ] Health backend = 200.
- [ ] Chat visible y funcional.

Si algun punto es NO, no evaluar UX todavia; corregir entorno primero.

---

## 3) Escenarios de prueba (obligatorios)

## Escenario A: Captura economica simple (numero)

Pasos:
1. Pulsar "Generar propuesta" hasta que pida dato economico.
2. Responder con un numero simple (ej. `12500`).
3. Verificar confirmacion y paso al siguiente.

Registro:
- Mensaje pedido fue claro al primer intento: [ ] SI [ ] NO
- El usuario entendio que formato usar (solo numero): [ ] SI [ ] NO
- Confirmacion de guardado fue clara: [ ] SI [ ] NO
- Tiempo (seg) desde pregunta hasta guardado:
- Observaciones:

## Escenario B: Dato no aplicable (0)

Pasos:
1. En siguiente pendiente economico responder `0`.
2. Validar que el agente acepte y avance sin friccion.

Registro:
- El mensaje explicaba que `0` era valido: [ ] SI [ ] NO
- Se guardo sin ambiguedad: [ ] SI [ ] NO
- Avanzo al siguiente dato: [ ] SI [ ] NO
- Observaciones:

## Escenario C: Bloqueo HITL + consulta de pliego explicita

Pasos:
1. Con pendientes activos, preguntar: "Que dicen las bases sobre el IVA?"
2. Verificar que no se rompa flujo y que la respuesta sea util.

Registro:
- El bloqueo fue comprensible (sin jerga tecnica): [ ] SI [ ] NO
- La whitelist permitio consulta de pliego cuando correspondia: [ ] SI [ ] NO
- El usuario supo que hacer despues de leer la respuesta: [ ] SI [ ] NO
- Observaciones:

---

## 4) Metricas rapidas (llenar al final)

1. Tiempo a primera respuesta util (seg):
2. Mensajes necesarios para completar 1 dato:
3. Veces que el usuario pregunto "que me estas pidiendo?":
4. Repeticion visible de mensajes (duplicados): [ ] SI [ ] NO
5. Abandono de chat durante captura: [ ] SI [ ] NO
6. Datos capturados correctamente en primer intento:

---

## 5) Criterios de exito de Fase 1

Se considera exitoso si se cumplen 4 o mas:

- [ ] El usuario no se pierde en el primer pedido economico.
- [ ] Entiende formato de respuesta en <= 1 lectura.
- [ ] No aparecen terminos tecnicos crudos (`blocking_issues`, `price_missing`, etc.).
- [ ] No hay duplicacion molesta del mismo mensaje.
- [ ] Completa al menos 2 datos seguidos sin pedir aclaracion.
- [ ] La interaccion se percibe "guia paso a paso" y no "reporte de error".

---

## 6) Hallazgos cualitativos (texto libre)

### Lo que funciono bien

-
-
-

### Lo que confundio al usuario

-
-
-

### Frases exactas que causaron friccion (copiar/pegar)

-
-
-

---

## 7) Decision de salida

- [ ] APROBADO para seguir con este flujo en demos.
- [ ] APROBADO con ajustes menores de copy.
- [ ] NO APROBADO (revisar flujo antes de nueva demo).

Acciones propuestas:

1.
2.
3.

