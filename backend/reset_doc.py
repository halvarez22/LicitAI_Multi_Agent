import asyncio
from app.memory.factory import MemoryAdapterFactory

async def fix_sync():
    doc_id = '67e20de9-9c3a-4a5e-b7e5-734cf2558cb5'
    session_id = 'licitacion_opm-001-2026_maderas_chihuahiua'
    real_file = "/data/uploads/7ee4512f-4286-4315-a675-940b7f66544d_bases_licitacion_opm-001-2026.pdf"
    
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    content = {
        "status": "UPLOADED",
        "file_path": real_file,
        "filename": "Bases licitacion OPM-001-2026.pdf"
    }
    await memory.save_document(doc_id, session_id, content, {"status": "UPLOADED"})
    print(f"Fixed! DB {doc_id} now points to file 7ee4512f...")
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(fix_sync())
