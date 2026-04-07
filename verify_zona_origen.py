"""
verify_zona_origen.py
Descarga el job más reciente y verifica que:
  1. Los ítems llevan zona_origen definido
  2. Ítems con zona_origen=TÉCNICO/OPERATIVO y categoria=administrativo existen
     (la "fuga" ya rastreada, ahora observable)

Uso:
  python verify_zona_origen.py <job_id>
  python verify_zona_origen.py   (detecta job_id del último reporte)
"""
import sys
import json
import requests
from pathlib import Path
from collections import defaultdict

API_BASE = "http://localhost:8001/api/v1"
DOCS_DIR = Path(__file__).parent / "licitaciones-ai" / "docs"


def latest_job_id() -> str:
    reports = sorted(DOCS_DIR.glob("corridas_prueba_inteligencia_*.json"), reverse=True)
    if not reports:
        raise FileNotFoundError("No hay reportes de corrida en docs/")
    data = json.loads(reports[0].read_text(encoding="utf-8"))
    job_id = None
    for case in data.get("cases", []):
        jid = case.get("steps", {}).get("job_id")
        if jid:
            job_id = jid
    if not job_id:
        raise ValueError(f"No se encontró job_id en {reports[0].name}")
    print(f"Reporte usado: {reports[0].name}")
    return job_id


def fetch_job(job_id: str) -> dict:
    r = requests.get(f"{API_BASE}/agents/jobs/{job_id}/status", timeout=30)
    r.raise_for_status()
    return r.json().get("data", {})


def count_zona(items: list) -> dict:
    by_zona = defaultdict(list)
    for it in items:
        zo = it.get("zona_origen") or "AUSENTE"
        by_zona[zo].append(it.get("categoria", "?"))
    return dict(by_zona)


def main():
    job_id = sys.argv[1] if len(sys.argv) > 1 else latest_job_id()
    print(f"Verificando job: {job_id}")

    job = fetch_job(job_id)
    status = job.get("status")
    print(f"Estado: {status}")
    if status != "COMPLETED":
        print("⚠️  Job aún no COMPLETED — reintenta cuando termine.")
        return

    result = job.get("result", {})
    cdata = (result.get("data") or {}).get("compliance", {}).get("data", {})

    all_items = []
    for cat in ("administrativo", "tecnico", "formatos"):
        for it in (cdata.get(cat) or []):
            if isinstance(it, dict):
                it.setdefault("_lista", cat)
                all_items.append(it)

    total = len(all_items)
    with_zona = [it for it in all_items if it.get("zona_origen")]
    sin_zona  = [it for it in all_items if not it.get("zona_origen")]

    print(f"\n{'='*55}")
    print(f"  Total ítems           : {total}")
    print(f"  Con zona_origen       : {len(with_zona)}")
    print(f"  Sin zona_origen       : {len(sin_zona)}  {'✅ OK' if not sin_zona else '❌ Pendiente rebuild'}")
    print(f"{'='*55}")

    if with_zona:
        print("\n  Tabla zona_origen × categoria_final:")
        print(f"  {'zona_origen':<35} {'categoria':<18} {'N':>4}")
        print(f"  {'-'*35} {'-'*18} {'-'*4}")
        crosstab = defaultdict(lambda: defaultdict(int))
        for it in with_zona:
            zo  = it.get("zona_origen", "?")
            cat = it.get("categoria", "?")
            crosstab[zo][cat] += 1
        for zo, cats in sorted(crosstab.items()):
            for cat, n in sorted(cats.items()):
                flag = " ⚠️  (fuga)" if "TÉCNICO" in zo and cat == "administrativo" else ""
                print(f"  {zo:<35} {cat:<18} {n:>4}{flag}")

        # Ejemplo concreto de ítem técnico con zona_origen técnica
        ejemplos = [
            it for it in with_zona
            if "TÉCNICO" in (it.get("zona_origen") or "")
            and it.get("categoria") == "administrativo"
        ]
        if ejemplos:
            print(f"\n  Ejemplo de ítem con zona_origen=TÉCNICO/OPERATIVO → categoria=administrativo:")
            ej = ejemplos[0]
            print(f"    id          : {ej.get('id')}")
            print(f"    nombre      : {ej.get('nombre')}")
            print(f"    zona_origen : {ej.get('zona_origen')}")
            print(f"    categoria   : {ej.get('categoria')}")
            print(f"    match_tier  : {ej.get('match_tier')}")
            desc = (ej.get('descripcion') or '')[:100]
            print(f"    descripcion : {desc}")
    else:
        print("\n  ❌ Ningún ítem tiene zona_origen — el contenedor no fue reconstruido.")

    print(f"\n{'='*55}")
    dump_path = DOCS_DIR / "_job_zona_origen_verify.json"
    dump_path.write_text(
        json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Dump guardado en: {dump_path.name}")


if __name__ == "__main__":
    main()
