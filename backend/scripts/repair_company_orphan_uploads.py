"""
Repara metadata de documentos empresariales cuyo archivo existe en disco
pero fue borrado de Postgres por condiciones de carrera en cargas concurrentes.

Uso:
  python scripts/repair_company_orphan_uploads.py co_1780078972797
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.routes.sessions import get_repository
from app.api.v1.routes.companies import _schedule_company_analysis

UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    os.path.join("/data", "uploads")
    if os.path.exists("/.dockerenv")
    else str(ROOT / "data" / "uploads"),
)


def _infer_doc_title(filename: str) -> Optional[str]:
    lower = filename.lower()
    if "logo" in lower or lower.endswith((".png", ".jpg", ".jpeg", ".webp")) and "cif" not in lower and "constitutiva" not in lower and "acta" not in lower:
        return "LOGOTIPO"
    if "cif" in lower or "constancia" in lower or "csf" in lower:
        return "CIF (SAT)"
    if "constitutiva" in lower or "acta" in lower:
        return "Acta Constitutiva"
    if "ine" in lower or "identificacion" in lower or "identificación" in lower:
        return "INE / Identificación"
    if "poder" in lower:
        return "Poder Notarial"
    return None


async def repair_company_orphan_uploads(company_id: str) -> Dict[str, int]:
    repo = await get_repository()
    try:
        company = await repo.get_company(company_id)
        if not company:
            raise SystemExit(f"Empresa no encontrada: {company_id}")

        prefix = f"comp_{company_id}_"
        orphans = [
            name
            for name in os.listdir(UPLOAD_DIR)
            if name.startswith(prefix)
        ]
        existing = company.get("docs") or {}
        existing_paths = {
            (meta or {}).get("path")
            for meta in existing.values()
            if isinstance(meta, dict)
        }

        attached = 0
        skipped = 0
        for orphan in sorted(orphans):
            full_path = os.path.join(UPLOAD_DIR, orphan)
            if full_path in existing_paths:
                skipped += 1
                continue

            doc_title = _infer_doc_title(orphan)
            if not doc_title:
                print(f"[?] Sin título inferido, omitido: {orphan}")
                skipped += 1
                continue

            current = existing.get(doc_title)
            if current and current.get("path") and os.path.exists(current.get("path", "")):
                skipped += 1
                continue

            meta = {
                "name": orphan.split("_", 3)[-1] if "_" in orphan else orphan,
                "path": full_path,
                "date": "NOW",
                "preview": None,
                "status": "UPLOADED",
            }
            updated = await repo.patch_company_state(
                company_id,
                docs_patch={doc_title: meta},
            )
            if updated:
                attached += 1
                print(f"[+] Re-adjuntado {doc_title}: {orphan}")
            else:
                skipped += 1

        return {"attached": attached, "skipped": skipped, "orphans_seen": len(orphans)}
    finally:
        await repo.disconnect()


async def _main(company_id: str) -> Dict[str, int]:
    stats = await repair_company_orphan_uploads(company_id)
    if stats.get("attached", 0) > 0:
        print(f"[*] Disparando análisis background para {company_id}...")
        await _schedule_company_analysis(company_id)
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python scripts/repair_company_orphan_uploads.py <company_id>")
    company_id = sys.argv[1]
    stats = asyncio.run(_main(company_id))
    print(stats)


if __name__ == "__main__":
    main()
