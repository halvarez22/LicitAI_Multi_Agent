"""Smoke: generación técnica vía API + verificación disco/artifacts."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:8000/api/v1"
SESSION_ID = "vigilancia_issste"
COMPANY_ID = "co_1780079004578"
POLL_SEC = 3
TIMEOUT_SEC = 600


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    print(f"=== Generación técnica: {SESSION_ID} ===")
    try:
        enc = _post(
            "/agents/process",
            {
                "session_id": SESSION_ID,
                "company_id": COMPANY_ID,
                "resume_generation": True,
                "generation_mode": "technical",
                "company_data": {
                    "mode": "generation_only",
                    "generation_mode": "technical",
                },
            },
        )
    except urllib.error.HTTPError as exc:
        print("POST /agents/process falló:", exc.read().decode("utf-8", errors="replace"))
        return 1

    job_id = (enc.get("data") or {}).get("job_id")
    if not job_id:
        print("Sin job_id:", json.dumps(enc, ensure_ascii=False, indent=2))
        return 1
    print("job_id:", job_id)

    t0 = time.time()
    result = None
    while time.time() - t0 < TIMEOUT_SEC:
        st = _get(f"/agents/jobs/{job_id}/status")
        job = (st.get("data") or {})
        status = job.get("status")
        prog = job.get("progress") or {}
        print(f"  [{status}] pct={prog.get('pct')} msg={prog.get('message', '')[:80]}")
        if status == "COMPLETED":
            result = job.get("result") or {}
            break
        if status == "FAILED":
            print("Job FAILED:", job.get("error"))
            return 1
        time.sleep(POLL_SEC)

    if result is None:
        print("Timeout esperando job")
        return 1

    orch_status = result.get("status")
    print("orchestrator status:", orch_status)
    print("chatbot_message:", (result.get("chatbot_message") or "")[:200])

    arts = _get(
        f"/downloads/artifacts?session_id={SESSION_ID}&scope=technical"
    )
    data = arts.get("data") or {}
    print("artifacts technical ready:", data.get("ready"), "count:", data.get("artifact_count"))
    if data.get("empty_reason"):
        print("empty_reason:", data.get("empty_reason"), "-", data.get("empty_reason_message"))

    # list files on disk
    import os

    tech_dir = f"/data/outputs/{SESSION_ID}/1.propuesta tecnica"
    files = []
    if os.path.isdir(tech_dir):
        for root, _, names in os.walk(tech_dir):
            for n in names:
                files.append(os.path.join(root, n))
    print("archivos en disco:", len(files))
    for f in sorted(files)[:15]:
        print(" ", f)

    ok = bool(data.get("ready")) and len(files) > 0 and orch_status in ("success", "partial")
    if not ok and orch_status == "waiting_for_data" and len(files) > 0:
        ok = True
        print("(Nota: archivos generados aunque orquestador en waiting_for_data)")
    print("RESULTADO:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
