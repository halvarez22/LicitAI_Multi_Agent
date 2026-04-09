"""Pruebas del escaneo de agnosticismo y del perfil económico multi-vertical."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.economic_validation.profiles import detect_profile


def _load_run_agnosticism():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_agnosticism_validation.py"
    spec = importlib.util.spec_from_file_location("run_agnosticism_validation", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_detect_profile_sector_salud_sin_issste_en_nombre() -> None:
    assert detect_profile({}, "Licitación servicios de salud regional 2026") == "health_sector_annex_like"


def test_detect_profile_imss_en_reglas() -> None:
    assert detect_profile({"modalidad": "Concurso IMSS obra civil"}, "") == "health_sector_annex_like"


def test_scan_app_tree_critical_on_session_slug(tmp_path: Path) -> None:
    mod = _load_run_agnosticism()
    app = tmp_path / "app"
    app.mkdir()
    (app / "leak.py").write_text('SESSION = "la-51-gyn-099"\n', encoding="utf-8")
    critical, _review = mod.scan_app_tree(app)
    assert len(critical) == 1
    assert "leak.py" in critical[0]


@pytest.mark.regression
def test_scan_app_tree_clean_on_real_backend_app() -> None:
    """Regresión F: ``app/`` sin slugs de sesión documentada ni acoplamiento crítico escaneado."""
    mod = _load_run_agnosticism()
    backend = Path(__file__).resolve().parents[1]
    critical, _review = mod.scan_app_tree(backend / "app")
    assert critical == []
