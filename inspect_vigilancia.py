import json, sys

sys.stdout.reconfigure(encoding='utf-8')

with open("docs/_job_vigilancia_20260402.json", encoding="utf-8") as f:
    d = json.load(f)

compliance = d["data"]["result"]["data"]["compliance"]
cdata = compliance.get("data", {})
admin    = cdata.get("administrativo", []) if isinstance(cdata, dict) else []
tecnico  = cdata.get("tecnico", []) if isinstance(cdata, dict) else []
formatos = cdata.get("formatos", []) if isinstance(cdata, dict) else []

print(f"=== CARDINALIDAD ===")
print(f"administrativo: {len(admin)}  |  tecnico: {len(tecnico)}  |  formatos: {len(formatos)}")

tier_count = {}
for item in admin:
    t = item.get("match_tier", "unknown")
    tier_count[t] = tier_count.get(t, 0) + 1
print(f"Tier en administrativo: {tier_count}")

# Palabras clave tecnicas
TECH_KW = [
    "personal", "elemento", "equipo", "herramienta", "uniforme", "capacitaci",
    "supervisor", "operativo", "limpieza", "vigilancia", "turno", "ronda",
    "ruta", "arma", "guardia", "custodia", "material", "quimico", "maquinaria",
    "frecuencia", "horario", "actividad", "protocol", "procedimiento", "recorrido",
    "bitacora", "supervision", "checklist", "armado", "radio", "patrulla",
    "riesgo", "incidente", "contingencia", "vehiculo",
    "propuesta tecnica", "metodologia", "organigrama", "mantenimiento"
]

print("\n=== Candidatos TECNICOS en 'administrativo' ===")
hits = []
for item in admin:
    nombre = (item.get("nombre") or "").lower()
    desc   = (item.get("descripcion") or "").lower()
    snip   = (item.get("snippet") or "").lower()
    combined = nombre + " " + desc + " " + snip
    if any(kw in combined for kw in TECH_KW):
        hits.append(item)

for i, item in enumerate(hits, 1):
    nombre = item.get("nombre", "N/A")
    desc   = (item.get("descripcion") or "")[:100]
    tier   = item.get("match_tier", "?")
    ev     = item.get("evidence_match", "?")
    page   = item.get("page", "?")
    print(f"{i}. [{tier} | ev:{ev} | p.{page}] {nombre}")
    print(f"   {desc}")
    print()

print(f"Total tecnicos probables en administrativo: {len(hits)} / {len(admin)}")

print("\n=== Items 'formatos' ===")
for item in formatos:
    nombre = item.get("nombre", "N/A")
    tier   = item.get("match_tier", "?")
    ev     = item.get("evidence_match", "?")
    desc   = (item.get("descripcion") or "")[:80]
    print(f"  [{tier} | ev:{ev}] {nombre} -- {desc}")
