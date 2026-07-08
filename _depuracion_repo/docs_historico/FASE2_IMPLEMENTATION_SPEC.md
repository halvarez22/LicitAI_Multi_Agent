# Especificación de Implementación: Fase 2 - Generación Completa de Documentos

> **Documento técnico para desarrollo asistido por IA**
> **Versión:** 1.0
> **Fecha:** 2026-03-26
> **Proyecto:** LicitAI - Forensic & Compliance Multi-Agent System

---

## 1. CONTEXTO DEL PROYECTO

### 1.1 Arquitectura Actual
LicitAI es un sistema multi-agente para auditoría forense de licitaciones ubicado en `C:\LicitAI_Multi_Agent\licitaciones-ai`.

**Stack tecnológico:**
- Backend: Python 3.10+ con FastAPI (`backend/app/`)
- Frontend: React + Vite (`frontend/src/`)
- Base de datos: PostgreSQL
- Vectores: ChromaDB
- LLM: Ollama (modelos locales: llama3.1:8b, qwen2.5-coder)
- Contenedores: Docker Compose

**Estructura de agentes:**
```
backend/app/agents/
├── base_agent.py          # Clase abstracta BaseAgent
├── orchestrator.py        # Coordinador de flujo
├── analyst.py             # Análisis de bases
├── compliance.py          # Auditoría forense
├── economic.py            # Evaluación económica (solo alertas)
├── data_gap.py            # Detección de datos faltantes
├── technical_writer.py    # Genera propuesta técnica
└── formats.py             # Genera documentos administrativos
```

### 1.2 Flujo Actual (Incompleto)
```
FASE 1: ANÁLISIS (✅ Completo)
├── AnalystAgent      → Extrae requisitos de bases
├── ComplianceAgent   → Auditoría forense con snippets literales
└── EconomicAgent     → Solo genera alertas de precios

FASE 2: GENERACIÓN (⚠️ Incompleto)
├── DataGapAgent      → ✅ Detecta datos faltantes
├── TechnicalWriterAgent → ✅ Genera propuesta técnica
├── FormatsAgent      → ✅ Genera docs administrativos
├── [FALTA] EconomicWriterAgent → ❌ Generar propuesta económica
├── [FALTA] DocumentPackagerAgent → ❌ Organizar en sobres
└── [FALTA] DeliveryAgent → ❌ Instrucciones de entrega
```

---

## 2. AGENTES A IMPLEMENTAR

### 2.1 EconomicWriterAgent (NUEVO)

**Ubicación:** `backend/app/agents/economic_writer.py`

**Responsabilidad:**
Generar la Propuesta Económica formal basada en el catálogo de precios de la empresa y los requisitos de la licitación.

**Input esperado:**
```python
{
    "session_id": "licitacion_abc_123",
    "company_id": "empresa_xyz",
    "company_data": {
        "master_profile": {...},
        "catalogo_precios": [...],  # Lista de productos/servicios con precios
        "docs": {...}
    },
    "compliance_master_list": {
        "tecnico": [...],
        "administrativo": [...],
        "formatos": [...]
    }
}
```

**Output esperado:**
```python
{
    "status": "success",
    "data": {
        "folder": "/data/outputs/{session_name}/2.propuesta_economica/",
        "documentos": [
            {
                "nombre": "Propuesta Económica - Anexo AE",
                "ruta": "/data/outputs/.../ANEXO_AE_PROPUESTA_ECONOMICA.docx",
                "tipo": "anexo_economico",
                "status": "FINAL"
            },
            {
                "nombre": "Tabla de Precios Unitarios",
                "ruta": "/data/outputs/.../TABLA_PRECIOS_UNITARIOS.xlsx",
                "tipo": "tabla_precios",
                "status": "FINAL"
            },
            {
                "nombre": "Carta de Compromiso de Precios",
                "ruta": "/data/outputs/.../CARTA_COMPROMISO_PRECIOS.docx",
                "tipo": "carta_compromiso",
                "status": "FINAL"
            }
        ],
        "resumen_economico": {
            "subtotal": 150000.00,
            "iva": 24000.00,
            "total": 174000.00,
            "moneda": "MXN",
            "vigencia_dias": 30
        }
    }
}
```

**Lógica de implementación:**

```python
class EconomicWriterAgent(BaseAgent):
    """
    Agente: Generador de Propuesta Económica.
    Genera documentos económicos formales basados en catálogo de empresa.
    """

    async def process(self, session_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Recuperar catálogo de precios de la empresa
        company_data = input_data.get("company_data", {})
        catalogo = company_data.get("catalogo_precios", [])

        # 2. Buscar en RAG los conceptos/partidas requeridas
        conceptos_query = await self.smart_search(
            session_id,
            "partidas conceptos precios unitarios cantidad unidad medida especificaciones",
            n_results=10
        )

        # 3. Usar LLM para estructurar la propuesta económica
        # - Extraer conceptos del texto de bases
        # - Match con catálogo de empresa
        # - Calcular totales

        # 4. Generar documentos:
        # 4.1 Tabla de Precios (Excel con openpyxl)
        # 4.2 Anexo AE (Word con python-docx)
        # 4.3 Carta de Compromiso (Word)

        # 5. Retornar rutas y resumen
```

**Formato de Tabla de Precios (Excel):**
| Partida | Descripción | Unidad | Cantidad | Precio Unit. | Importe |
|---------|-------------|--------|----------|--------------|---------|
| 1 | Suministro de... | Pieza | 100 | $150.00 | $15,000.00 |

