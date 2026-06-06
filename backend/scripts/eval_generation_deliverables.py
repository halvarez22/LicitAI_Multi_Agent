"""
Evaluación universal de generación: inventario «generar» vs archivos materializados.

Uso:
  PYTHONPATH=. python scripts/eval_generation_deliverables.py <session_id>

No hardcodea licitación: lee panel consolidado + disco /data/outputs/<session_id>.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from app.api.deps import get_connected_memory
from app.services.document_candidate_list_service import build_formats_panel_consolidated


def _norm(s: str) -> str:
    t = re.sub(r"\s+", " ", str(s or "").strip().lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _collect_expected_generar(panel: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for bk in (
        "sobre_1_tecnico",
        "sobre_2_economico",
        "requisitos_legales",
        "otros_requisitos_criticos",
    ):
        for row in panel.get(bk) or []:
            if str(row.get("tipo_accion_final") or row.get("tipo") or "") != "generar":
                continue
            name = str(row.get("nombre_canonico") or row.get("nombre") or "").strip()
            if name:
                out.append(name)
    return out


def _scan_output_files(session_id: str) -> List[Path]:
    roots = [
        Path("/data/outputs") / session_id,
        Path("scratch/outputs") / session_id,
    ]
    files: List[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".docx", ".pdf", ".xlsx"):
                files.append(p)
    return files


def _load_indice(session_id: str) -> List[Dict[str, Any]]:
    for base in (Path("/data/outputs") / session_id, Path("scratch/outputs") / session_id):
        path = base / "_compranet_validated" / "INDICE_ENTREGA.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return list(data.get("files") or [])
            except Exception:
                return []
    return []


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    panel = await build_formats_panel_consolidated(mem, session_id, state)
    expected = _collect_expected_generar(panel)
    files = _scan_output_files(session_id)
    gen = state.get("generation_state") or {}
    jobs = {str(j.get("id")): str(j.get("status")) for j in (gen.get("jobs") or []) if isinstance(j, dict)}

    print(f"=== Evaluación generación | sesión: {session_id} ===\n")
    print("Cola:", jobs)
    print(f"\nEsperados (panel generar): {len(expected)}")
    for i, name in enumerate(expected, 1):
        print(f"  {i:02d}. {name[:100]}")

    indice = _load_indice(session_id)
    print(f"\nÍndice entrega (_compranet_validated): {len(indice)} archivos")
    for ent in indice:
        print(
            f"  - [{ent.get('sobre')}] {ent.get('nombre_entrega')} "
            f"({ent.get('materialization_route') or 'n/d'})"
        )

    print(f"\nArchivos en disco (scan): {len(files)}")
    for p in sorted(files):
        rel = p.as_posix().split(session_id)[-1].lstrip("/")
        print(f"  - {rel}")

    desc_path = None
    for base in (Path("/data/outputs") / session_id, Path("scratch/outputs") / session_id):
        candidate = base / "descriptions.json"
        if candidate.is_file():
            desc_path = candidate
            break
    if desc_path:
        try:
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
            print(f"\ndescriptions.json: {len(desc) if isinstance(desc, list) else len(desc.keys())} entradas")
        except Exception as exc:
            print(f"\ndescriptions.json: no legible ({exc})")

    print("\n--- Brecha (heurística por tokens, no hardcode) ---")
    file_tokens: Set[str] = set()
    for p in files:
        file_tokens.update(_norm(p.stem).split())
    missing_like: List[str] = []
    for name in expected:
        tokens = [t for t in _norm(name).split() if len(t) > 3]
        if tokens and not any(t in file_tokens for t in tokens[:4]):
            missing_like.append(name)
    if missing_like:
        print(f"Pendientes probables ({len(missing_like)}):")
        for m in missing_like[:20]:
            print(f"  ? {m[:90]}")
    else:
        print("Cada ítem esperado comparte tokens con algún archivo (revisión manual aún recomendada).")

    await mem.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
