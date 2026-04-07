import asyncio
import json
import logging
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_performance():
    # 1. Configurar infraestructura
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    mcp_manager = MCPContextManager(memory_repository=memory)
    orchestrator = OrchestratorAgent(context_manager=mcp_manager)
    
    # 2. Definir sesión de prueba (Licitación Psiquiatría)
    session_id = "instituto_nacional_de_psiquiatra_ramn_de_la_fuente_muz"
    
    # Datos de empresa simulados (Manavil)
    input_data = {
        "company_data": {
            "mode": "full",
            "master_profile": {
                "tipo": "moral",
                "razon_social": "MANAVIL SEGURIDAD PRIVADA S.A. DE C.V.",
                "rfc": "MSP1234567A8",
                "representante_legal": "Yunuen Ivon Aceves Sanchez",
                "domicilio_fiscal": "Avenida Insurgentes Sur 1602, Ciudad de México",
                "telefono": "55 1234 5678",
                "web": "https://manavilseguridad.com.mx"
            }
        }
    }
    
    print("\n" + "="*50)
    print("🚀 INICIANDO PRUEBA DE DESEMPEÑO: AGENTES vs MANO")
    print("="*50)
    
    try:
        # Ejecutar Orquestación
        resultado = await orchestrator.process(session_id, input_data)
        
        # 3. Extraer Hallazgos de los Agentes
        compliance_data = resultado.get("results", {}).get("compliance", {}).get("data", {})
        admin_items = compliance_data.get("administrativo", [])
        tech_items = compliance_data.get("tecnico", [])
        formats_items = compliance_data.get("formatos", [])
        
        print("\n" + "-"*30)
        print("📊 HALLAZGOS DEL AGENTE (COMPLIANCE):")
        print(f"✅ Administrativos detectados: {len(admin_items)}")
        for item in admin_items:
            print(f"  - {item.get('id')}: {item.get('nombre')}")
            
        print(f"\n✅ Técnicos detectados: {len(tech_items)}")
        for item in tech_items:
            print(f"  - {item.get('id')}: {item.get('nombre')}")
            
        # 4. Verificar generación de archivos
        formats_gen = resultado.get("results", {}).get("formats", {}).get("documentos_generados", [])
        print(f"\n📄 DOCUMENTOS GENERADOS (FORMATS): {len(formats_gen)}")
        
        # 5. DICTAMEN FINAL
        print("\n" + "="*50)
        print("🏁 DICTAMEN DE ANTIGRAVITY:")
        
        # Evaluación de cobertura (Basada en mi lista manual: 1.1 al 1.19 admin, 2.1 al 2.35 tech)
        total_admin_expected = 19
        total_tech_expected = 35
        
        admin_ratio = (len(admin_items) / total_admin_expected) * 100
        tech_ratio = (len(tech_items) / total_tech_expected) * 100
        
        print(f"🎯 Cobertura Administrativa: {admin_ratio:.1f}%")
        print(f"🎯 Cobertura Técnica: {tech_ratio:.1f}%")
        
        if admin_ratio >= 90 and tech_ratio >= 90:
            print("\n🌟 RESULTADO: ÉXITO TOTAL. El agente ha igualado la precisión humana.")
        elif admin_ratio > 70:
            print("\n📈 RESULTADO: MEJORA SIGNIFICATIVA. El barrido secuencial funciona, pero hay ruido.")
        else:
            print("\n⚠️ RESULTADO: INSUFICIENTE. Aún hay pérdida de contexto.")
        print("="*50)

    except Exception as e:
        print(f"❌ Error durante la prueba: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(test_performance())