**Dependencies a agregar en requirements.txt:**
```
openpyxl>=3.1.0
```

---

### 2.2 DocumentPackagerAgent (NUEVO)

**Ubicación:** `backend/app/agents/document_packager.py`

**Responsabilidad:**
Organizar TODOS los documentos generados en la estructura de sobres según el tipo de licitación (electrónica o presencial).

**Input esperado:**
```python
{
    "session_id": "licitacion_abc_123",
    "documentos_generados": {
        "tecnica": [...],      # Output de TechnicalWriterAgent
        "administrativa": [...], # Output de FormatsAgent
        "economica": [...]     # Output de EconomicWriterAgent
    }
}
```

**Output esperado:**
```python
{
    "status": "success",
    "data": {
        "estructura_sobres": {
            "sobre_1_administrativo": {
                "nombre": "SOBRE No. 1 - DOCUMENTACIÓN ADMINISTRATIVA",
                "carpeta": "/data/outputs/{session}/SOBRE_1_ADMINISTRATIVO/",
                "documentos": [
                    {"orden": 1, "nombre": "Propuesta Administrativa", "archivo": "..."},
                    {"orden": 2, "nombre": "Acta Constitutiva", "archivo": "..."},
                    # ...
                ],
                "total_documentos": 15
            },
            "sobre_2_tecnico": {
                "nombre": "SOBRE No. 2 - PROPUESTA TÉCNICA",
                "carpeta": "/data/outputs/{session}/SOBRE_2_TECNICO/",
                "documentos": [...],
                "total_documentos": 8
            },
            "sobre_3_economico": {
                "nombre": "SOBRE No. 3 - PROPUESTA ECONÓMICA",
                "carpeta": "/data/outputs/{session}/SOBRE_3_ECONOMICO/",
                "documentos": [...],
                "total_documentos": 3
            }
        },
        "caratulas_generadas": [
            "/data/outputs/{session}/SOBRE_1_ADMINISTRATIVO/CARATULA.docx",
            "/data/outputs/{session}/SOBRE_2_TECNICO/CARATULA.docx",
            "/data/outputs/{session}/SOBRE_3_ECONOMICO/CARATULA.docx"
        ],
        "indice_general": "/data/outputs/{session}/INDICE_GENERAL.pdf"
    }
}
```

**Lógica de implementación:**

```python
class DocumentPackagerAgent(BaseAgent):
    """
    Agente: Empacador de Documentos.
    Organiza documentos en estructura de sobres según formato oficial.
    """

    async def process(self, session_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Recuperar todos los documentos generados de sesiones anteriores
        context = await self.context_manager.get_global_context(session_id)
        tasks = context.get("session_state", {}).get("tasks_completed", [])

        # 2. Buscar en RAG la estructura de sobres requerida
        estructura_query = await self.smart_search(
            session_id,
            "sobre número contenido documentación administrativa técnica económica presentación",
            n_results=5
        )

        # 3. Clasificar cada documento en su sobre correspondiente
        # - Usar el ID del requisito (1.x = administrativo, 2.x = técnico, 3.x = económico)
        # - Extraer orden de presentación de las bases

        # 4. Crear estructura de carpetas
        # SOBRE_1_ADMINISTRATIVO/
        # SOBRE_2_TECNICO/
        # SOBRE_3_ECONOMICO/

        # 5. Generar carátula por sobre (Word con índice)
        # Incluye: Nombre del sobre, número de licitación, empresa, fecha

        # 6. Mover/copiar documentos a carpetas correspondientes

        # 7. Generar Índice General (PDF con todos los documentos)

        # 8. Retornar estructura completa
```

**Formato de Carátula (Word):**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    SOBRE No. 1
          DOCUMENTACIÓN ADMINISTRATIVA

