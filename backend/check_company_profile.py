import asyncio
from app.memory.factory import MemoryAdapterFactory
from app.models.company import Company
from sqlalchemy.future import select

async def check():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    async with memory.async_session() as db_session:
        # 1. Buscar la empresa
        result = await db_session.execute(select(Company).filter(Company.name.ilike('%Tecnologia Integrales%')))
        company = result.scalars().first()
        
        if not company:
            print("Empresa no encontrada.")
            return
            
        print(f"Empresa: {company.name} (ID: {company.id})")
        print(f"Tipo: {company.type}")
        
        # 2. Perfil Maestro (JSON con docs y metadata)
        print("\n--- PERFIL MAESTRO ---")
        import json
        profile = company.master_profile or {}
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        
        # 3. Documentos en 'docs' field (si existen)
        docs = company.docs or {}
        print(f"\nDocumentos en 'docs' ({len(docs)}):")
        for doc_id, doc_meta in docs.items():
            print(f"- {doc_meta.get('filename')} ({doc_meta.get('type')})")

if __name__ == "__main__":
    asyncio.run(check())
