# 🔍 Tunning de Agente DataGap - LicitAI

Este documento es el **Manual de Completitud y Sanidad** para la operación y replicación del Agente de Detección de Brechas de Información (Agente 3). Define el estándar de "Validación de Calidad" necesario para alimentar los formatos oficiales.

---

## 🧠 1. Estrategia de los Dos Canales (A y B)

El Agente de DataGap no es solo un preguntador; es un **Sanador de Perfiles**. Opera mediante un flujo de doble verificación:

1.  **Canal A (Descubrimiento RAG):** Al detectar un campo vacío o con basura, el agente busca en orden: (a) vectores **`company_{id}`** tras `/companies/{id}/analyze`; (b) PDFs de **Fuentes de Verdad** de la sesión **excluyendo** archivos cuyo nombre sugiere bases/convocatoria/pliego (`convocatoria`, `bases`, `pliego`, `licitación`, `requisitos`, etc.), para no tomar correos o teléfonos del convocante. Luego intenta auto-completar sin molestar al usuario.
2.  **Canal B (Feedback Chatbot):** Solo si el Canal A falla después de una búsqueda exhaustiva, el agente genera un mensaje conversacional amigable solicitando el dato específico.

---

## 🛡️ 2. El "Cerebro de Sanidad" (Data Sanity Brain)

Para igualar la inteligencia humana, el agente no acepta campos simplemente por no estar vacíos. Se implementaron las siguientes **Reglas de Juicio**:

*   **Identificación (INE/RFC):** Rechaza cualquier dato de menos de 8 caracteres (evitando errores como "22" o "N/A").
*   **Email Antidatos-de-Prueba:** Bloquea correos sospechosos o de ejemplos comunes (ej: denuncas@sat).
*   **Sitio Web Real:** Invalida URLs incompletas como "http" o "https://", forzando una URL funcional para el membrete corporativo.
*   **Longitud Quirúrgica:** Cualquier dato que no cumpla con la longitud mínima esperada para su tipo es marcado como **GAP**.

---

## 🖥️ 3. Optimización de Búsqueda Secuencial (8GB VRAM)

*   **Multi-Query Interno:** Para cada "GAP", el agente lanza consultas vectoriales específicas (ej: busca "clave elector", "folio", "identificación" por separado para encontrar el INE).
*   **Gestión de Ventana:** Al usar una ventana de **16k tokens**, el agente puede leer el extracto de un contrato antiguo para encontrar un teléfono que no estaba en el perfil maestro.
*   **Persistencia:** Todo dato "auto-sanado" se guarda automáticamente en PostgreSQL para que los Agentes Generadores (Technical Writer, Formats) lo vean inmediatamente.

---

## 📜 4. El Faro de la Calidad de Datos

Para replicar este éxito en cualquier otra app:
1.  **Duda de la Entrada:** Nunca asumas que lo que el usuario escribió (o lo que quedó de una prueba anterior) es verídico.
2.  **Validadores por Tipo:** El correo debe tener @, el teléfono debe tener dígitos, el INE debe ser alfanumérico largo.
3.  **Proactividad Humana:** Si el dato falta, no solo digas "Falta X". Explica **POR QUÉ** lo necesitas (ej: "Para las firmas obligatorias...") y **DÓNDE** puede encontrarlo el usuario (ej: "Sugerencia: INE o Comprobante").

---
*Manual de Ingeniería de Datos - LicitAI 2024*