LICITACIÓN: LA-050GYR019-E123-2024
EMPRESA: Constructora Ejemplo S.A. de C.V.
RFC: EJE850101ABC
FECHA: 26 de marzo de 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONTENIDO:
1. Propuesta Administrativa
2. Acta Constitutiva
3. Poder del Representante Legal
...
```

---

### 2.3 DeliveryAgent (NUEVO)

**Ubicación:** `backend/app/agents/delivery.py`

**Responsabilidad:**
Generar instrucciones detalladas para la entrega de la propuesta, diferenciando entre licitación electrónica (portal web) y presencial (física).

**Input esperado:**
```python
{
    "session_id": "licitacion_abc_123",
    "estructura_sobres": {...},  # Output de DocumentPackagerAgent
    "tipo_licitacion": "electronica" | "presencial"  # Detectado de bases
}
```

**Output esperado:**
```python
{
    "status": "success",
    "data": {
        "tipo_licitacion": "electronica",
        "portal": {
            "nombre": "CompraNet",
            "url": "https://upcp-compranet.hacienda.gob.mx/",
            "instrucciones": [
                {
                    "paso": 1,
                    "accion": "Iniciar sesión con FIEL",
                    "detalle": "Usar la FIEL de la empresa registrada"
                },
                {
                    "paso": 2,
                    "accion": "Buscar la licitación",
                    "detalle": "Número: LA-050GYR019-E123-2024"
                },
                {
                    "paso": 3,
                    "accion": "Subir Sobre 1",
                    "detalle": "Archivo: SOBRE_1_ADMINISTRATIVO.zip",
                    "campo_portal": "Documentación Administrativa",
                    "formato_requerido": "PDF",
                    "tamano_maximo": "50 MB"
                },
                # ...
            ],
            "archivos_preparados": [
                {
                    "archivo_original": "ACTA_CONSTITUTIVA.docx",
                    "archivo_portal": "ACTA_CONSTITUTIVA.pdf",
                    "ruta": "/data/outputs/{session}/para_portal/",
                    "tamano_mb": 2.5
                }
            ]
        },
        "checklist_entrega": [
            {"item": "FIEL vigente", "status": "pendiente"},
            {"item": "Archivos en formato PDF", "status": "listo"},
            {"item": "Firma electrónica de documentos", "status": "pendiente"},
            # ...
        ],
        "fecha_limite": "2026-04-15T14:00:00",
        "alertas": [
            "⚠️ La fecha límite es en 20 días",
            "⚠️ Verificar que los archivos no excedan 50 MB"
        ]
    }
}
```

**Para licitación presencial:**
```python
{
    "tipo_licitacion": "presencial",
    "entrega_fisica": {
        "direccion": "Av. Universidad #123, Col. Centro, CDMX",
        "horario": "09:00 a 15:00 hrs",
        "contacto": "Lic. Juan Pérez, Tel: 55-1234-5678",
        "instrucciones_sobres": [
            {
                "sobre": "SOBRE No. 1",
                "contenido": "Documentación Administrativa",
                "presentacion": "Cerrado, membretado, firmado en la solapa",
                "cantidad_copias": 1
            },
            # ...
        ],
        "materiales_necesarios": [
            "3 sobres tamaño oficio",
            "Engargolador o folder con broche",
            "Separadores de colores",
            "Memorando de presentación"
        ]
    }
}
```

**Lógica de implementación:**

```python
class DeliveryAgent(BaseAgent):
    """
    Agente: Entrega de Propuesta.
    Genera instrucciones específicas para portal electrónico o entrega física.
    """

    async def process(self, session_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Detectar tipo de licitación (electrónica vs presencial)
        tipo_query = await self.smart_search(
            session_id,
            "licitación electrónica presencial plataforma portal CompraNet entrega física",
            n_results=3
        )
        tipo_licitacion = await self._detectar_tipo_llm(tipo_query)

        # 2. Si es electrónica:
        if tipo_licitacion == "electronica":
            # 2.1 Detectar portal (CompraNet, CompraMX, estatal, etc.)
            portal = await self._detectar_portal(tipo_query)

            # 2.2 Convertir todos los DOCX a PDF
            await self._convertir_a_pdf(estructura_sobres)

            # 2.3 Generar instrucciones paso a paso
            instrucciones = await self._generar_instrucciones_portal(portal, session_id)

            # 2.4 Generar checklist de requisitos del portal

        # 3. Si es presencial:
        else:
            # 3.1 Extraer dirección y horario de entrega
            datos_entrega = await self._extraer_datos_entrega(session_id)

            # 3.2 Generar instrucciones de armado de sobres físicos

            # 3.3 Lista de materiales necesarios

        # 4. Generar documento de instrucciones final (PDF/Word)

        # 5. Retornar estructura completa
```

**Dependencies adicionales:**
```
reportlab>=4.0.0  # Para generación de PDFs de instrucciones
```

---

## 3. MODIFICACIONES AL ORCHESTRATOR

### 3.1 Actualizar `backend/app/agents/orchestrator.py`

Agregar en la **FASE 2: GENERACIÓN** los nuevos agentes:

```python
# --- FASE 2: GENERACIÓN ---
if mode in ["full", "generation", "generation_only"]:
    print(f"[DEBUG ORCHESTRATOR] Entrando en Fase de Generación | Mode: {mode}")

    # Paso 3.5: DataGapAgent — EL GUARDIÁN (EXISTENTE)
    # ... código existente ...

    # Paso 4: Redacción Técnica (EXISTENTE)
    # ... código existente ...

    # Paso 5: Generación de Formatos (EXISTENTE)
    # ... código existente ...

    # ═══════════════════════════════════════════════════════════
    # NUEVOS PASOS - FASE 2 COMPLETA
    # ═══════════════════════════════════════════════════════════

    # Paso 6: Propuesta Económica (NUEVO)
    logger.info("[Agent 0 -> Agent 6] Generando Propuesta Económica...")
    from app.agents.economic_writer import EconomicWriterAgent
    economic_writer = EconomicWriterAgent(self.context_manager)
    try:
        economic_writer_result = await economic_writer.process(session_id, input_data)
        execution_results["economic_writer"] = economic_writer_result
        input_data["economic_docs"] = economic_writer_result.get("data", {})
        next_steps.append("economic_writing_COMPLETED")
    except Exception as e:
        logger.error(f"Error en EconomicWriterAgent: {e}")
        execution_results["economic_writer"] = {"status": "error", "message": str(e)}

    # Paso 7: Empacado de Documentos (NUEVO)
    logger.info("[Agent 0 -> Agent 7] Empacando Documentos en Sobres...")
    from app.agents.document_packager import DocumentPackagerAgent
    packager = DocumentPackagerAgent(self.context_manager)
    try:
        packager_result = await packager.process(session_id, input_data)
        execution_results["packager"] = packager_result
        input_data["structure"] = packager_result.get("data", {})
        next_steps.append("document_packaging_COMPLETED")
    except Exception as e:
        logger.error(f"Error en DocumentPackagerAgent: {e}")
        execution_results["packager"] = {"status": "error", "message": str(e)}

    # Paso 8: Instrucciones de Entrega (NUEVO)
    logger.info("[Agent 0 -> Agent 8] Generando Instrucciones de Entrega...")
    from app.agents.delivery import DeliveryAgent
    delivery = DeliveryAgent(self.context_manager)
    try:
        delivery_result = await delivery.process(session_id, input_data)
        execution_results["delivery"] = delivery_result
        next_steps.append("delivery_instructions_COMPLETED")
    except Exception as e:
        logger.error(f"Error en DeliveryAgent: {e}")
        execution_results["delivery"] = {"status": "error", "message": str(e)}
```

---

## 4. SCHEMAS PYDANTIC

### 4.1 Agregar a `backend/app/api/schemas/responses.py`

```python
class EconomicDocument(BaseModel):
    """Documento económico generado"""
    nombre: str
    ruta: str
    tipo: str  # anexo_economico, tabla_precios, carta_compromiso
    status: str

class EconomicWriterResponse(BaseModel):
    """Respuesta del EconomicWriterAgent"""
    status: str
    folder: str
    documentos: List[EconomicDocument]
    resumen_economico: Dict[str, Any]

class SobreDocument(BaseModel):
    """Documento dentro de un sobre"""
    orden: int
    nombre: str
    archivo: str

class Sobre(BaseModel):
    """Estructura de un sobre"""
    nombre: str
    carpeta: str
    documentos: List[SobreDocument]
    total_documentos: int

class PackagerResponse(BaseModel):
    """Respuesta del DocumentPackagerAgent"""
    status: str
    estructura_sobres: Dict[str, Sobre]
    caratulas_generadas: List[str]
    indice_general: str

class InstructionStep(BaseModel):
    """Paso de instrucción de entrega"""
    paso: int
    accion: str
    detalle: str
    campo_portal: Optional[str] = None
    formato_requerido: Optional[str] = None
    tamano_maximo: Optional[str] = None

class PortalInfo(BaseModel):
    """Información del portal electrónico"""
    nombre: str
    url: str
    instrucciones: List[InstructionStep]
    archivos_preparados: List[Dict[str, Any]]

class DeliveryResponse(BaseModel):
    """Respuesta del DeliveryAgent"""
    status: str
    tipo_licitacion: str  # electronica | presencial
    portal: Optional[PortalInfo]
    entrega_fisica: Optional[Dict[str, Any]]
    checklist_entrega: List[Dict[str, str]]
    fecha_limite: Optional[str]
    alertas: List[str]
```

---

## 5. TESTS

### 5.1 Tests Unitarios

**Ubicación:** `backend/tests/agents/`

Crear los siguientes archivos de test:

#### `test_economic_writer.py`

```python
import pytest
from app.agents.economic_writer import EconomicWriterAgent
from app.agents.mcp_context import MCPContextManager

@pytest.mark.asyncio
async def test_economic_writer_generates_documents():
    """Verifica que el agente genera los 3 documentos económicos esperados."""
    # Setup
    context_manager = MCPContextManager()
    agent = EconomicWriterAgent(context_manager)

    input_data = {
        "session_id": "test_session_001",
        "company_id": "test_company",
        "company_data": {
            "master_profile": {
                "razon_social": "Empresa Test S.A. de C.V.",
                "rfc": "TEST850101ABC",
                "representante_legal": "Juan Pérez"
            },
            "catalogo_precios": [
                {"concepto": "Suministro de material", "precio": 150.00, "unidad": "Pieza"},
                {"concepto": "Instalación", "precio": 200.00, "unidad": "Servicio"}
            ]
        },
        "compliance_master_list": {
            "tecnico": [],
            "administrativo": [],
            "formatos": []
        }
    }

    # Execute
    result = await agent.process("test_session_001", input_data)

    # Assert
    assert result["status"] == "success"
    assert len(result["data"]["documentos"]) >= 3
    assert any(d["tipo"] == "anexo_economico" for d in result["data"]["documentos"])
    assert any(d["tipo"] == "tabla_precios" for d in result["data"]["documentos"])
    assert any(d["tipo"] == "carta_compromiso" for d in result["data"]["documentos"])
    assert result["data"]["resumen_economico"]["total"] > 0


@pytest.mark.asyncio
async def test_economic_writer_handles_empty_catalog():
    """Verifica manejo de catálogo vacío."""
    context_manager = MCPContextManager()
    agent = EconomicWriterAgent(context_manager)

    input_data = {
        "session_id": "test_session_002",
        "company_data": {
            "catalogo_precios": []
        }
    }

    result = await agent.process("test_session_002", input_data)

    # Debe retornar error o status específico
    assert result["status"] in ["error", "waiting_for_data"]


@pytest.mark.asyncio
async def test_economic_writer_calculates_totals_correctly():
    """Verifica cálculo correcto de subtotal, IVA y total."""
    context_manager = MCPContextManager()
    agent = EconomicWriterAgent(context_manager)

    # Con valores conocidos
    input_data = {
        "session_id": "test_session_003",
        "company_data": {
            "catalogo_precios": [
                {"concepto": "Item 1", "precio": 1000.00, "cantidad": 10},
                {"concepto": "Item 2", "precio": 500.00, "cantidad": 5}
            ]
        }
    }

    result = await agent.process("test_session_003", input_data)

    subtotal = result["data"]["resumen_economico"]["subtotal"]
    iva = result["data"]["resumen_economico"]["iva"]
    total = result["data"]["resumen_economico"]["total"]

    # Verificar cálculos: subtotal = 10000 + 2500 = 12500
    # IVA 16% = 2000
    # Total = 14500
    assert subtotal == 12500.00
    assert iva == 2000.00
    assert total == 14500.00
```

#### `test_document_packager.py`

```python
import pytest
import os
from app.agents.document_packager import DocumentPackagerAgent
from app.agents.mcp_context import MCPContextManager

@pytest.mark.asyncio
async def test_packager_creates_sobre_structure():
    """Verifica creación de estructura de 3 sobres."""
    context_manager = MCPContextManager()
    agent = DocumentPackagerAgent(context_manager)

    input_data = {
        "session_id": "test_session_001",
        "documentos_generados": {
            "tecnica": [{"nombre": "Carta Presentación", "ruta": "/tmp/test.docx"}],
            "administrativa": [{"nombre": "Acta Constitutiva", "ruta": "/tmp/test.docx"}],
            "economica": [{"nombre": "Propuesta Económica", "ruta": "/tmp/test.docx"}]
        }
    }

    result = await agent.process("test_session_001", input_data)

    assert result["status"] == "success"
    assert "sobre_1_administrativo" in result["data"]["estructura_sobres"]
    assert "sobre_2_tecnico" in result["data"]["estructura_sobres"]
    assert "sobre_3_economico" in result["data"]["estructura_sobres"]


@pytest.mark.asyncio
async def test_packager_generates_caratulas():
    """Verifica generación de carátulas por sobre."""
    context_manager = MCPContextManager()
    agent = DocumentPackagerAgent(context_manager)

    result = await agent.process("test_session_001", {})

    caratulas = result["data"]["caratulas_generadas"]
    assert len(caratulas) == 3
    assert all(c.endswith("CARATULA.docx") for c in caratulas)


@pytest.mark.asyncio
async def test_packager_classifies_documents_correctly():
    """Verifica que documentos con ID 1.x van a Sobre 1, 2.x a Sobre 2, etc."""
    context_manager = MCPContextManager()
    agent = DocumentPackagerAgent(context_manager)

    input_data = {
        "session_id": "test_session_001",
        "documentos_generados": {
            "administrativa": [
                {"id": "1.1", "nombre": "Acta Constitutiva"},
                {"id": "1.2", "nombre": "RFC"}
            ],
            "tecnica": [
                {"id": "2.1", "nombre": "Propuesta Técnica"}
            ],
            "economica": [
                {"id": "3.1", "nombre": "Propuesta Económica"}
            ]
        }
    }

    result = await agent.process("test_session_001", input_data)

    sobre_1 = result["data"]["estructura_sobres"]["sobre_1_administrativo"]
    sobre_2 = result["data"]["estructura_sobres"]["sobre_2_tecnico"]
    sobre_3 = result["data"]["estructura_sobres"]["sobre_3_economico"]

    assert sobre_1["total_documentos"] == 2
    assert sobre_2["total_documentos"] == 1
    assert sobre_3["total_documentos"] == 1
```

#### `test_delivery.py`

```python
import pytest
from app.agents.delivery import DeliveryAgent
from app.agents.mcp_context import MCPContextManager

@pytest.mark.asyncio
async def test_delivery_detects_electronica():
    """Verifica detección correcta de licitación electrónica."""
    context_manager = MCPContextManager()
    agent = DeliveryAgent(context_manager)

    # Mock de estructura con indicadores de electrónica
    result = await agent.process("test_electronica_001", {
        "tipo_licitacion": "electronica"
    })

    assert result["data"]["tipo_licitacion"] == "electronica"
    assert result["data"]["portal"] is not None
    assert "instrucciones" in result["data"]["portal"]


@pytest.mark.asyncio
async def test_delivery_detects_presencial():
    """Verifica detección correcta de licitación presencial."""
    context_manager = MCPContextManager()
    agent = DeliveryAgent(context_manager)

    result = await agent.process("test_presencial_001", {
        "tipo_licitacion": "presencial"
    })

    assert result["data"]["tipo_licitacion"] == "presencial"
    assert result["data"]["entrega_fisica"] is not None
    assert "direccion" in result["data"]["entrega_fisica"]


@pytest.mark.asyncio
async def test_delivery_generates_checklist():
    """Verifica generación de checklist de entrega."""
    context_manager = MCPContextManager()
    agent = DeliveryAgent(context_manager)

    result = await agent.process("test_session_001", {})

    checklist = result["data"]["checklist_entrega"]
    assert len(checklist) >= 5
    assert any("FIEL" in c["item"] for c in checklist)


@pytest.mark.asyncio
async def test_delivery_extracts_deadline():
    """Verifica extracción de fecha límite de las bases."""
    context_manager = MCPContextManager()
    agent = DeliveryAgent(context_manager)

    result = await agent.process("test_session_001", {})

    # Debe tener fecha límite o None si no se encontró
    assert "fecha_limite" in result["data"]
```

### 5.2 Tests de Integración

#### `test_phase2_integration.py`

```python
import pytest
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager

@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_phase2_pipeline():
    """Test de integración: Fase 2 completa con todos los agentes."""
    context_manager = MCPContextManager()
    orchestrator = OrchestratorAgent(context_manager)

    # Input completo
    input_data = {
        "session_id": "integration_test_001",
        "company_id": "test_company",
        "company_data": {
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Empresa Test S.A. de C.V.",
                "rfc": "TEST850101ABC",
                "representante_legal": "Juan Pérez",
                "domicilio_fiscal": "Av. Test #123, CDMX"
            },
            "catalogo_precios": [
                {"concepto": "Suministro", "precio": 100.00, "unidad": "Pieza", "cantidad": 50}
            ]
        }
    }

    # Ejecutar Fase 2 completa
    result = await orchestrator.process("integration_test_001", input_data)

    # Verificar que todos los agentes se ejecutaron
    assert result["status"] == "success"
    assert "technical" in result["results"]
    assert "formats" in result["results"]
    assert "economic_writer" in result["results"]
    assert "packager" in result["results"]
    assert "delivery" in result["results"]

    # Verificar estructura de carpetas creada
    assert os.path.exists("/data/outputs/integration_test_001")
    assert os.path.exists("/data/outputs/integration_test_001/SOBRE_1_ADMINISTRATIVO")
    assert os.path.exists("/data/outputs/integration_test_001/SOBRE_2_TECNICO")
    assert os.path.exists("/data/outputs/integration_test_001/SOBRE_3_ECONOMICO")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_phase2_handles_missing_company_data():
    """Verifica que Fase 2 detecta datos faltantes y retorna waiting_for_data."""
    context_manager = MCPContextManager()
    orchestrator = OrchestratorAgent(context_manager)

    input_data = {
        "session_id": "test_missing_data",
        "company_data": {
            "mode": "generation_only",
            "master_profile": {}  # Sin datos de empresa
        }
    }

    result = await orchestrator.process("test_missing_data", input_data)

    # Debe detenerse en DataGapAgent
    assert result["status"] == "waiting_for_data"
    assert "missing_fields" in result
