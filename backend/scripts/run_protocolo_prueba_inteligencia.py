"""
Ejecuta el protocolo operativo por cada archivo en la carpeta de prueba:
crear sesión → upload → process → agents/process.

Uso:
  set LICITAI_PRUEBA_INTELIGENCIA_DIR=C:\\path\\to\\folder
  python scripts/run_protocolo_prueba_inteligencia.py

Salida:
  docs/corridas_prueba_inteligencia_<timestamp>.json (relativo al repo licitaciones-ai)

Defaults del harness: piso ~2h de espera máxima al job (PDFs densos). Smoke rápido:
  $env:E2E_ORCH_TIMEOUT_MIN_SEC="900"

Reanudar sin re-subir (misma sesión en Postgres), si el backend conserva la sesión:
  $env:E2E_RESUME_SESSION_ID="<session_id del reporte JSON>"
  (resume_generation=true se envía automáticamente al usar reutilización de sesión)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

DEFAULT_DIR = (
    r"C:\LicitAI_Multi_Agent\bases y convocatorias de prueba\bases_licitai_prueba_inteligencia"
)

API_BASE = os.environ.get("E2E_API_URL", "http://localhost:8001/api/v1")
# Base para cálculo adaptativo (tamaño de archivo). El tope efectivo lo marcan MIN/MAX.
ORCH_TIMEOUT = int(os.environ.get("E2E_ORCH_TIMEOUT_SEC", "2400"))
UPLOAD_TIMEOUT = int(os.environ.get("E2E_UPLOAD_TIMEOUT_SEC", "300"))
PROCESS_TIMEOUT = int(os.environ.get("E2E_PROCESS_TIMEOUT_SEC", "900"))
ORCH_TIMEOUT_PER_MB = int(os.environ.get("E2E_ORCH_TIMEOUT_PER_MB_SEC", "20"))
# Piso/techo del tiempo máximo de polling hasta COMPLETED/FAILED (no afecta jobs que terminan antes).
ORCH_TIMEOUT_MIN = int(os.environ.get("E2E_ORCH_TIMEOUT_MIN_SEC", "7200"))
ORCH_TIMEOUT_MAX = int(os.environ.get("E2E_ORCH_TIMEOUT_MAX_SEC", "10800"))
E2E_POLL_INTERVAL_SEC = float(os.environ.get("E2E_POLL_INTERVAL_SEC", "5"))
E2E_PROCESS_ACCEPT_TIMEOUT_SEC = int(os.environ.get("E2E_PROCESS_ACCEPT_TIMEOUT_SEC", "120"))


def _env_bool(name: str, default: bool = False) -> bool:
    """Lee variables de entorno tipo flag (1/true/yes/on)."""
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _slug(name: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "_", name.lower().replace(" ", "_"))
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:max_len] or "ses")[:63]


def _calc_orch_timeout_sec(file_size_bytes: int) -> int:
    """Calcula timeout adaptativo por archivo usando tamaño como proxy de latencia."""
    size_mb = max(file_size_bytes / (1024 * 1024), 0.0)
    adaptive = int(ORCH_TIMEOUT + (size_mb * ORCH_TIMEOUT_PER_MB))
    return max(ORCH_TIMEOUT_MIN, min(adaptive, ORCH_TIMEOUT_MAX))


def _poll_job_until_done(
    job_id: str,
    max_wait_sec: int,
    poll_interval: float = E2E_POLL_INTERVAL_SEC,
) -> dict:
    """
    Consulta GET /agents/jobs/{job_id}/status hasta COMPLETED o FAILED.

    Retorna el dict `data` de GenericResponse (estado Redis del job).
    Lanza requests.Timeout si se supera max_wait_sec sin estado terminal.
    """
    deadline = time.monotonic() + max_wait_sec
    last: dict = {}
    while time.monotonic() < deadline:
        r = requests.get(
            f"{API_BASE}/agents/jobs/{job_id}/status",
            timeout=60,
        )
        if r.status_code != 200:
            raise RuntimeError(f"job status HTTP {r.status_code}: {r.text[:500]}")
        body = r.json()
        last = body.get("data") or {}
        st = (last.get("status") or "").upper()
        if st in ("COMPLETED", "FAILED"):
            return last
        time.sleep(poll_interval)
    raise requests.Timeout(
        f"Job {job_id} no terminó en {max_wait_sec}s (último estado: {last.get('status')})"
    )


def main() -> int:
    base_dir = Path(os.environ.get("LICITAI_PRUEBA_INTELIGENCIA_DIR", DEFAULT_DIR))
    if not base_dir.is_dir():
        print(f"ERROR: No existe carpeta: {base_dir}", file=sys.stderr, flush=True)
        return 1

    def _file_sort_key(p: Path) -> tuple:
        # PDF primero: el pipeline de extracción es más estable que DOCX en algunos entornos.
        ext = p.suffix.lower()
        prio = 0 if ext == ".pdf" else 1
        return (prio, p.name.lower())

    files = sorted(
        [p for p in base_dir.iterdir() if p.is_file() and not p.name.startswith(".")],
        key=_file_sort_key,
    )
    if not files:
        print(f"ERROR: Sin archivos en {base_dir}", file=sys.stderr, flush=True)
        return 1

    max_files = os.environ.get("LICITAI_MAX_FILES")
    if max_files and max_files.isdigit():
        files = files[: int(max_files)]

    target_file = os.environ.get("LICITAI_TARGET_FILE")
    if target_file:
        target_path = Path(target_file)
        target_name = target_path.name.lower()
        files = [p for p in files if p.name.lower() == target_name]
        if not files:
            print(
                f"ERROR: LICITAI_TARGET_FILE no coincide con archivos en carpeta: {target_file}",
                file=sys.stderr,
                flush=True,
            )
            return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if os.environ.get("LICITAI_REPORT_JSON"):
        report_path = Path(os.environ["LICITAI_REPORT_JSON"])
    else:
        report_path = REPO_ROOT / "docs" / f"corridas_prueba_inteligencia_{ts}.json"

    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_base": API_BASE,
        "source_dir": str(base_dir),
        "report_path": str(report_path),
        "checkpoint_mode": "resume_skip_completed",
        "cases": [],
        "errors": [],
    }

    if report_path.exists():
        try:
            previous = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(previous, dict) and isinstance(previous.get("cases"), list):
                report["cases"] = previous["cases"]
                print(
                    f"Checkpoint detectado: {len(report['cases'])} casos previos cargados.",
                    flush=True,
                )
        except Exception:
            # Si no se puede leer el reporte previo, se continúa con corrida limpia.
            pass

    done_ok_filenames = {
        c.get("filename")
        for c in report["cases"]
        if isinstance(c, dict) and c.get("filename") and c.get("error") is None and c.get("orchestrator_status")
    }
    previous_timeout_filenames = {
        c.get("filename")
        for c in report["cases"]
        if isinstance(c, dict)
        and c.get("filename")
        and isinstance(c.get("error"), str)
        and (
            "read timed out" in c.get("error", "").lower()
            or "no terminó en" in c.get("error", "").lower()
        )
    }

    def persist() -> None:
        report["summary"] = {
            "total_files": len(files),
            "cases_recorded": len(report["cases"]),
            "ok": sum(
                1
                for c in report["cases"]
                if c.get("error") is None and c.get("orchestrator_status")
            ),
            "failed": sum(1 for c in report["cases"] if c.get("error")),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    r0 = requests.get(f"{API_BASE}/health", timeout=15)
    if r0.status_code != 200:
        report["errors"].append(f"health {r0.status_code}")
        persist()
        print(f"Reporte (parcial): {report_path}", flush=True)
        return 2

    persist()
    print(f"Reporte incremental: {report_path}", flush=True)

    run_suffix = uuid.uuid4().hex[:8]

    to_run = [p for p in files if p.name not in done_ok_filenames]
    skipped = len(files) - len(to_run)
    if skipped:
        print(f"Checkpoint: se omiten {skipped} archivo(s) ya exitosos.", flush=True)

    for idx, fp in enumerate(to_run, start=1):
        case = {
            "index": idx,
            "filename": fp.name,
            "session_id": None,
            "steps": {},
            "orchestrator_status": None,
            "analysis_status": None,
            "compliance_status": None,
            "error": None,
        }
        reuse_session = os.environ.get("E2E_RESUME_SESSION_ID", "").strip()
        if reuse_session:
            session_slug = reuse_session[:63]
            case["session_id"] = session_slug
            case["steps"]["reuse_session"] = True
        else:
            base_slug = f"lic_p_intel_{idx:02d}_{_slug(fp.stem)}_{run_suffix}"
            session_slug = base_slug[:63]
            case["session_id"] = session_slug

        try:
            if not reuse_session:
                cr = requests.post(
                    f"{API_BASE}/sessions/create",
                    params={"name": session_slug},
                    timeout=60,
                )
                case["steps"]["create_session"] = {"status_code": cr.status_code, "body": cr.text[:500]}
                cr_ok = cr.status_code == 200
                try:
                    cr_j = cr.json()
                    cr_ok = cr_ok and bool(cr_j.get("success", False))
                except Exception:
                    cr_ok = False
                if not cr_ok:
                    case["error"] = "create_session failed"
                    report["cases"].append(case)
                    persist()
                    continue

                with open(fp, "rb") as f:
                    up = requests.post(
                        f"{API_BASE}/upload/document",
                        files={"file": (fp.name, f, "application/octet-stream")},
                        data={"session_id": session_slug},
                        timeout=UPLOAD_TIMEOUT,
                    )
                case["steps"]["upload"] = {"status_code": up.status_code, "body": up.text[:800]}
                if up.status_code != 200:
                    case["error"] = "upload failed"
                    report["cases"].append(case)
                    persist()
                    continue

                up_j = up.json()
                doc_id = (up_j.get("data") or {}).get("doc_id")
                if not doc_id:
                    case["error"] = "no doc_id"
                    report["cases"].append(case)
                    persist()
                    continue

                pr = requests.post(
                    f"{API_BASE}/upload/process/{doc_id}",
                    data={"session_id": session_slug},
                    timeout=PROCESS_TIMEOUT,
                )
                case["steps"]["process"] = {"status_code": pr.status_code, "body": pr.text[:1200]}
                if pr.status_code != 200:
                    case["error"] = "process failed"
                    report["cases"].append(case)
                    persist()
                    continue

            resume_gen = _env_bool("E2E_RESUME_GENERATION") or bool(reuse_session)
            body = {
                "session_id": session_slug,
                "company_id": None,
                "company_data": {"mode": "analysis_only", "name": f"Protocolo_Prueba_{idx:02d}"},
                "resume_generation": resume_gen,
            }
            orch_timeout = _calc_orch_timeout_sec(fp.stat().st_size)
            # Si el archivo ya presentó timeout en corrida previa, subir timeout para reintento.
            if fp.name in previous_timeout_filenames:
                orch_timeout = max(orch_timeout, int(os.environ.get("E2E_RETRY_TIMEOUT_SEC", "7200")))
            case["steps"]["agents_process_timeout_sec"] = orch_timeout
            # POST asíncrono: 202 Accepted + job_id; el trabajo real se espera por polling.
            orch = requests.post(
                f"{API_BASE}/agents/process",
                json=body,
                timeout=E2E_PROCESS_ACCEPT_TIMEOUT_SEC,
            )
            case["steps"]["agents_process_accept"] = {
                "status_code": orch.status_code,
                "body_preview": orch.text[:3500],
            }
            if orch.status_code not in (200, 202):
                case["error"] = f"agents/process HTTP {orch.status_code}"
                report["cases"].append(case)
                persist()
                continue

            accept_j = orch.json()
            acc_data = accept_j.get("data") or {}
            job_id = acc_data.get("job_id")
            if not job_id:
                case["error"] = "agents/process sin job_id en respuesta"
                report["cases"].append(case)
                persist()
                continue

            case["steps"]["job_id"] = job_id
            try:
                job_state = _poll_job_until_done(job_id, max_wait_sec=orch_timeout)
            except (requests.Timeout, RuntimeError) as pe:
                case["error"] = str(pe)
                report["cases"].append(case)
                persist()
                continue

            case["steps"]["agents_process_job_final"] = {
                "status": job_state.get("status"),
                "error": job_state.get("error"),
                "forensic_traceback": job_state.get("forensic_traceback"),
            }

            if job_state.get("status") == "FAILED":
                case["error"] = job_state.get("error") or "job FAILED"
                report["cases"].append(case)
                persist()
                continue

            result = job_state.get("result") or {}
            case["orchestrator_status"] = result.get("status")
            data = result.get("data") or {}
            if isinstance(data.get("analysis"), dict):
                case["analysis_status"] = data["analysis"].get("status")
            if isinstance(data.get("compliance"), dict):
                case["compliance_status"] = data["compliance"].get("status")
                case["compliance_message"] = data["compliance"].get("message") or data["compliance"].get("error")

        except requests.Timeout as e:
            case["error"] = f"timeout: {e}"
        except Exception as e:
            case["error"] = repr(e)

        report["cases"].append(case)
        persist()
        print(
            f"[{idx}/{len(to_run)}] {fp.name} -> "
            f"orch={case.get('orchestrator_status')} "
            f"analysis={case.get('analysis_status')} "
            f"compliance={case.get('compliance_status')} "
            f"err={case.get('error')}",
            flush=True,
        )

    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    persist()
    print(f"\nReporte final: {report_path}", flush=True)
    return 0 if report["summary"]["failed"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
