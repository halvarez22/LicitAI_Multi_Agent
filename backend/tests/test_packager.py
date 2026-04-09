"""Tests del empaquetador CompraNet determinista (sin LLM)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

from app.agents.packager import CompraNetPackager, build_pack_session_data_from_outputs

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "real_sessions"


def _load_oracle_validator():
    backend_root = Path(__file__).resolve().parents[1]
    module_path = backend_root / "scripts" / "oracle_validator.py"
    spec = importlib.util.spec_from_file_location("oracle_validator_pkg", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules["oracle_validator_pkg"] = module
    spec.loader.exec_module(module)
    return module


def _profile_from_fixture() -> dict:
    raw = json.loads((_FIXTURES / "template_lock_data.json").read_text(encoding="utf-8"))
    return raw.get("master_profile") or {}


def test_packager_ok_con_estructura_sobres(tmp_path: Path) -> None:
    profile = _profile_from_fixture()
    rfc = str(profile.get("rfc") or "RFC_FIXTURE")
    lic = "la-51-gyn-051gyn025-n-8-2024_vigilancia"
    root = tmp_path / lic
    sobre = root / "SOBRE_1_ADMINISTRATIVO"
    sobre.mkdir(parents=True)
    doc = sobre / "01_propuesta.docx"
    doc.write_bytes(b"contenido real minimal para hash")

    estructura = {
        "sobre_1": {
            "titulo": "SOBRE 1",
            "carpeta": str(sobre),
            "documentos": [
                {"orden": 1, "nombre": "Propuesta", "archivo": "01_propuesta.docx"},
            ],
            "total_documentos": 1,
        }
    }
    pr = CompraNetPackager().pack(
        {
            "output_root": str(root),
            "rfc": rfc,
            "licitacion_id": lic,
            "estructura_sobres": estructura,
        }
    )
    assert pr.success
    assert pr.validation_passed
    assert pr.manifest_path and Path(pr.manifest_path).is_file()
    assert len(pr.files) == 1
    assert pr.files[0]["sha256"] and pr.files[0]["bytes"] > 0


def test_packager_rechaza_extension_invalida(tmp_path: Path) -> None:
    profile = _profile_from_fixture()
    root = tmp_path / "sess"
    sobre = root / "SOBRE_1_ADMINISTRATIVO"
    sobre.mkdir(parents=True)
    (sobre / "01_mal.exe").write_bytes(b"x")
    estructura = {
        "sobre_1": {
            "carpeta": str(sobre),
            "documentos": [{"orden": 1, "nombre": "m", "archivo": "01_mal.exe"}],
        }
    }
    pr = CompraNetPackager().pack(
        {
            "output_root": str(root),
            "rfc": str(profile.get("rfc") or "RFC_FIXTURE"),
            "licitacion_id": "LIC-01",
            "estructura_sobres": estructura,
        }
    )
    assert not pr.success
    assert any("Extensión no permitida" in e for e in pr.errors)


def test_packager_genera_zip_si_supera_umbral(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPRANET_PACKAGE_MAX_BYTES", "20")
    profile = _profile_from_fixture()
    root = tmp_path / "sess2"
    sobre = root / "SOBRE_2_TECNICO"
    sobre.mkdir(parents=True)
    (sobre / "01_gordo.docx").write_bytes(b"x" * 40)
    estructura = {
        "sobre_2": {
            "carpeta": str(sobre),
            "documentos": [{"orden": 1, "nombre": "t", "archivo": "01_gordo.docx"}],
        }
    }
    pr = CompraNetPackager().pack(
        {
            "output_root": str(root),
            "rfc": str(profile.get("rfc") or "RFC_FIXTURE"),
            "licitacion_id": "LIC-ZIP",
            "estructura_sobres": estructura,
        }
    )
    assert pr.success
    assert pr.zip_path and Path(pr.zip_path).is_file()


def test_build_pack_session_data_from_outputs_sin_hardcode() -> None:
    pdata = {
        "folder_raiz": "/data/outputs/x",
        "estructura_sobres": {"sobre_1": {"carpeta": "/tmp", "documentos": []}},
    }
    company = {"master_profile": {"rfc": "AAA010101AAA"}, "licitacion_id": "LIC-9"}
    s = build_pack_session_data_from_outputs("session-x", pdata, company)
    assert s["rfc"] == "AAA010101AAA"
    assert s["licitacion_id"] == "LIC-9"
    assert s["output_root"] == "/data/outputs/x"


def test_oracle_pkg01_con_fixture_real(tmp_path: Path) -> None:
    ov = _load_oracle_validator()
    fixture = json.loads((_FIXTURES / "compranet_pack_ok.json").read_text(encoding="utf-8"))
    case = {
        "case_id": "PKG01",
        "agent": "CompraNetPackager",
        "agent_contract_path": "packaging.validation_passed",
        "expected_now": {"type": "bool"},
        "criticality": "blocking",
    }
    r = ov.eval_pkg01(case, {"packager": fixture})
    assert r.estado_actual == "ok"


def test_packager_rendimiento_menor_200ms(tmp_path: Path) -> None:
    profile = _profile_from_fixture()
    root = tmp_path / "perf"
    estructura: dict = {}
    for i, key in enumerate(["sobre_1", "sobre_2", "sobre_3"], start=1):
        sd = root / f"SOBRE_{i}_X"
        sd.mkdir(parents=True)
        f = sd / f"01_f{i}.docx"
        f.write_bytes(b"doc")
        estructura[key] = {
            "carpeta": str(sd),
            "documentos": [{"orden": 1, "nombre": "n", "archivo": f.name}],
        }
    t0 = time.perf_counter()
    pr = CompraNetPackager().pack(
        {
            "output_root": str(root),
            "rfc": str(profile.get("rfc") or "RFC_FIXTURE"),
            "licitacion_id": "LIC-PERF",
            "estructura_sobres": estructura,
        }
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert pr.success
    assert elapsed_ms < 200.0


@pytest.mark.regression
def test_regression_compranet_pack_snapshot_session_documentada() -> None:
    """
    Regresión Oracle PKG01 con snapshot anónimo de ``stage_completed:compranet_pack``.

    Referencia de sesión de negocio (bases reales anonimizadas): ``la-51-gyn-051gyn025-n-8-2024_vigilancia``.
    """
    ov = _load_oracle_validator()
    fixture = json.loads((_FIXTURES / "compranet_pack_ok.json").read_text(encoding="utf-8"))
    case = next(
        c
        for c in json.loads(
            (Path(__file__).resolve().parents[1] / "tests" / "oracle_v1.0.1-runtime-final.json").read_text(
                encoding="utf-8"
            )
        )["cases"]
        if c.get("case_id") == "PKG01"
    )
    r = ov.eval_pkg01(case, {"packager": fixture})
    assert r.case_id == "PKG01"
    assert r.estado_actual == "ok"