```

### 5.3 Script de Validación Manual

#### `scripts/validate_phase2.py`

```python
"""
Script de validación manual para Fase 2.
Ejecutar con: python scripts/validate_phase2.py --session test_session

Verifica:
1. Todos los archivos DOCX se generaron correctamente
2. Los PDFs convertidos son válidos
3. La estructura de carpetas es correcta
4. El índice general contiene todos los documentos
"""

import os
import sys
import argparse
from docx import Document
from PyPDF2 import PdfReader

def validate_docx(filepath):
    """Valida que un archivo DOCX es legible."""
    try:
        doc = Document(filepath)
        return len(doc.paragraphs) > 0
    except Exception as e:
        print(f"❌ Error en {filepath}: {e}")
        return False

def validate_pdf(filepath):
    """Valida que un PDF es legible."""
    try:
        reader = PdfReader(filepath)
        return len(reader.pages) > 0
    except Exception as e:
        print(f"❌ Error en {filepath}: {e}")
        return False

def validate_structure(base_path):
    """Valida la estructura de carpetas."""
    required_folders = [
        "1.propuesta_tecnica",
        "2.propuesta_economica",
        "3.documentos_administrativos",
        "SOBRE_1_ADMINISTRATIVO",
        "SOBRE_2_TECNICO",
        "SOBRE_3_ECONOMICO"
    ]

    results = {}
    for folder in required_folders:
        path = os.path.join(base_path, folder)
        exists = os.path.exists(path)
        results[folder] = exists
        status = "✅" if exists else "❌"
        print(f"{status} {folder}")

    return results

