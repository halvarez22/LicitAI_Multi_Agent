"""
E2E desatendido: empresa (SERTEI) + licitación + bases reales + Excel costos + orquestador.

Rutas por defecto (Windows, repo licitaciones-ai):
  SERTEI:  .../Documentos de empresa participante/sertei
  BASES:   .../bases y convocatorias de prueba
  COSTOS:  .../costos

Variables:
  E2E_API_URL              (default http://127.0.0.1:8001/api/v1)
  E2E_SERTEI_DIR, E2E_BASES_DIR, E2E_COSTOS_DIR
  E2E_JOB_TIMEOUT_SEC      (default 7200)
  E2E_POLL_SEC             (default 5)
  E2E_REPORT_DESKTOP       (1 escribe MD+JSON en Escritorio del usuario)

Uso (desde carpeta backend, con API levantada):
  python scripts/e2e_corporate_licitacion_desatendido.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

API_BASE = os.environ.get("E2E_API_URL", "http://127.0.0.1:8001/api/v1").rstrip("/")
JOB_TIMEOUT = int(os.environ.get("E2E_JOB_TIMEOUT_SEC", "7200"))
POLL_SEC = max(2, int(os.environ.get("E2E_POLL_SEC", "5")))
AGENTS_POST_TIMEOUT = int(os.environ.get("E2E_AGENTS_POST_TIMEOUT_SEC", "120"))
COMPANY_ANALYZE_TIMEOUT = int(os.environ.get("E2E_COMPANY_ANALYZE_TIMEOUT_SEC", "1800"))
WRITE_DESKTOP = os.environ.get("E2E_REPORT_DESKTOP", "1").strip().lower() in ("1", "true", "yes")
# Solo CIF + logo (sin Acta de ~7MB): valida licitación+orquestador sin esperar OCR pesado del acta.
CORP_MINIMAL = os.environ.get("E2E_CORP_MINIMAL", "0").strip().lower() in ("1", "true", "yes")

DEFAULT_SERTEI = REPO_ROOT / "Documentos de empresa participante" / "sertei"
DEFAULT_BASES = REPO_ROOT / "bases y convocatorias de prueba"
DEFAULT_COSTOS = REPO_ROOT / "costos"

SERTEI_DIR = Path(os.environ.get("E2E_SERTEI_DIR", str(DEFAULT_SERTEI)))
BASES_DIR = Path(os.environ.get("E2E_BASES_DIR", str(DEFAULT_BASES)))
COSTOS_DIR = Path(os.environ.get("E2E_COSTOS_DIR", str(DEFAULT_COSTOS)))

# Bases: PDF vigilancia (nativo, tamaño manejable). Costos: Excel único en carpeta costos.
BASE_PDF = "LA-51-GYN-051GYN025-N-8-2024 VIGILANCIA.pdf"
COST_XLSX = "CALCULO COSTO ISSSTE VIGILANCIA 2024.xlsx"


def _desktop_dir() -> Path | None:
    home = Path(os.environ.get("USERPROFILE", "") or "")
    for candidate in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return candidate
    return None


def _poll_job(session: requests.Session, job_id: str, deadline: float) -> dict:
    last_prog = None
    transient = 0
    while time.time() < deadline:
        try:
            r = session.get(f"{API_BASE}/agents/jobs/{job_id}/status", timeout=60)
        except requests.RequestException:
            transient += 1
            if transient > 24:
                return {"ok": False, "error": "poll_network"}
            time.sleep(POLL_SEC)
            continue
        transient = 0
        if r.status_code != 200:
            return {"ok": False, "error": "poll_http", "code": r.status_code, "body": r.text[:800]}
        body = r.json()
        data = body.get("data") or {}
        st = data.get("status")
        prog = data.get("progress") or {}
        if prog != last_prog:
            last_prog = prog
            print(f"    [job] {st} | {prog.get('message', '')}", flush=True)
        if st == "COMPLETED":
            return {"ok": True, "job": data}
        if st == "FAILED":
            return {"ok": False, "job": data, "error": data.get("error")}
        time.sleep(POLL_SEC)
    return {"ok": False, "error": "poll_timeout"}


def _maybe_answer_chatbot(session: requests.Session, session_id: str, company_id: str, profile: dict) -> list[dict]:
    """Inyecta 1–3 respuestas genéricas con datos del perfil corporativo si existen."""
    rl = (profile.get("representante_legal") or "").strip()
    rfc = (profile.get("rfc") or "").strip()
    rz = (profile.get("razon_social") or "").strip()
    parts = []
    if rl:
        parts.append(f"El representante legal vigente es {rl}.")
    if rfc:
        parts.append(f"El RFC de la empresa es {rfc}.")
    if rz:
        parts.append(f"La razón social es {rz}.")
    if not parts:
        parts.append(
            "Confirmo los datos de la empresa según acta constitutiva y CIF cargados; procede con el análisis."
        )
    query = " ".join(parts)
    out = []
    for i in range(3):
        try:
            r = session.post(
                f"{API_BASE}/chatbot/ask",
                json={"session_id": session_id, "company_id": company_id, "query": query},
                timeout=120,
            )
            out.append({"round": i + 1, "status_code": r.status_code, "preview": r.text[:600]})
            if r.status_code != 200:
                break
        except requests.RequestException as e:
            out.append({"round": i + 1, "error": repr(e)})
            break
    return out


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trace_path = REPO_ROOT / "data" / "e2e_outputs" / f"e2e_corporate_trace_{stamp}.log"
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    def trace(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
        trace_path.open("a", encoding="utf-8").write(line)

    report: dict = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_base": API_BASE,
        "paths": {"sertei": str(SERTEI_DIR), "bases": str(BASES_DIR), "costos": str(COSTOS_DIR)},
        "steps": [],
        "errors": [],
        "company_analyze": None,
        "orchestrator_poll": None,
        "chatbot_injections": [],
    }

    def log(name: str, **kw):
        entry = {"name": name, "ts": time.time(), **kw}
        report["steps"].append(entry)
        print(f"[E2E] {name}: {kw}", flush=True)
        trace(f"{name} {kw}")

    http = requests.Session()
    company_id = f"co_e2e_{uuid.uuid4().hex[:10]}"
    lic_name = f"E2E Desatendido SERTEI {stamp}"

    # --- Validación de rutas ---
    for label, p in (("sertei", SERTEI_DIR), ("bases", BASES_DIR), ("costos", COSTOS_DIR)):
        if not p.is_dir():
            report["errors"].append(f"Carpeta {label} no existe: {p}")
            report["final_status"] = "paths_missing"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 1

    acta = SERTEI_DIR / "Acta Constitutiva.pdf"
    cif = SERTEI_DIR / "CIF sertei.pdf"
    logo = SERTEI_DIR / "logo_sertei_sin fondo.png"
    bases_pdf = BASES_DIR / BASE_PDF
    cost_xlsx = COSTOS_DIR / COST_XLSX

    for label, p in (
        ("acta", acta),
        ("cif", cif),
        ("logo", logo),
        ("bases_pdf", bases_pdf),
        ("cost_xlsx", cost_xlsx),
    ):
        if not p.is_file():
            report["errors"].append(f"Archivo faltante {label}: {p}")
            report["final_status"] = "files_missing"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 1

    try:
        r = http.get(f"{API_BASE}/health", timeout=15)
        log("health", status_code=r.status_code)
        if r.status_code != 200:
            report["errors"].append("health no 200")
            report["final_status"] = "health_fail"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 2

        # --- Empresa ---
        cr = http.post(
            f"{API_BASE}/companies/",
            json={
                "id": company_id,
                "name": "SERTEI E2E",
                "type": "moral",
                "docs_metadata": {},
                "master_profile": {},
            },
            timeout=60,
        )
        log("company_create", status_code=cr.status_code, body_preview=cr.text[:500])
        if cr.status_code != 200 or not cr.json().get("success", True):
            report["errors"].append("crear empresa falló")
            report["final_status"] = "company_create_fail"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 3

        uploads = []
        if not CORP_MINIMAL:
            uploads.append(("Acta Constitutiva", acta, "application/pdf"))
        uploads.extend(
            [
                ("CIF (SAT)", cif, "application/pdf"),
                ("LOGOTIPO", logo, "image/png"),
            ]
        )
        report["e2e_corp_minimal"] = CORP_MINIMAL
        for doc_title, path, mime in uploads:
            with open(path, "rb") as f:
                ur = http.post(
                    f"{API_BASE}/companies/{company_id}/upload",
                    files={"file": (path.name, f, mime)},
                    data={"docTitle": doc_title},
                    timeout=300,
                )
            log("company_upload", doc_title=doc_title, status_code=ur.status_code, preview=ur.text[:400])
            if ur.status_code != 200:
                report["errors"].append(f"upload {doc_title} HTTP {ur.status_code}")
                report["final_status"] = "company_upload_fail"
                _write_reports(report, stamp, WRITE_DESKTOP)
                return 4

        report["company_id"] = company_id
        try:
            ar = http.post(
                f"{API_BASE}/companies/{company_id}/analyze",
                timeout=COMPANY_ANALYZE_TIMEOUT,
            )
        except requests.Timeout:
            report["errors"].append(
                f"timeout en company/analyze (>={COMPANY_ANALYZE_TIMEOUT}s); "
                "sube E2E_COMPANY_ANALYZE_TIMEOUT_SEC o ejecuta en máquina con OCR/VLM más rápido."
            )
            report["company_analyze"] = {"http": "timeout", "success": False}
            report["final_status"] = "company_analyze_timeout"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 14

        log("company_analyze", status_code=ar.status_code, preview=ar.text[:1200])
        try:
            aj = ar.json()
        except Exception:
            aj = {}
        report["company_analyze"] = {
            "http": ar.status_code,
            "success": aj.get("success"),
            "message": aj.get("message"),
            "processing_report": aj.get("processing_report"),
            "profile_keys": list((aj.get("profile") or {}).keys()) if isinstance(aj.get("profile"), dict) else None,
            "representante_legal": (aj.get("profile") or {}).get("representante_legal")
            if isinstance(aj.get("profile"), dict)
            else None,
        }
        profile_after = aj.get("profile") if isinstance(aj.get("profile"), dict) else {}

        # --- Licitación (sesión) ---
        safe_name = lic_name.replace(" ", "%20")
        sr = http.post(f"{API_BASE}/sessions/create?name={safe_name}", timeout=60)
        log("session_create", status_code=sr.status_code, preview=sr.text[:500])
        sj = sr.json()
        if not sj.get("success") or not (sj.get("data") or {}).get("session_id"):
            report["errors"].append("crear sesión falló")
            report["final_status"] = "session_create_fail"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 5
        session_id = sj["data"]["session_id"]

        doc_ids: list[str] = []

        with open(bases_pdf, "rb") as f:
            up1 = http.post(
                f"{API_BASE}/upload/document",
                files={"file": (bases_pdf.name, f, "application/pdf")},
                data={"session_id": session_id},
                timeout=300,
            )
        log("upload_bases", status_code=up1.status_code)
        if up1.status_code != 200:
            report["errors"].append("upload bases falló")
            report["final_status"] = "upload_bases_fail"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 6
        d1 = (up1.json().get("data") or {}).get("doc_id")
        if d1:
            doc_ids.append(d1)

        with open(cost_xlsx, "rb") as f:
            up2 = http.post(
                f"{API_BASE}/upload/document",
                files={"file": (cost_xlsx.name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"session_id": session_id},
                timeout=300,
            )
        log("upload_costos", status_code=up2.status_code)
        if up2.status_code != 200:
            report["errors"].append("upload costos falló")
            report["final_status"] = "upload_costos_fail"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 7
        d2 = (up2.json().get("data") or {}).get("doc_id")
        if d2:
            doc_ids.append(d2)

        for did in doc_ids:
            pr = http.post(
                f"{API_BASE}/upload/process/{did}",
                data={"session_id": session_id},
                timeout=1200,
            )
            log("upload_process", doc_id=did, status_code=pr.status_code, preview=pr.text[:500])
            if pr.status_code != 200:
                report["errors"].append(f"process {did} falló")
                report["final_status"] = "ingest_fail"
                _write_reports(report, stamp, WRITE_DESKTOP)
                return 8

        body = {
            "session_id": session_id,
            "company_id": company_id,
            "company_data": {
                "mode": "full",
                "name": "SERTEI E2E",
            },
            "resume_generation": False,
        }
        orch = http.post(f"{API_BASE}/agents/process", json=body, timeout=AGENTS_POST_TIMEOUT)
        log("agents_process", status_code=orch.status_code, preview=orch.text[:800])
        if orch.status_code not in (200, 202):
            report["errors"].append(f"agents/process HTTP {orch.status_code}")
            report["final_status"] = "orchestrator_enqueue_fail"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 9

        oj = orch.json()
        job_id = (oj.get("data") or {}).get("job_id")
        if not job_id:
            report["errors"].append("sin job_id")
            report["final_status"] = "no_job_id"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 10

        deadline = time.time() + JOB_TIMEOUT
        poll_out = _poll_job(http, job_id, deadline)
        report["orchestrator_poll"] = {k: v for k, v in poll_out.items() if k != "job"}
        if not poll_out.get("ok"):
            report["errors"].append(f"job: {poll_out}")
            report["final_status"] = "job_failed_or_timeout"
            _write_reports(report, stamp, WRITE_DESKTOP)
            return 11

        job = poll_out["job"]
        result = job.get("result")
        report["orchestrator_result_summary"] = _slim_orchestrator_result(result)

        # Inyección post-orquestador (RAG / datos faltantes)
        injections = _maybe_answer_chatbot(http, session_id, company_id, profile_after)
        report["chatbot_injections"] = injections

        st = (result or {}).get("status", "unknown")
        report["final_status"] = "completed" if st != "error" else "orchestrator_error"
        if st == "error":
            report["errors"].append("orchestrator status=error en result")
        report["session_id"] = session_id
        report["company_id"] = company_id
        report["job_id"] = job_id
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_reports(report, stamp, WRITE_DESKTOP)
        return 0 if st != "error" else 12

    except requests.Timeout:
        report["errors"].append("timeout global requests")
        report["final_status"] = "timeout"
        _write_reports(report, stamp, WRITE_DESKTOP)
        return 13
    except Exception as e:
        report["errors"].append(repr(e))
        report["final_status"] = "exception"
        _write_reports(report, stamp, WRITE_DESKTOP)
        raise


def _slim_orchestrator_result(p: dict | None) -> dict:
    if not isinstance(p, dict):
        return {}
    out = {
        "status": p.get("status"),
        "session_id": p.get("session_id"),
        "chatbot_preview": (p.get("chatbot_message") or "")[:800],
    }
    data = p.get("data")
    if isinstance(data, dict):
        slim = {}
        for k, v in data.items():
            if k == "compliance" and isinstance(v, dict):
                inner = v.get("data") or {}
                slim[k] = {
                    "status": v.get("status"),
                    "n_admin": len(inner.get("administrativo") or []),
                    "n_tecnico": len(inner.get("tecnico") or []),
                    "n_formatos": len(inner.get("formatos") or []),
                }
            elif k == "analysis" and isinstance(v, dict):
                slim[k] = {"status": v.get("status"), "keys": list(v.keys())}
            else:
                s = json.dumps(v, ensure_ascii=False)
                slim[k] = s[:1500] + ("…" if len(s) > 1500 else "")
        out["data"] = slim
    return out


def _write_reports(report: dict, stamp: str, desktop: bool) -> None:
    out_dir = REPO_ROOT / "data" / "e2e_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"e2e_corporate_licitacion_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_lines = [
        "# Informe ejecutivo — E2E desatendido (empresa + licitación)",
        "",
        f"- **Inicio (UTC):** {report.get('started_at_utc')}",
        f"- **Fin (UTC):** {report.get('finished_at_utc', 'N/A')}",
        f"- **Estado final:** `{report.get('final_status')}`",
        f"- **API:** `{report.get('api_base')}`",
        f"- **Empresa:** `{report.get('company_id', 'N/A')}`",
        f"- **Modo minimal (sin acta):** `{report.get('e2e_corp_minimal', False)}`",
        f"- **Sesión:** `{report.get('session_id', 'N/A')}`",
        f"- **Job:** `{report.get('job_id', 'N/A')}`",
        "",
        "## Análisis corporativo (Acta / CIF)",
        "",
        "```json",
        json.dumps(report.get("company_analyze"), indent=2, ensure_ascii=False) or "{}",
        "```",
        "",
        "## Orquestador (resumen)",
        "",
        "```json",
        json.dumps(report.get("orchestrator_result_summary"), indent=2, ensure_ascii=False) or "{}",
        "```",
        "",
        "## Inyecciones chatbot post-job",
        "",
        "```json",
        json.dumps(report.get("chatbot_injections"), indent=2, ensure_ascii=False) or "[]",
        "```",
        "",
        "## Errores",
        "",
        "\n".join(f"- {e}" for e in (report.get("errors") or [])) or "- (ninguno)",
        "",
        "## Archivos generados",
        "",
        f"- JSON: `{json_path}`",
    ]
    md_repo = out_dir / f"E2E_REPORTE_EJECUTIVO_{stamp}.md"
    md_repo.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\n[E2E] JSON: {json_path}", flush=True)
    print(f"[E2E] MD (repo): {md_repo}", flush=True)

    if desktop:
        desk = _desktop_dir()
        if desk:
            md_desk = desk / f"E2E_REPORTE_EJECUTIVO_{stamp}.md"
            json_desk = desk / f"e2e_corporate_licitacion_{stamp}.json"
            md_desk.write_text(md_repo.read_text(encoding="utf-8"), encoding="utf-8")
            json_desk.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[E2E] MD (escritorio): {md_desk}", flush=True)
            print(f"[E2E] JSON (escritorio): {json_desk}", flush=True)
        else:
            print("[E2E] Escritorio no encontrado; solo repo data/e2e_outputs", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND_ROOT))
    raise SystemExit(main())
