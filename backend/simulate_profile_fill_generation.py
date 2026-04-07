"""
Simulación de perfil mínimo para DataGap y ejecución del orquestador en modo generation_only.

Uso típico (desde el directorio backend, con DATABASE_URL y servicios LLM/Chroma según entorno):

  python simulate_profile_fill_generation.py --company-id co_xxx --session-id <uuid-sesion>

Requisitos:
- La sesión debe existir en PostgreSQL y contener en tasks_completed el resultado de Fase 1
  (p. ej. tarea ``economic_proposal``), porque generation_only no vuelve a ejecutar Analyst/Compliance/Economic.
- La empresa debe existir; se fusionan ``cedula_representante``, ``email`` y ``web`` en ``master_profile``
  con valores que pasan la validación de DataGapAgent (no placeholders).

Solo actualiza BD y sale (sin LLM):

  python simulate_profile_fill_generation.py --company-id co_xxx --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# Ejecutar como script local (no contenedor): raíz del paquete = directorio de este archivo
_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.memory.factory import MemoryAdapterFactory

DEFAULT_SIM_PROFILE = {
    "cedula_representante": "SIML123456789012",
    "email": "contacto.simulado@empresa-ejemplo.mx",
    "web": "https://empresa-ejemplo.mx",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--company-id", required=True, help="ID de empresa en companies (ej. co_...)")
    p.add_argument("--session-id", help="ID de sesión con Fase 1 ya persistida")
    p.add_argument("--dry-run", action="store_true", help="Solo mostrar fusión de perfil; no guardar ni orquestar")
    p.add_argument("--cedula", default=None, help="Sobrescribe cedula_representante simulada")
    p.add_argument("--email", default=None, help="Sobrescribe email simulado")
    p.add_argument("--web", default=None, help="Sobrescribe sitio web simulado")
    p.add_argument(
        "--output-json",
        default=None,
        help="Ruta opcional para volcar la respuesta del orquestador (UTF-8)",
    )
    return p.parse_args()


async def _main_async() -> int:
    args = _parse_args()
    profile_patch = {**DEFAULT_SIM_PROFILE}
    if args.cedula:
        profile_patch["cedula_representante"] = args.cedula
    if args.email:
        profile_patch["email"] = args.email
    if args.web:
        profile_patch["web"] = args.web

    memory = MemoryAdapterFactory.create_adapter()
    if memory is None:
        print("No se pudo crear el adaptador de memoria (¿DATABASE_URL?).", file=sys.stderr)
        return 1

    await memory.connect()
    try:
        company = await memory.get_company(args.company_id)
        if not company:
            print(f"Empresa no encontrada: {args.company_id}", file=sys.stderr)
            return 1

        master = dict(company.get("master_profile") or {})
        merged = {**master, **profile_patch}
        print("--- master_profile (fusión simulada) ---")
        print(json.dumps(merged, indent=2, ensure_ascii=False))

        if args.dry_run:
            print("\n(dry-run: no se escribió en BD ni se invocó el orquestador)")
            return 0

        company["master_profile"] = merged
        await memory.save_company(args.company_id, company)
        print(f"\n✓ Perfil actualizado para {args.company_id}")

        if not args.session_id:
            print("Sin --session-id no se ejecuta generation_only.", file=sys.stderr)
            return 0

        session = await memory.get_session(args.session_id)
        if not session:
            print(f"Sesión no encontrada: {args.session_id}", file=sys.stderr)
            return 1

        tasks = session.get("tasks_completed") or []
        has_economic = any(t.get("task") == "economic_proposal" for t in tasks)
        if not has_economic:
            print(
                "Aviso: la sesión no tiene tarea 'economic_proposal' en tasks_completed. "
                "EconomicWriter probablemente falle; ejecuta antes analysis_only o full.",
                file=sys.stderr,
            )

        mcp = MCPContextManager(memory_repository=memory)
        orch = OrchestratorAgent(context_manager=mcp)
        input_data = {
            "company_id": args.company_id,
            "company_data": {"mode": "generation_only"},
        }
        result = await orch.process(args.session_id, input_data)

        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"\nRespuesta del orquestador guardada en {args.output_json}")

        print("\n--- orchestrator_decision (resumen) ---")
        print(json.dumps(result.get("orchestrator_decision", {}), indent=2, ensure_ascii=False))
        print("\nstatus:", result.get("status"))
        return 0 if result.get("status") == "success" else 2
    finally:
        await memory.disconnect()


def main() -> None:
    raise SystemExit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