def run_validation(session_name):
    """Ejecuta validación completa."""
    base_path = f"/data/outputs/{session_name}"

    print(f"\n{'='*60}")
    print(f"VALIDACIÓN FASE 2 - {session_name}")
    print(f"{'='*60}\n")

    if not os.path.exists(base_path):
        print(f"❌ No existe el directorio: {base_path}")
        return False

    # 1. Validar estructura
    print("📁 Estructura de carpetas:")
    structure_results = validate_structure(base_path)

    # 2. Validar DOCXs
    print(f"\n📄 Documentos DOCX:")
    docx_files = []
    for root, dirs, files in os.walk(base_path):
        for f in files:
            if f.endswith(".docx"):
                docx_files.append(os.path.join(root, f))

    docx_valid = 0
    for f in docx_files:
        if validate_docx(f):
            docx_valid += 1
            print(f"  ✅ {os.path.basename(f)}")
        else:
            print(f"  ❌ {os.path.basename(f)}")

    # 3. Validar PDFs (si existen)
    print(f"\n📑 Archivos PDF:")
    pdf_files = []
    for root, dirs, files in os.walk(base_path):
        for f in files:
            if f.endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))

    pdf_valid = 0
    for f in pdf_files:
        if validate_pdf(f):
            pdf_valid += 1
            print(f"  ✅ {os.path.basename(f)}")

    # 4. Resumen
    print(f"\n{'='*60}")
    print("RESUMEN:")
    print(f"  Carpetas esperadas: {sum(structure_results.values())}/{len(structure_results)}")
    print(f"  DOCX válidos: {docx_valid}/{len(docx_files)}")
    print(f"  PDFs válidos: {pdf_valid}/{len(pdf_files)}")
    print(f"{'='*60}\n")

    # Criterios de éxito
    all_folders = all(structure_results.values())
    all_docx_valid = docx_valid == len(docx_files)

    if all_folders and all_docx_valid:
        print("✅ VALIDACIÓN EXITOSA - Listo para pruebas de campo")
        return True
    else:
        print("⚠️ VALIDACIÓN CON ERRORES - Revisar antes de liberar")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validar Fase 2")
    parser.add_argument("--session", required=True, help="Nombre de la sesión")
    args = parser.parse_args()

    success = run_validation(args.session)
    sys.exit(0 if success else 1)
