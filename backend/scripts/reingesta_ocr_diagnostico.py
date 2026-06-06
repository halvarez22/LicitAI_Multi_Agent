"""
Informe de re-ingesta OCR: compara texto persistido vs extracción actual por página.

Uso (dentro del contenedor backend):
  python scripts/reingesta_ocr_diagnostico.py --session opm_municipio_madera --pages 3,15,24,7
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_PROMPT_ECHO = "ANALIZAR Y TRANSCRIBIR DE FORMA FORENSE"
_PAGE_SPLIT = re.compile(r"---\s*PÁGINA\s+(\d+)\s*---", re.IGNORECASE)


def _split_pages(full_text: str) -> Dict[int, str]:
    parts = _PAGE_SPLIT.split(full_text or "")
    out: Dict[int, str] = {}
    for i in range(1, len(parts), 2):
        try:
            num = int(parts[i])
        except (TypeError, ValueError):
            continue
        body = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        out[num] = body
    return out


def _classify_page(text: str) -> str:
    t = (text or "").strip()
    if len(t) < 80:
        return "VACIA_CORTA"
    if t.startswith(_PROMPT_ECHO) and len(t) < 450:
        return "CONTAMINADA_SOLO_PROMPT"
    if _PROMPT_ECHO in t[:150]:
        return "CONTAMINADA_PROMPT_MAS_TEXTO"
    return "OK"


def _preview(s: str, n: int = 400) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s if len(s) <= n else s[: n - 1] + "…"


async def _ollama_glm_short_prompt(
    vision_agent: Any, file_path: str, page_num: int
) -> Dict[str, Any]:
    """Misma imagen, prompt corto tipo CLI (diagnóstico, no pipeline productivo)."""
    import httpx

    img_str = await vision_agent._render_page_base64(file_path, page_num)
    if not img_str:
        return {"error": "render_failed", "text": ""}
    payload = {
        "model": "glm-ocr",
        "prompt": "Text Recognition:\nExtract all text from this image accurately.",
        "images": [img_str],
        "stream": False,
        "options": {"temperature": 0.0, "num_ctx": 16384, "num_predict": 4096},
    }
    url = f"{vision_agent.ollama_url.strip('/')}/api/generate"
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            text = (res.json().get("response") or "").strip()
            return {"text": text, "chars": len(text), "status": res.status_code}
    except Exception as exc:
        return {"error": str(exc)[:300], "text": "", "chars": 0}


async def run_report(
    session_id: str,
    page_nums: List[int],
    *,
    out_dir: str,
) -> str:
    from app.agents.extractor_digital import DigitalExtractorAgent
    from app.agents.extractor_vision import VisionExtractorAgent
    from app.memory.factory import MemoryAdapterFactory
    import fitz

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()

    file_path: Optional[str] = None
    filename = ""
    stored_full = ""
    for d in await mem.get_documents(session_id) or []:
        c = d.get("content") if isinstance(d.get("content"), dict) else {}
        fn = str(c.get("filename") or "")
        if "bases" not in fn.lower() and "licitacion" not in fn.lower():
            continue
        file_path = c.get("file_path") or c.get("path")
        filename = fn
        stored_full = c.get("extracted_text") or ""
        break

    if not file_path or not os.path.isfile(file_path):
        await mem.disconnect()
        raise FileNotFoundError(f"PDF no encontrado para sesión {session_id}: {file_path}")

    stored_by_page = _split_pages(stored_full)
    digital = DigitalExtractorAgent()
    vision = VisionExtractorAgent()

    ocr_url = os.getenv("OCR_URL", "")
    health_ocr = False
    try:
        from app.services.ocr_service import OCRServiceClient

        health_ocr = await OCRServiceClient().health_check()
    except Exception:
        pass

    models_glm: List[str] = []
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{vision.ollama_url.strip('/')}/api/tags")
            if r.status_code == 200:
                models_glm = [
                    m.get("name", "")
                    for m in r.json().get("models", [])
                    if "glm" in str(m.get("name", "")).lower()
                    or "ocr" in str(m.get("name", "")).lower()
                ]
    except Exception as exc:
        models_glm = [f"error_tags: {exc}"]

    doc = fitz.open(file_path)
    pages_report: List[Dict[str, Any]] = []

    for pn in page_nums:
        if pn < 1 or pn > len(doc):
            pages_report.append({"page": pn, "error": "page_out_of_range"})
            continue

        stored = stored_by_page.get(pn, "")
        page = doc.load_page(pn - 1)
        digital_text = digital.extract_page_digital(page)
        digital_signal = len(digital_text.strip()) > 50

        print(f"[*] Re-ingesta página {pn} (VLM forense + prompt corto)...")
        vlm_forensic = await vision.extract_page_vision(file_path, pn)
        vlm_short = await _ollama_glm_short_prompt(vision, file_path, pn)

        pages_report.append(
            {
                "page": pn,
                "stored": {
                    "classification": _classify_page(stored),
                    "chars": len(stored),
                    "preview": _preview(stored, 500),
                    "has_prompt_echo": _PROMPT_ECHO in (stored[:200] if stored else ""),
                },
                "digital_pymupdf": {
                    "chars": len(digital_text.strip()),
                    "would_skip_vlm": digital_signal,
                    "preview": _preview(digital_text, 400),
                },
                "reingesta_vlm_forensic_prompt": {
                    "chars": len(vlm_forensic),
                    "classification": _classify_page(vlm_forensic),
                    "preview": _preview(vlm_forensic, 500),
                    "matches_stored_prefix": stored[:120] == vlm_forensic[:120]
                    if stored and vlm_forensic
                    else False,
                },
                "reingesta_vlm_short_prompt": {
                    "chars": vlm_short.get("chars", 0),
                    "classification": _classify_page(vlm_short.get("text", "")),
                    "preview": _preview(vlm_short.get("text", ""), 500),
                    "error": vlm_short.get("error"),
                },
                "delta_chars_forensic_vs_stored": len(vlm_forensic) - len(stored),
            }
        )

    doc.close()
    await mem.disconnect()

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "filename": filename,
        "file_path": file_path,
        "total_pages_pdf": len(stored_by_page) or None,
        "infra": {
            "OCR_URL": ocr_url,
            "OLLAMA_URL": vision.ollama_url,
            "ocr_health_check": health_ocr,
            "glm_models_in_ollama": models_glm,
            "vision_model_in_code": "glm-ocr",
            "ocr_vlm_microservice": "disabled_in_compose",
        },
        "pages_sampled": page_nums,
        "pages": pages_report,
        "interpretacion": (
            "Si reingesta_vlm_forensic repite el prompt, el modelo vía Ollama no está "
            "transcribiendo con el prompt largo actual. Si vlm_short_prompt devuelve texto "
            "útil, el insumo falla por formato de prompt, no por ausencia del modelo."
        ),
    }

    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "reingesta_ocr_opm_report.json")
    md_path = os.path.join(out_dir, "reingesta_ocr_opm_report.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lines = [
        "# Informe de re-ingesta OCR — OPM Madera",
        "",
        f"- **Generado:** {report['generated_at']}",
        f"- **Sesión:** `{session_id}`",
        f"- **Archivo:** {filename}",
        f"- **Modelos glm/ocr en Ollama:** {', '.join(models_glm) or '—'}",
        f"- **health_check OCR_URL:** {health_ocr}",
        "",
        "## Infraestructura",
        "",
        "| Variable | Valor |",
        "|----------|-------|",
        f"| OCR_URL | `{ocr_url}` |",
        f"| Modelo en código | `glm-ocr` |",
        f"| Microservicio ocr-vlm | Desactivado en compose |",
        "",
        "## Páginas muestreadas",
        "",
    ]
    for p in pages_report:
        if p.get("error"):
            lines.append(f"### Página {p['page']} — ERROR: {p['error']}")
            continue
        st = p["stored"]
        lines.extend(
            [
                f"### Página {p['page']}",
                "",
                f"| Fuente | Clasificación | Caracteres |",
                f"|--------|---------------|------------|",
                f"| **Persistido (BD)** | {st['classification']} | {st['chars']} |",
                f"| PyMuPDF digital | — | {p['digital_pymupdf']['chars']} "
                f"(¿saltaría VLM? {p['digital_pymupdf']['would_skip_vlm']}) |",
                f"| Re-ingesta VLM prompt forense | "
                f"{p['reingesta_vlm_forensic_prompt']['classification']} | "
                f"{p['reingesta_vlm_forensic_prompt']['chars']} |",
                f"| Re-ingesta VLM prompt corto | "
                f"{p['reingesta_vlm_short_prompt']['classification']} | "
                f"{p['reingesta_vlm_short_prompt']['chars']} |",
                "",
                "**Persistido (preview):**",
                f"> {st['preview']}",
                "",
                "**VLM forense (preview):**",
                f"> {p['reingesta_vlm_forensic_prompt']['preview']}",
                "",
                "**VLM prompt corto (preview):**",
                f"> {p['reingesta_vlm_short_prompt']['preview']}",
                "",
                "---",
                "",
            ]
        )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="opm_municipio_madera")
    parser.add_argument(
        "--pages",
        default="3,15,24,7",
        help="Números de página separados por coma (7 = control OK)",
    )
    parser.add_argument(
        "--out-dir",
        default="/app/scratch",
        help="Directorio de salida (en host: backend/scratch)",
    )
    args = parser.parse_args()
    pages = [int(x.strip()) for x in args.pages.split(",") if x.strip()]
    path = asyncio.run(run_report(args.session, pages, out_dir=args.out_dir))
    print(f"Informe JSON: {path}")
    print(f"Informe MD:   {path.replace('.json', '.md')}")


if __name__ == "__main__":
    main()
