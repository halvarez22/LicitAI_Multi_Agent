# Contexto del Proyecto: LicitAI (Forensic & Compliance Multi-Agent System)

## 📌 Arquitectura General
LicitAI es un sistema multi-agente para la extracción, análisis y auditoría forense de licitaciones.
- **Backend:** Python con FastAPI (ubicado en `./backend`)
- **Frontend:** React con Vite (ubicado en `./frontend`)
- **Base de Datos:** PostgreSQL para persistencia de datos relacionales y estado de auditorías.
- **RAG & Vectores:** ChromaDB para búsqueda semántica.
- **Inteligencia Artificial:** Orquestación de Agentes con LangChain/LlamaIndex, ejecutando modelos mediante Ollama localmente (ej. qwen2.5-coder, llama3, etc.).
- **Infraestructura:** Todo está contenerizado con Docker (orquestado vía `docker-compose.yml`).

## 🧠 Flujo de Análisis Forense
El sistema sigue un flujo especializado "Pipeline" para analizar licitaciones:
1. **Intake / VisionExtractor:** Extracción de datos de PDFs (escaneados y nativos).
2. **Analyst Agent:** Comprensión de las bases y extracción de requisitos.
3. **Compliance Agent (Forensic):** Auditoría que compara rigurosamente los requisitos con los documentos extraídos para identificar riesgos o faltantes, con mitigación de "Lost in the Middle". Exige extracción literal y formatos de salida JSON estrictos.
4. **Economic Agent:** Evaluación económica.

## 🛠️ Reglas de Código y Desarrollo
- **Backend (Python):** 
  - Usar siempre type hints (`typing`).
  - Escribir `docstrings` en español describiendo entrada/salida y posibles excepciones.
  - La persistencia de auditorías o "Dictámenes Forenses" debe hacerse directamente a PostgreSQL para evitar pérdida de datos del contenedor. Poner atención a la correcta sanitización Pydantic -> SQLAlchemy.
- **Frontend (React):**
  - Los componentes UI deben ceñirse a un formato de "Tarjeta Forense" estricto: (Ubicación, Sección, Texto Literal).
  - Mantener unificado el conteo de requisitos de auditoría a través de todos los componentes.
- **General:**
  - Todas las explicaciones de código y planeación en la conversación se harán en **español**.
  - No usar TailwindCSS a menos que se solicite específicamente, priorizamos Vanilla CSS y componentes estructurados. 
  - Si implementas Prompt Engineering, usa ejemplos con refuerzo positivo y "few-shot learning".

## 🚀 Comandos Útiles y Utilidades
- **Correr entorno local:** `docker-compose up -d --build`
- **Verificar Logs Backend:** `docker-compose logs -f backend`
- **(Si en WSL/Host):** La instancia de Ollama se expone en `http://localhost:11434` o su respectivo endpoint en el `.env`.

> ⚠️ Nota para IA: Revisa el esquema de base de datos o modelos Pydantic en `backend/app` antes de proponer cambios estructurales a la base de datos persistente.
