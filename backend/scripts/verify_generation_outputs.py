"""
Verificacion de artefactos en disco para el Entregable 2 (propuesta tecnica + economica).

Tras una generacion exitosa (UI o simulate_profile_fill_generation.py), comprueba que existan
las carpetas y archivos que escriben TechnicalWriter, EconomicWriter y (opcional) FormatsAgent.

Uso (desde el directorio backend):

  python scripts/verify_generation_outputs.py --session-folder "nombre_carpeta_bajo_outputs"

En host con Docker y volumen ./data:/data:

  python scripts/verify_generation_outputs.py --session-folder "mi_sesion" --root ../data/outputs

Salida: codigo 0 si pasa el nivel solicitado; distinto de 0 si falta algo critico.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Tuple

TECH_DIR = "1.propuesta tecnica"
ECON_DIR = "2.propuesta_economica"
ADMIN_DIR = "3.documentos administrativos"

ECONOMIC_REQUIRED = (
    "TABLA_PRECIOS_UNITARIOS.xlsx",
    "ANEXO_AE_PROPUESTA_ECONOMICA.docx",
    "CARTA_COMPROMISO_PRECIOS.docx",
)


def _list_files(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def check_economic(base: Path) -> Tuple[bool, List[str]]:
    d = base / ECON_DIR
    msgs: List[str] = []
    if not d.is_dir():
        return False, [f"Falta carpeta: {d}"]
    ok = True
    for name in ECONOMIC_REQUIRED:
        p = d / name
        if not p.is_file():
            ok = False
            msgs.append(f"Falta archivo economico: {p}")
        else:
            msgs.append(f"OK economico: {name} ({p.stat().st_size} bytes)")
    return ok, msgs


def check_technical(base: Path, min_docx: int) -> Tuple[bool, List[str]]:
    d = base / TECH_DIR
    msgs: List[str] = []
    if not d.is_dir():
        return False, [f"Falta carpeta tecnica: {d}"]
    docx = list(d.rglob("*.docx"))
    if len(docx) < min_docx:
        return False, msgs + [f"Propuesta tecnica: se esperaban al menos {min_docx} .docx, hay {len(docx)}"]
    msgs.append(f"OK tecnico: {len(docx)} archivo(s) .docx")
    return True, msgs


def check_admin(base: Path, min_docx: int) -> Tuple[bool, List[str]]:
    d = base / ADMIN_DIR
    msgs: List[str] = []
    if not d.is_dir():
        return False, [f"Falta carpeta administrativa: {d}"]
    docx = list(d.rglob("*.docx"))
    if min_docx > 0 and len(docx) < min_docx:
        return False, msgs + [f"Formatos admin: se esperaban al menos {min_docx} .docx, hay {len(docx)}"]
    msgs.append(f"OK admin/formatos: {len(docx)} archivo(s) .docx")
    return True, msgs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--session-folder",
        required=True,
        help="Nombre de carpeta bajo outputs (session_state.name o session_id segun agentes).",
    )
    p.add_argument(
        "--root",
        default=os.environ.get("GENERATION_OUTPUTS_ROOT", "/data/outputs"),
        help="Raiz de salidas (default: GENERATION_OUTPUTS_ROOT o /data/outputs).",
    )
    p.add_argument(
        "--level",
        choices=("economic", "full"),
        default="economic",
        help="economic: solo los 3 archivos de propuesta economica. "
        "full: economico + al menos 1 docx tecnico + carpeta admin con al menos 1 docx.",
    )
    args = p.parse_args()

    base = Path(args.root) / args.session_folder
    if not base.is_dir():
        print(f"[FAIL] No existe la carpeta de sesion: {base}", file=sys.stderr)
        return 2

    all_ok = True
    print(f"[INFO] Verificando: {base}")

    ok_e, lines = check_economic(base)
    for line in lines:
        print(line)
    all_ok = all_ok and ok_e

    if args.level == "full":
        ok_t, lines = check_technical(base, min_docx=1)
        for line in lines:
            print(line)
        all_ok = all_ok and ok_t

        ok_a, lines = check_admin(base, min_docx=1)
        for line in lines:
            print(line)
        all_ok = all_ok and ok_a

    total = len(_list_files(base))
    print(f"[INFO] Total archivos bajo sesion: {total}")

    if all_ok:
        print("[OK] Verificacion Entregable 2 superada (nivel %s)." % args.level)
        return 0
    print("[FAIL] Verificacion incompleta.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
