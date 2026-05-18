import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check_company_details():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    cid = "co_1777426690421"
    c = await m.get_company(cid)
    if c:
        print(f"Company: {c['name']}")
        print(f"Profile keys: {list(c.get('master_profile', {}).keys())}")
        print(f"Docs count: {len(c.get('docs', {}))}")
        for doc_id, doc_info in c.get('docs', {}).items():
            print(f" - Doc: {doc_info.get('filename')} | Type: {doc_info.get('type')}")
    else:
        print("Company not found")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check_company_details())
