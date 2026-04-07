"""
E2E: tres bases reales desde `bases_licitai_prueba_inteligencia`.

Flujo: crear sesión → subir PDF → POST /agents/process → polling
GET /agents/jobs/{job_id}/status hasta COMPLETED o FAILED.

La API devuelve 202 con job_id (proceso en background); este script es el flujo correcto
para contrastar con scripts antiguos que esperaban respuesta síncrona.

Variables de entorno:
  E2E_API_URL   (default http://127.0.0.1:8001/api/v1)
  E2E_BASE_DIR  (ruta a la carpeta con los PDF)
  E2E_MAX_FILES (1–3, default 3)
  E2E_POLL_SEC  (default 5)
  E2E_JOB_TIMEOUT_SEC (default 7200 por archivo)

Uso (desde host con backend en 8001):
  python scripts/e2e_bases_inteligencia.py
  python scripts/e2e_bases_inteligencia.py   # con E2E_MAX_FILES=1 solo el primero
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = Path(__file__).resolve().parent / "e2e_inteligencia_report.json"

API_BASE = os.environ.get("E2E_API_URL", "http://127.0.0.1:8001/api/v1").rstrip("/")
DEFAULT_BASE_DIR = (
    r"C:\LicitAI_Multi_Agent\bases y convocatorias de prueba\bases_licitai_prueba_inteligencia"
)
BASE_DIR = Path(os.environ.get("E2E_BASE_DIR", DEFAULT_BASE_DIR))
MAX_FILES = max(1, min(3, int(os.environ.get("E2E_MAX_FILES", "3"))))
POLL_SEC = max(2, int(os.environ.get("E2E_POLL_SEC", "5")))
JOB_TIMEOUT = int(os.environ.get("E2E_JOB_TIMEOUT_SEC", "7200"))

# Tres PDF elegidos: tamaño manejable + perfiles distintos (obras/iluminación, vigilancia, ISSSTE).
E2E_PDFS = [
    {
        "label": "iluminacion_t5_2019",
        "file": "T5 BASES DD-PM-ILUM-2019-SUM CAMBIO ILUMINACION.pdf",
        "nota": "Bases técnicas relativamente livianas (~300 KB).",
    },
    {
        "label": "vigilancia_la51_2024",
        "file": "LA-51-GYN-051GYN025-N-8-2024 VIGILANCIA.pdf",
        "nota": "Servicio de vigilancia; PDF nativo ~890 KB.",
    },
    {
        "label": "issste_limpieza_2024",
        "file": "BASES SERVICIO LIMPIEZA 2024 ISSSTE BCS.pdf",
        "nota": "Sector salud / ISSSTE; ~540 KB.",
    },
]


def _slim_compliance(compliance: dict | None) -> dict:
    if not isinstance(compliance, dict):
        return {}
    data = compliance.get("data") or {}
    out = {
        "status": compliance.get("status"),
        "n_admin": len(data.get("administrativo") or []),
        "n_tecnico": len(data.get("tecnico") or []),
        "n_formatos": len(data.get("formatos") or []),
    }
    zones = (compliance.get("data") or {}).get("audit_summary") or {}
    if isinstance(zones, dict) and zones.get("zones"):
        out["audit_zones"] = zones.get("zones")
    return out


def _slim_result(full: dict | None) -> dict:
    if not isinstance(full, dict):
        return {}
    inner = full.get("data")
    if not isinstance(inner, dict):
        return {"orchestrator_status": full.get("status"), "raw_keys": list(full.keys())}
    analysis = inner.get("analysis") or {}
    compliance = inner.get("compliance") or {}
    economic = inner.get("economic") or {}
    ap = (
        analysis.get("data")
        if isinstance(analysis, dict) and isinstance(analysis.get("data"), dict)
        else (analysis if isinstance(analysis, dict) else {})
    )
    reqs = ap.get("requisitos_filtro")
    n_req = len(reqs) if isinstance(reqs, list) else None
    part = ap.get("requisitos_participacion")
    n_part = len(part) if isinstance(part, list) else None
    reglas = ap.get("reglas_economicas")
    n_reglas_llenas = (
        len([v for v in reglas.values() if isinstance(v, str) and v.strip() and v != "No especificado"])
        if isinstance(reglas, dict)
        else None
    )
    alc = ap.get("alcance_operativo")
    n_alcance = len(alc) if isinstance(alc, list) else None
    dt = ap.get("datos_tabulares") if isinstance(ap.get("datos_tabulares"), dict) else {}
    return {
        "orchestrator_status": full.get("status"),
        "chatbot_preview": (full.get("chatbot_message") or "")[:400],
        "requisitos_participacion_count": n_part,
        "requisitos_filtro_count": n_req,
        "reglas_economicas_campos_llenos": n_reglas_llenas,
        "alcance_operativo_filas": n_alcance,
        "datos_tabulares_line_items": dt.get("line_items_count"),
        "datos_tabulares_alerta": (dt.get("alerta_faltante") or "")[:200] or None,
        "compliance": _slim_compliance(compliance if isinstance(compliance, dict) else None),
        "economic_has_alerts": bool(
            isinstance(economic, dict)
            and (economic.get("data") or {}).get("analisis_precios", {}).get("alertas")
        ),
    }


def _poll_job(session: requests.Session, job_id: str) -> dict:
    deadline = time.time() + JOB_TIMEOUT
    last_progress = None
    transient_errors = 0
    max_transient = 24  # ~2 min de reintentos si el worker cierra el socket entre polls

    while time.time() < deadline:
        try:
            r = session.get(f"{API_BASE}/agents/jobs/{job_id}/status", timeout=60)
        except requests.RequestException as e:
            transient_errors += 1
            if transient_errors > max_transient:
                return {"ok": False, "poll_network_error": repr(e), "transient_errors": transient_errors}
            print(f"    [poll reintento {transient_errors}/{max_transient}] {e!s}")
            time.sleep(POLL_SEC)
            continue

        transient_errors = 0
        if r.status_code != 200:
            return {"poll_error": r.status_code, "body": r.text[:1500]}
        body = r.json()
        data = body.get("data") or {}
        status = data.get("status")
        prog = data.get("progress") or {}
        if prog != last_progress:
            last_progress = prog
            print(f"    [job {job_id[:8]}…] {status} | {prog.get('message', '')}")
        if status == "COMPLETED":
            return {"ok": True, "job": data}
        if status == "FAILED":
            return {"ok": False, "job": data, "error": data.get("error"), "trace": data.get("forensic_traceback")}
        time.sleep(POLL_SEC)
    return {"ok": False, "timeout_sec": JOB_TIMEOUT}


def _run_one(session: requests.Session, label: str, pdf_name: str) -> dict:
    pdf_path = BASE_DIR / pdf_name
    if not pdf_path.is_file():
        return {"label": label, "error": f"no existe: {pdf_path}"}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = f"e2e_intel_{label}_{stamp}"
    cr = session.post(
        f"{API_BASE}/sessions/create",
        params={"name": safe_name},
        timeout=30,
    )
    if cr.status_code != 200:
        return {"label": label, "error": f"create session HTTP {cr.status_code}", "body": cr.text[:500]}
    cj = cr.json()
    if not cj.get("success"):
        return {"label": label, "error": "create session failed", "body": cj}
    session_id = (cj.get("data") or {}).get("session_id")
    if not session_id:
        return {"label": label, "error": "sin session_id"}

    with open(pdf_path, "rb") as f:
        up = session.post(
            f"{API_BASE}/upload/upload",
            files={"file": (pdf_name, f, "application/pdf")},
            data={"session_id": session_id},
            timeout=600,
        )
    if up.status_code != 200:
        return {"label": label, "session_id": session_id, "error": f"upload HTTP {up.status_code}", "body": up.text[:800]}
    uj = up.json()
    if not uj.get("success"):
        return {"label": label, "session_id": session_id, "error": "upload failed", "body": uj}

    pr = session.post(
        f"{API_BASE}/agents/process",
        json={
            "session_id": session_id,
            "company_id": None,
            "company_data": {"mode": "analysis_only", "name": "E2E_Inteligencia"},
        },
        timeout=60,
    )
    if pr.status_code not in (200, 202):
        return {
            "label": label,
            "session_id": session_id,
            "error": f"agents/process HTTP {pr.status_code}",
            "body": pr.text[:1200],
        }
    pj = pr.json()
    job_id = (pj.get("data") or {}).get("job_id")
    if not job_id:
        return {"label": label, "session_id": session_id, "error": "sin job_id en respuesta", "body": pj}

    poll_out = _poll_job(session, job_id)
    if not poll_out.get("ok"):
        return {
            "label": label,
            "session_id": session_id,
            "job_id": job_id,
            "pdf": pdf_name,
            "poll": poll_out,
        }

    job = poll_out["job"]
    result = job.get("result") or {}
    return {
        "label": label,
        "session_id": session_id,
        "job_id": job_id,
        "pdf": pdf_name,
        "pdf_mb": round(pdf_path.stat().st_size / (1024 * 1024), 2),
        "outcome": "COMPLETED",
        "summary": _slim_result(result),
        "full_result_stored": False,
    }


def main() -> int:
    report: dict = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_base": API_BASE,
        "base_dir": str(BASE_DIR),
        "max_files": MAX_FILES,
        "runs": [],
    }
    print(f"[E2E] API={API_BASE}  BASE_DIR={BASE_DIR}  MAX_FILES={MAX_FILES}")

    if not BASE_DIR.is_dir():
        print(f"[E2E] ERROR: carpeta no existe: {BASE_DIR}", file=sys.stderr)
        report["fatal"] = "base_dir missing"
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 1

    session = requests.Session()
    try:
        h = session.get(f"{API_BASE}/health", timeout=15)
        report["health_status"] = h.status_code
        print(f"[E2E] health: {h.status_code}")
        if h.status_code != 200:
            print("[E2E] Abort: health no OK", file=sys.stderr)
            REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            return 1
    except requests.RequestException as e:
        print(f"[E2E] ERROR health: {e}", file=sys.stderr)
        report["fatal"] = repr(e)
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 1

    try:
        for spec in E2E_PDFS[:MAX_FILES]:
            print(f"\n[E2E] === {spec['label']} === {spec['file']}")
            print(f"       {spec['nota']}")
            t0 = time.time()
            try:
                run = _run_one(session, spec["label"], spec["file"])
            except requests.RequestException as e:
                run = {"label": spec["label"], "error": "request_exception", "detail": repr(e)}
            run["elapsed_sec"] = round(time.time() - t0, 2)
            report["runs"].append(run)
            if run.get("summary"):
                print(f"    resumen: {json.dumps(run['summary'], ensure_ascii=False)[:500]}…")
            elif run.get("poll"):
                print(f"    poll: {run['poll']}")
            elif run.get("error"):
                print(f"    error: {run['error']}")
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[E2E] Reporte: {REPORT_PATH}")

    failed = any(
        bool(r.get("error"))
        or (isinstance(r.get("poll"), dict) and not r["poll"].get("ok"))
        for r in report["runs"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
