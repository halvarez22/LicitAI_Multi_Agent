"""
E2E contra API real: subida → process → POST /agents/process (orquestador).
Genera un PDF nativo con texto >100 chars para pasar validaciones de extracción.

Uso (desde host, backend en localhost:8001):
  python scripts/e2e_orchestrator_run.py

Salida: scripts/e2e_orchestrator_report.json (y stdout resumido).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

# Raíz backend (contenedor monta /app; en host es la carpeta backend)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = Path(__file__).resolve().parent / "e2e_orchestrator_report.json"

API_BASE = os.environ.get("E2E_API_URL", "http://localhost:8001/api/v1")
REQUEST_TIMEOUT_PROCESS = int(os.environ.get("E2E_ORCH_TIMEOUT_SEC", "1800"))  # 30 min


def _build_native_pdf() -> str:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    c = canvas.Canvas(path, pagesize=letter)
    lines = [
        "Licitación pública municipal. Objeto: suministro e instalación de luminarias LED viales.",
        "Requisitos: constancia fiscal, padrón de proveedores, garantía de seriedad del cinco por ciento.",
        "Plazos: junta de aclaraciones, presentación de proposiciones y fallo según bases.",
        "La propuesta técnica y económica se presentará en sobre cerrado según instructivo.",
    ]
    y = 750
    for line in lines:
        c.drawString(72, y, line[:95])
        y -= 18
    c.save()
    return path


def main() -> int:
    report: dict = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_base": API_BASE,
        "steps": [],
        "errors": [],
    }
    session_id = f"e2e_orch_{uuid.uuid4().hex[:10]}"
    pdf_path: str | None = None

    def log_step(name: str, **kwargs):
        entry = {"name": name, "ts": time.time(), **kwargs}
        report["steps"].append(entry)
        print(f"[E2E] {name}: {kwargs}")

    try:
        r = requests.get(f"{API_BASE}/health", timeout=15)
        log_step("health", status_code=r.status_code, body=r.text[:500])
        if r.status_code != 200:
            report["errors"].append("health no 200")
            report["final_status"] = "aborted"
            _write_report(report)
            return 1

        pdf_path = _build_native_pdf()
        log_step("pdf_created", path=pdf_path, size=os.path.getsize(pdf_path))

        with open(pdf_path, "rb") as f:
            up = requests.post(
                f"{API_BASE}/upload/document",
                files={"file": ("e2e_bases_dummy.pdf", f, "application/pdf")},
                data={"session_id": session_id},
                timeout=120,
            )
        log_step("upload", status_code=up.status_code, body=up.text[:800])
        if up.status_code != 200:
            report["errors"].append(f"upload failed: {up.text}")
            report["final_status"] = "aborted"
            _write_report(report)
            return 1

        up_j = up.json()
        doc_id = (up_j.get("data") or {}).get("doc_id")
        if not doc_id:
            report["errors"].append("sin doc_id en upload")
            report["final_status"] = "aborted"
            _write_report(report)
            return 1

        pr = requests.post(
            f"{API_BASE}/upload/process/{doc_id}",
            data={"session_id": session_id},
            timeout=600,
        )
        log_step("upload_process", status_code=pr.status_code, body=pr.text[:1200])
        if pr.status_code != 200:
            report["errors"].append(f"upload/process failed: {pr.text[:2000]}")
            report["final_status"] = "ingest_failed"
            _write_report(report)
            return 2

        body = {
            "session_id": session_id,
            "company_id": None,
            "company_data": {
                "mode": "analysis_only",
                "name": "E2E_Orchestrator_Client",
            },
        }
        t0 = time.time()
        orch = requests.post(
            f"{API_BASE}/agents/process",
            json=body,
            timeout=REQUEST_TIMEOUT_PROCESS,
        )
        elapsed = time.time() - t0
        log_step(
            "agents_process",
            status_code=orch.status_code,
            elapsed_sec=round(elapsed, 2),
            body_preview=orch.text[:2500],
        )

        if orch.status_code != 200:
            report["errors"].append(f"agents/process HTTP {orch.status_code}: {orch.text[:3000]}")
            report["final_status"] = "orchestrator_http_error"
            _write_report(report)
            return 3

        payload = orch.json()
        report["orchestrator_response"] = _sanitize_payload(payload)
        report["final_status"] = payload.get("status", "unknown")
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_report(report)
        print(json.dumps(report["orchestrator_response"], indent=2, ensure_ascii=False)[:4000])
        return 0
    except requests.Timeout:
        report["errors"].append(f"timeout después de {REQUEST_TIMEOUT_PROCESS}s")
        report["final_status"] = "timeout"
        _write_report(report)
        return 4
    except Exception as e:
        report["errors"].append(repr(e))
        report["final_status"] = "exception"
        _write_report(report)
        raise
    finally:
        if pdf_path:
            try:
                os.unlink(pdf_path)
            except OSError:
                pass


def _sanitize_payload(p: dict) -> dict:
    """Recorta respuestas enormes para el JSON de reporte."""
    out = dict(p)
    data = out.get("data")
    if isinstance(data, dict):
        slim = {}
        for k, v in data.items():
            if k == "compliance" and isinstance(v, dict):
                slim[k] = {
                    "status": v.get("status"),
                    "keys": list(v.keys()),
                }
                if "data" in v and isinstance(v["data"], dict):
                    slim[k]["data_keys"] = list(v["data"].keys())
            elif k == "analysis" and isinstance(v, dict):
                slim[k] = {"status": v.get("status"), "keys": list(v.keys())}
            else:
                s = json.dumps(v, ensure_ascii=False)
                slim[k] = s[:2000] + ("…" if len(s) > 2000 else "")
        out["data"] = slim
    return out


def _write_report(report: dict) -> None:
    report.setdefault("finished_at_utc", datetime.now(timezone.utc).isoformat())
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[E2E] Reporte escrito: {REPORT_PATH}")


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND_ROOT))
    raise SystemExit(main())
