import os
import sys
import time
import asyncio
from typing import Dict

# Ajuste de entorno mínimo para ejecución local
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/licitaciones")
os.environ.setdefault("VECTOR_DB_URL", "http://localhost:8000")
os.environ.setdefault("LLM_URL", "http://localhost:11434")
os.environ.setdefault("MEMORY_BACKEND", "postgres")

sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

from app.memory.factory import MemoryAdapterFactory
from app.agents.mcp_context import MCPContextManager
from app.agents.compliance import ComplianceAgent


class AdminOnlyComplianceAgent(ComplianceAgent):
    """
    Variante de Compliance que procesa una sola macro-zona (admin, tecnico, formatos, garantias).
    Pruebas de integración más rápidas que el E2E completo.
    """

    def __init__(self, context_manager: MCPContextManager, zone_key: str):
        super().__init__(context_manager)
        self.zone_key = zone_key

    async def process(self, session_id: str, input_data):
        llm = self.llm_service if hasattr(self, "llm_service") else None

        zone_def = self._zone_definition(self.zone_key)
        print(f"📋 [LicitAI] PRUEBA INTEGRACIÓN: {zone_def['name']}")
        print("-" * 63)
        print(f"🕵️ Sesión de prueba: {session_id}")

        start_global = time.time()

        search_zones = [zone_def]

        # Configuración heredada de Compliance
        chunk_size = int(os.getenv("COMPLIANCE_CHUNK_CHARS", 8000))
        overlap = int(os.getenv("COMPLIANCE_CHUNK_OVERLAP", 800))
        n_results = int(os.getenv("COMPLIANCE_ZONE_N_RESULTS", 5))
        max_block_time = int(os.getenv("COMPLIANCE_MAX_BLOCK_SECONDS", 150))

        full_master_list = {"administrativo": [], "tecnico": [], "formatos": []}
        zone_reports = []

        for zone in search_zones:
            print(f"    [*] Procesando Zona: {zone['name']}")
            zone_start = time.time()

            context_zone = await self.smart_search(session_id, zone["query"], n_results=n_results)
            if not context_zone:
                zone_reports.append(
                    {"zone": zone["name"], "status": "fail", "reason": "RAG vacío", "metrics": {}}
                )
                continue

            chunks = self._split_context(context_zone, chunk_size, overlap)
            print(
                f"        [-] Bloques a procesar: {len(chunks)} "
                f"(Contexto: {len(context_zone)} chars)"
            )

            raw_zone_items, block_events = await self._map_zone_chunks(
                zone["name"],
                chunks,
                llm or self._get_llm(),
                max_block_time,
            )

            reduced_items, zone_metrics = self._reduce_zone_items(
                zone["name"],
                raw_zone_items,
                context_zone,
            )

            status, reason = self._apply_zone_gate(reduced_items, zone_metrics)
            status, reason = self._resolve_zone_status_for_block_timeouts(status, reason, block_events)

            zone_duration = time.time() - zone_start
            suspect_n = sum(1 for b in block_events if b.get("suspect_llm_timeout"))
            zone_reports.append(
                {
                    "zone": zone["name"],
                    "status": status,
                    "reason": reason,
                    "metrics": {
                        **zone_metrics,
                        "duration_sec": round(zone_duration, 2),
                        "context_chars": len(context_zone),
                        "blocks_count": len(chunks),
                        "block_events": block_events,
                        "blocks_suspect_timeout_count": suspect_n,
                    },
                }
            )

            if status != "fail":
                for cat in ["administrativo", "tecnico", "formatos"]:
                    full_master_list[cat].extend(
                        [it for it in reduced_items if it["categoria"] == cat]
                    )

        total_final = sum(len(v) for v in full_master_list.values())
        duration_total = time.time() - start_global

        print(f"\n🧾 [Resumen {zone_def['name']}]")
        print(f"    > Total ítems: {total_final}")
        for z in zone_reports:
            m = z.get("metrics", {})
            print(
                f"    - {z['zone']}: status={z['status']} "
                f"snip={m.get('snip_match_pct')}% page={m.get('page_match_pct')}% "
                f"total={m.get('total')} bloques={m.get('blocks_count')} "
                f"duración={m.get('duration_sec')}s"
            )

        print(f"\n⏱️ TIEMPO TOTAL {zone_def['name']}: {duration_total:.2f}s")

        zone_status = zone_reports[0]["status"] if zone_reports else "fail"
        if zone_status == "pass":
            top_status = "success"
        elif zone_status == "partial":
            top_status = "partial"
        else:
            top_status = "fail"
        return {
            "status": top_status,
            "data": full_master_list,
            "zones": zone_reports,
            "duration_sec": duration_total,
        }

    def _get_llm(self):
        from app.services.llm_service import LLMServiceClient

        if not hasattr(self, "llm_service") or self.llm_service is None:
            self.llm_service = LLMServiceClient()
        return self.llm_service

    def _zone_definition(self, key: str) -> Dict[str, str]:
        zones = {
            "admin": {
                "name": "ADMINISTATIVO/LEGAL",
                "query": (
                    "requisitos legales documentacion administrativa rfc acta constitutiva "
                    "representacion legal poderes notariales domicilio fiscal"
                ),
            },
            "tecnico": {
                "name": "TÉCNICO/OPERATIVO",
                "query": (
                    "especificaciones tecnicas suministro materiales experiencia equipo "
                    "personal capacidad técnica"
                ),
            },
            "formatos": {
                "name": "FORMATOS/ANEXOS",
                "query": (
                    "lista de anexos formatos obligatorios cartas bajo protesta "
                    "declaraciones escritos libres membretados"
                ),
            },
            "garantias": {
                "name": "GARANTÍAS/SEGUROS",
                "query": (
                    "fianzas polizas cheques certificado garantia cumplimiento "
                    "anticipo responsabilidad civil"
                ),
            },
        }
        return zones.get(key, zones["admin"])


async def run_zone(zone_key: str):
    session_id = "licitacion_opm-001-2026_maderas_chihuahiua"

    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    ctx_manager = MCPContextManager(memory)

    agent = AdminOnlyComplianceAgent(ctx_manager, zone_key=zone_key)
    try:
        start = time.time()
        result = await agent.process(session_id, input_data={})
        end = time.time()

        print("\n📊 Resultado resumido de la prueba de integración por zona:")
        print(f"    > Estado: {result.get('status')}")
        total_items = sum(len(v) for v in result.get("data", {}).values())
        print(f"    > Ítems totales en la zona: {total_items}")
        print(f"    > Tiempo total medido externamente: {end - start:.2f}s")
    finally:
        await memory.disconnect()


if __name__ == "__main__":
    selected_zone = (sys.argv[1] if len(sys.argv) > 1 else "admin").strip().lower()
    asyncio.run(run_zone(selected_zone))