```

---

## 6. FRONTEND: ACTUALIZACIONES

### 6.1 Modificar `frontend/src/App.jsx`

Agregar visualización de los nuevos agentes en el Dashboard:

```jsx
// En el componente App.jsx, agregar estados para los nuevos resultados:
const [economicResults, setEconomicResults] = useState(null);
const [packagerResults, setPackagerResults] = useState(null);
const [deliveryResults, setDeliveryResults] = useState(null);

// Actualizar triggerGeneration para manejar nuevos resultados:
const triggerGeneration = async () => {
    // ... código existente ...

    const res = await axios.post(`${API_BASE}/agents/process`, {
        session_id: sessionId,
        company_id: selectedCompanyId,
        company_data: { "mode": "generation_only" }
    });

    if (res.data.status === "success") {
        const { technical, formats, economic_writer, packager, delivery } = res.data.results;

        setGenerationResults(res.data.data);
        setEconomicResults(economic_writer?.data);
        setPackagerResults(packager?.data);
        setDeliveryResults(delivery?.data);
    }
};
```

### 6.2 Crear componente `DeliveryInstructions.jsx`

**Ubicación:** `frontend/src/components/DeliveryInstructions.jsx`

```jsx
import React from 'react';
import { FileCheck, Upload, MapPin, Clock, AlertTriangle, CheckCircle } from 'lucide-react';

