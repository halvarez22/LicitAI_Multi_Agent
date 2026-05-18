#!/usr/bin/env python
"""Script de diagnóstico para verificar el perfil de la empresa."""
import asyncio
import json
from app.contracts.session_contracts import get_repository


async def check_company_profile(company_id: str):
    """Verifica el perfil de una empresa específica."""
    repo = await get_repository()
    try:
        company = await repo.get_company(company_id)
        if not company:
            print(f"❌ Empresa '{company_id}' NO encontrada")
            return
        
        print(f"\n✅ Empresa encontrada: {company.get('name', 'Sin nombre')}")
        print(f"   ID: {company.get('id', 'Sin ID')}")
        print(f"   Tipo: {company.get('type', 'Sin tipo')}")
        
        master_profile = company.get('master_profile', {})
        print(f"\n📋 MASTER_PROFILE:")
        if not master_profile:
            print("   ⚠️  PERFIL VACÍO - No hay datos extraídos")
        else:
            for key, value in master_profile.items():
                if key == "provenance_ui":
                    continue
                print(f"   - {key}: {value}")
        
        docs = company.get('docs', {})
        print(f"\n📁 DOCUMENTOS ({len(docs)}):")
        for doc_title, doc_info in docs.items():
            status = doc_info.get('status', 'UNKNOWN')
            name = doc_info.get('name', 'Sin nombre')
            print(f"   - {doc_title}: {status} ({name})")
        
        # Verificar si hay datos en el perfil
        required_fields = ['razon_social', 'rfc', 'representante_legal', 'domicilio_fiscal']
        missing = [f for f in required_fields if not master_profile.get(f)]
        
        if missing:
            print(f"\n⚠️  CAMPOS FALTANTES: {missing}")
        else:
            print(f"\n✅ PERFIL COMPLETO - Todos los campos requeridos están presentes")
            
    finally:
        await repo.disconnect()


async def list_all_companies():
    """Lista todas las empresas disponibles."""
    repo = await get_repository()
    try:
        # Esta función depende de tu implementación del repositorio
        # Ajusta según sea necesario
        print("\n🔍 Buscando empresas en la base de datos...")
        # Por ahora, intentamos con el ID conocido
        await check_company_profile("comercializadora-mayo-y-torres")
    finally:
        await repo.disconnect()


if __name__ == "__main__":
    import sys
    company_id = sys.argv[1] if len(sys.argv) > 1 else "comercializadora-mayo-y-torres"
    asyncio.run(check_company_profile(company_id))
