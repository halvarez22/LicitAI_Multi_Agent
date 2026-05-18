"""
Limpia datos contaminados por captura económica incorrecta (documentos pedidos como PU).

- Sesión: elimina de pending_questions las entradas economic_price documentales (misma heurística que EconomicAgent).
- Empresa: elimina del catálogo filas source=chatbot_intake que sean documentales sin señal de partida.

Uso (desde carpeta backend, con DATABASE_URL cargada):
  python scripts/cleanup_economic_contamination.py --session-id vigilancia_issste --company-id <UUID>
  python scripts/cleanup_economic_contamination.py --session-id vigilancia_issste --company-id <UUID> --dry-run
  python scripts/cleanup_economic_contamination.py --list-contaminated-catalog
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.memory.factory import MemoryAdapterFactory
from app.services.economic_cotization_filters import (
    filter_pending_questions_economic_contamination,
    filter_company_catalog_contamination,
)


def _has_strict_anchor(q: dict) -> bool:
    """Fail-closed: documento + página + fragmento."""
    if not isinstance(q, dict):
        return False
    if str(q.get("type")) != "economic_price":
        return True
    oi = q.get("original_item")
    if not isinstance(oi, dict):
        return False
    src = str(oi.get("source") or "").strip()
    sn = str(oi.get("snippet") or "").strip()
    pg = oi.get("page") or oi.get("pagina")
    if not src or len(sn) < 12:
        return False
    try:
        return int(pg) >= 1
    except (TypeError, ValueError):
        return False


async def main() -> None:
    parser = argparse.ArgumentParser(description="Limpieza pending_questions + catálogo chatbot_intake contaminado.")
    parser.add_argument("--session-id", default="", help="ID de sesión (ej. vigilancia_issste)")
    parser.add_argument("--company-id", default="", help="ID de empresa cuyo catálogo limpiar")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar cambios, no persistir")
    parser.add_argument(
        "--list-contaminated-catalog",
        action="store_true",
        help="Listar empresas con entradas de catálogo contaminadas (chatbot_intake + documento)",
    )
    args = parser.parse_args()

    memory = MemoryAdapterFactory.create_adapter()
    if not memory:
        print("ERROR: No se pudo crear el adaptador de memoria.")
        sys.exit(1)
    if not await memory.connect():
        print("ERROR: No se pudo conectar a la base de datos (DATABASE_URL).")
        sys.exit(1)

    try:
        if args.list_contaminated_catalog:
            companies = await memory.get_companies()
            found = False
            for c in companies:
                cat = c.get("catalog") or []
                clean, removed = filter_company_catalog_contamination(cat)
                if removed:
                    found = True
                    print(f"\nEmpresa id={c.get('id')} name={c.get('name')!r}")
                    for r in removed:
                        print(f"  - eliminaría: {json.dumps(r, ensure_ascii=False)[:500]}")
            if not found:
                print("No hay entradas de catálogo contaminadas (chatbot_intake + patrón documental).")
            return

        if not args.session_id:
            print("ERROR: --session-id es obligatorio salvo --list-contaminated-catalog")
            sys.exit(1)

        state = await memory.get_session(args.session_id)
        if not state:
            print(f"ERROR: Sesión no encontrada: {args.session_id}")
            sys.exit(1)

        pending = list(state.get("pending_questions") or [])
        tmp_pending, removed_q = filter_pending_questions_economic_contamination(pending)
        removed_anchor = [q for q in tmp_pending if not _has_strict_anchor(q)]
        new_pending = [q for q in tmp_pending if _has_strict_anchor(q)]
        removed_q.extend(removed_anchor)
        idx = int(state.get("current_question_index") or 0)
        if new_pending:
            idx = min(idx, len(new_pending) - 1)
            idx = max(0, idx)
        else:
            idx = 0

        print(f"Sesión {args.session_id}:")
        print(f"  pending_questions: {len(pending)} -> {len(new_pending)} (eliminadas {len(removed_q)})")
        for r in removed_q:
            lbl = str(r.get("label", ""))[:120]
            print(f"    - {lbl}")

        patch: dict = {
            "pending_questions": new_pending,
            "current_question_index": idx,
        }
        if removed_q:
            uv = list(state.get("economic_unverified_suggestions") or [])
            for q in removed_q:
                uv.append(
                    {
                        "field": str(q.get("field") or ""),
                        "label": str(q.get("label") or "")[:280],
                        "reason": "cleanup_removed_unverified_or_documental",
                        "source": "cleanup_economic_contamination",
                    }
                )
            patch["economic_unverified_suggestions"] = uv[-400:]
        # Limpiar hints de pausa económica si quedó estado inconsistente
        if "last_economic_waiting_hints" in state:
            patch["last_economic_waiting_hints"] = None
        if removed_q:
            lod = state.get("last_orchestrator_decision")
            if isinstance(lod, dict) and lod.get("stop_reason") == "ECONOMIC_GAP":
                patch["last_orchestrator_decision"] = None

        if args.dry_run:
            print("\n[DRY-RUN] No se escribió nada.")
        else:
            merged = dict(state)
            merged.update(patch)
            await memory.save_session(args.session_id, merged)
            print("\nSesión actualizada.")

        if not args.company_id:
            print(
                "\nCatálogo: omitido (sin --company-id). "
                "Usa --list-contaminated-catalog para ver IDs y pasa --company-id."
            )
            return

        company = await memory.get_company(args.company_id)
        if not company:
            print(f"ERROR: Empresa no encontrada: {args.company_id}")
            sys.exit(1)

        cat = list(company.get("catalog") or [])
        new_cat, removed_c = filter_company_catalog_contamination(cat)
        print(f"\nEmpresa {args.company_id}:")
        print(f"  catálogo: {len(cat)} -> {len(new_cat)} (eliminadas {len(removed_c)})")
        for r in removed_c:
            d = str(r.get("description", ""))[:120]
            print(f"    - {d} (price_base={r.get('price_base')})")

        if args.dry_run:
            print("\n[DRY-RUN] Catálogo no modificado.")
        else:
            company["catalog"] = new_cat
            await memory.save_company(args.company_id, company)
            print("Catálogo actualizado.")

    finally:
        await memory.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