const DeliveryInstructions = ({ deliveryData }) => {
    if (!deliveryData) return null;

    const { tipo_licitacion, portal, entrega_fisica, checklist_entrega, alertas } = deliveryData;

    return (
        <div className="delivery-instructions">
            <h3>
                {tipo_licitacion === 'electronica' ? <Upload size={20} /> : <MapPin size={20} />}
                Instrucciones de Entrega - {tipo_licitacion === 'electronica' ? 'Portal Electrónico' : 'Entrega Presencial'}
            </h3>

            {/* Alertas */}
            {alertas?.length > 0 && (
                <div className="alerts-box">
                    {alertas.map((alert, i) => (
                        <div key={i} className="alert-item">
                            <AlertTriangle size={14} />
                            <span>{alert}</span>
                        </div>
                    ))}
                </div>
            )}

            {/* Instrucciones Portal Electrónico */}
            {tipo_licitacion === 'electronica' && portal && (
                <div className="portal-section">
                    <h4>{portal.nombre}</h4>
                    <a href={portal.url} target="_blank" rel="noopener noreferrer">{portal.url}</a>

                    <ol className="instructions-list">
                        {portal.instrucciones.map((inst) => (
                            <li key={inst.paso}>
                                <strong>Paso {inst.paso}:</strong> {inst.accion}
                                <p>{inst.detalle}</p>
                                {inst.formato_requerido && (
                                    <span className="format-badge">Formato: {inst.formato_requerido}</span>
                                )}
                            </li>
                        ))}
                    </ol>
                </div>
            )}

            {/* Instrucciones Entrega Presencial */}
            {tipo_licitacion === 'presencial' && entrega_fisica && (
                <div className="presencial-section">
                    <div className="address-box">
                        <MapPin size={16} />
                        <div>
                            <strong>Dirección:</strong>
                            <p>{entrega_fisica.direccion}</p>
                            <span><Clock size={14} /> {entrega_fisica.horario}</span>
                        </div>
                    </div>

                    <h4>Instrucciones de Sobres:</h4>
                    {entrega_fisica.instrucciones_sobres?.map((sobre, i) => (
                        <div key={i} className="sobre-card">
                            <h5>{sobre.sobre}</h5>
                            <p>{sobre.contenido}</p>
                            <span>{sobre.presentacion}</span>
                        </div>
                    ))}

                    <h4>Materiales Necesarios:</h4>
                    <ul>
                        {entrega_fisica.materiales_necesarios?.map((mat, i) => (
                            <li key={i}>{mat}</li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Checklist */}
            <div className="checklist-section">
                <h4><FileCheck size={16} /> Checklist de Entrega</h4>
                {checklist_entrega?.map((item, i) => (
                    <div key={i} className="checklist-item">
                        {item.status === 'listo' ? <CheckCircle size={14} color="green" /> : <Clock size={14} />}
                        <span>{item.item}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default DeliveryInstructions;
```

---

## 7. DEPENDENCIES ADICIONALES

### 7.1 Actualizar `backend/requirements.txt`

```
# Dependencias existentes
fastapi>=0.104.0
uvicorn>=0.24.0
pydantic>=2.5.0
sqlalchemy>=2.0.0
asyncpg>=0.29.0
httpx>=0.25.0
python-docx>=1.1.0
chromadb-client>=0.4.0
redis>=5.0.0

# Nuevas dependencias para Fase 2
openpyxl>=3.1.0          # Para Excel (tabla de precios)
reportlab>=4.0.0         # Para PDFs de instrucciones
PyPDF2>=3.0.0            # Para validación de PDFs
python-magic>=0.4.27     # Para detección de MIME types
```

---

## 8. CRITERIOS DE ACEPTACIÓN

### 8.1 EconomicWriterAgent

| ID | Criterio | Verificación |
|----|----------|--------------|
| EC-01 | Genera Anexo AE en formato DOCX | Test unitario + validación manual |
| EC-02 | Genera Tabla de Precios en Excel | Test unitario + abrir en Excel |
| EC-03 | Genera Carta de Compromiso | Test unitario |
| EC-04 | Calcula subtotal, IVA y total correctamente | Test con valores conocidos |
| EC-05 | Maneja catálogo vacío con error descriptivo | Test unitario |
| EC-06 | Usa logo y datos del master_profile | Validación visual |

### 8.2 DocumentPackagerAgent

| ID | Criterio | Verificación |
|----|----------|--------------|
| PK-01 | Crea estructura de 3 sobres | Test unitario + validación filesystem |
| PK-02 | Clasifica documentos por ID (1.x, 2.x, 3.x) | Test unitario |
| PK-03 | Genera carátula por sobre | Validación visual de DOCX |
| PK-04 | Genera índice general en PDF | Test unitario |
| PK-05 | Ordena documentos según bases | Validación manual |
| PK-06 | Maneja documentos sin ID con clasificación por LLM | Test unitario |

### 8.3 DeliveryAgent

| ID | Criterio | Verificación |
|----|----------|--------------|
| DL-01 | Detecta correctamente tipo (electrónica vs presencial) | Test unitario |
| DL-02 | Genera instrucciones paso a paso para portal | Validación visual |
| DL-03 | Genera instrucciones de armado físico | Validación visual |
| DL-04 | Extrae fecha límite de las bases | Test unitario |
| DL-05 | Genera checklist de entrega | Test unitario |
| DL-06 | Convierte DOCX a PDF para portal | Validación filesystem |

### 8.4 Integración Fase 2

| ID | Criterio | Verificación |
|----|----------|--------------|
| IN-01 | Orchestrator ejecuta los 3 nuevos agentes en orden | Test de integración |
| IN-02 | Flujo completo genera estructura final lista para entregar | Script de validación |
| IN-03 | Maneja errores de cada agente sin romper flujo | Test de integración |
| IN-04 | Frontend muestra instrucciones de entrega | Validación visual |
| IN-05 | Tiempo total de ejecución < 10 minutos para licitación típica | Benchmark |

---

## 9. INSTRUCCIONES DE IMPLEMENTACIÓN

### 9.1 Orden de Implementación

1. **Primero:** Implementar `EconomicWriterAgent`
   - Crear archivo `economic_writer.py`
   - Implementar lógica de generación de documentos
   - Tests unitarios

2. **Segundo:** Implementar `DocumentPackagerAgent`
   - Crear archivo `document_packager.py`
   - Implementar clasificación y estructuración
   - Tests unitarios

3. **Tercero:** Implementar `DeliveryAgent`
   - Crear archivo `delivery.py`
   - Implementar detección de tipo y generación de instrucciones
   - Tests unitarios

4. **Cuarto:** Integrar con Orchestrator
   - Modificar `orchestrator.py`
   - Agregar nuevos pasos en Fase 2
   - Test de integración

5. **Quinto:** Actualizar Frontend
   - Crear componente `DeliveryInstructions.jsx`
   - Actualizar `App.jsx`
   - Validación visual

6. **Sexto:** Script de validación
   - Crear `scripts/validate_phase2.py`
   - Ejecutar con sesión de prueba

### 9.2 Antes de Liberar a Pruebas de Campo

Ejecutar en orden:

```bash
# 1. Correr tests unitarios
cd backend
pytest tests/agents/test_economic_writer.py -v
pytest tests/agents/test_document_packager.py -v
pytest tests/agents/test_delivery.py -v

# 2. Correr tests de integración
pytest tests/integration/test_phase2_integration.py -v

# 3. Correr validación manual con sesión de prueba
python scripts/validate_phase2.py --session test_integration_001

# 4. Verificar que el frontend muestra correctamente los resultados
# (Manual: abrir http://localhost:8504 y ejecutar generación)

# 5. Verificar logs de backend
docker-compose logs -f backend | grep -E "(Economic|Packager|Delivery)"
```

### 9.3 Checklist Pre-Liberación

- [ ] Todos los tests unitarios pasan
- [ ] Test de integración pasa
- [ ] Script de validación reporta "VALIDACIÓN EXITOSA"
- [ ] Frontend muestra instrucciones de entrega correctamente
- [ ] No hay errores en logs de backend
- [ ] Los archivos generados son legibles (abrir en Word/Excel)
- [ ] La estructura de carpetas es correcta
- [ ] Los cálculos de totales son correctos (verificar manualmente)
- [ ] El índice general contiene todos los documentos

---

## 10. NOTAS ADICIONALES

### 10.1 Consideraciones de VRAM

Los 3 nuevos agentes usan LLM, por lo que **respetan el semáforo de VRAM** (`LLM_SEMAPHORE`). Esto significa que se ejecutan secuencialmente, no en paralelo.

### 10.2 Manejo de Errores

Cada agente debe capturar sus excepciones y retornar un status claro:
- `"success"`: Documentos generados correctamente
- `"error"`: Error durante generación (incluir mensaje)
- `"waiting_for_data"`: Faltan datos necesarios

### 10.3 Logging

Usar el logger estándar de Python con prefijos identificadores:
```python
print(f"[EconomicWriter] 🔖 Generando propuesta económica...")
print(f"[Packager] 📦 Organizando documentos en sobres...")
print(f"[Delivery] 📋 Generando instrucciones de entrega...")
```

### 10.4 Compatibilidad

Los nuevos agentes deben ser compatibles con:
- Python 3.10+
- Windows 11 (entorno de desarrollo actual)
- Docker (entorno de producción)

---

**FIN DEL DOCUMENTO**