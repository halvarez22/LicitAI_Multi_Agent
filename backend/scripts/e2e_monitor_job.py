"""
Dispara POST /agents/process y hace polling del job hasta COMPLETED/FAILED.
Imprime métricas: ítems compliance, documentos formats, archivos en disco.

Uso (desde el host, API en 8001):

  python scripts/e2e_monitor_job.py

Variables opcionales:
  E2E_API_BASE=http://127.0.0.1:8001/api/v1
  E2E_SESSION_ID=...
  E2E_POLL_SEC=20
  E2E_MAX_WAIT_SEC=7200
  E2E_OUTPUTS_HOST=C:/data/outputs
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _dig(d: Any, *keys: str, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _summarize_result(result: Optional[Dict[str, Any]]) -> None:
    if not result:
        print("  (sin result en job)")
        return
    status = result.get("status")
    print(f"  orchestrator status: {status}")
    data = result.get("data") or {}
    comp = data.get("compliance") or {}
    comp_data = comp.get("data") if isinstance(comp, dict) else {}
    if isinstance(comp_data, dict):
        summary = comp_data.get("audit_summary") or {}
        total = summary.get("total_items")
        zones = summary.get("zones") or []
        print(f"  compliance total_items (audit_summary): {total}")
        for z in zones:
            zn = z.get("zone", "?")
            st = z.get("status", "?")
            blks = (z.get("metrics") or {}).get("blocks_count")
            print(f"    zona {zn}: {st} | bloques_map={blks}")
    fmt = data.get("formats") or {}
    fmt_data = fmt.get("data") if isinstance(fmt, dict) else {}
    if isinstance(fmt_data, dict):
        print(f"  formats count (AgentOutput): {fmt_data.get('count')}")
        docs = fmt_data.get("documentos") or []
        print(f"  formats documentos en payload: {len(docs)}")
    tech = data.get("technical") or {}
    tdata = tech.get("data") if isinstance(tech, dict) else {}
    if isinstance(tdata, dict):
        paths = tdata.get("generated_paths") or tdata.get("paths") or []
        if paths:
            print(f"  technical paths: {len(paths)}")
    gen_state = result.get("generation_state")
    if gen_state:
        print(f"  generation_state keys: {list(gen_state.keys())[:12]}")


def _count_disk_outputs(session_id: str, root: Path) -> None:
    base = root / session_id
    if not base.is_dir():
        print(f"  disco: no existe {base}")
        return
    docx = list(base.rglob("*.docx"))
    xlsx = list(base.rglob("*.xlsx"))
    zipf = list(base.rglob("*.zip"))
    print(f"  disco {base}: {len(docx)} .docx, {len(xlsx)} .xlsx, {len(zipf)} .zip")


def main() -> int:
    base = os.getenv("E2E_API_BASE", "http://127.0.0.1:8001/api/v1").rstrip("/")
    session_id = os.getenv(
        "E2E_SESSION_ID", "la-51-gyn-051gyn025-n-8-2024_vigilancia"
    )
    poll = int(os.getenv("E2E_POLL_SEC", "25"))
    max_wait = int(os.getenv("E2E_MAX_WAIT_SEC", "7200"))
    outputs_host = os.getenv("E2E_OUTPUTS_HOST", "C:/data/outputs")

    payload = {
        "session_id": session_id,
        "company_id": os.getenv("E2E_COMPANY_ID", "co_e2e_monitor"),
        "company_data": {
            "mode": "full",
            "name": "E2E Monitor SA de CV",
            "master_profile": {
                "tipo": "moral",
                "razon_social": "E2E Monitor SA de CV",
                "rfc": "EMO123456ABC",
                "domicilio_fiscal": "Av. Monitoreo 100, León, Guanajuato, CP 37000",
                "representante_legal": "Representante Legal E2E",
            },
        },
        "resume_generation": False,
    }

    print(f"[E2E] POST {base}/agents/process session_id={session_id!r}")
    try:
        r = _post_json(f"{base}/agents/process", payload, timeout=180)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[E2E] HTTP {e.code}: {body[:800]}")
        return 1
    except Exception as e:
        print(f"[E2E] Error POST: {e}")
        return 1

    if not r.get("success"):
        print(f"[E2E] Respuesta no success: {r}")
        return 1

    job_id = (r.get("data") or {}).get("job_id")
    if not job_id:
        print(f"[E2E] Sin job_id: {r}")
        return 1

    print(f"[E2E] job_id={job_id} | polling cada {poll}s (tope {max_wait}s)…")
    t0 = time.time()
    last_stage = ""

    while time.time() - t0 < max_wait:
        try:
            st = _get_json(f"{base}/agents/jobs/{job_id}/status", timeout=60)
        except Exception as e:
            print(f"[E2E] poll error: {e}")
            time.sleep(poll)
            continue

        job = st.get("data") or {}
        status = job.get("status", "?")
        prog = job.get("progress") or {}
        stage = prog.get("stage", "")
        pct = prog.get("pct", "")
        msg = (prog.get("message") or "")[:120]
        if stage != last_stage or status in ("COMPLETED", "FAILED"):
            print(f"  [{int(time.time() - t0)}s] {status} | {stage} {pct}% {msg}")
            last_stage = stage

        if status == "COMPLETED":
            print("\n[E2E] ===== RESULTADO =====")
            _summarize_result(job.get("result"))
            _count_disk_outputs(session_id, Path(outputs_host))
            return 0

        if status == "FAILED":
            print("\n[E2E] ===== FAILED =====")
            print(f"  error: {job.get('error', '')[:2000]}")
            print(f"  forensic: {job.get('forensic_traceback')}")
            _summarize_result(job.get("result"))
            return 2

        time.sleep(poll)

    print(f"[E2E] Timeout tras {max_wait}s (último status visto arriba).")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
