import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def get_session_dictamen():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    session_id = "suministro_e_instalacin_de_paneles_solares"
    session_data = await m.get_session(session_id)
    if session_data:
        fast_track = session_data.get("document_candidates_final") or session_data.get("document_candidates_v1")
        print(f"Fast Track Candidates found in session: {bool(fast_track)}")
        if fast_track:
            print(json.dumps(fast_track, indent=2))
        else:
            print("Keys in session_data:", list(session_data.keys()))
            if "dictamen" in session_data:
                print("Keys in dictamen:", list(session_data["dictamen"].keys()))
    else:
        print("Session not found")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(get_session_dictamen())
