"""
Empaquetador determinista alineado a convenciones típicas CompraNet (sobres, nombres, manifiesto).

Sin LLM: solo reglas explícitas, rutas reales y variables tomadas de ``session_data``
(``rfc``, ``licitacion_id``, rutas de disco). Extensiones y límites configurables vía variables
de entorno.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _env_csv(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default).strip()
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _sanitize_token(value: str, max_len: int = 96) -> str:
    """Normaliza token para nombres de archivo (sin datos inventados)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] if s else "NA"


def _sobre_label_from_key(sobre_key: str, carpeta: str) -> str:
    """Mapea claves/carpetas del DocumentPackager a etiqueta CompraNet."""
    k = (sobre_key or "").lower()
    c = (carpeta or "").upper()
    if "sobre_1" in k or "ADMINISTRATIVO" in c or "COMPLEMENT" in c:
        return "SobreComplementaria"
    if "sobre_2" in k or "TECNICO" in c or "TÉCNICO" in carpeta.upper():
        return "SobreTecnica"
    if "sobre_3" in k or "ECONOMICO" in c or "ECONÓMICO" in carpeta.upper():
        return "SobreEconomica"
    return f"Sobre_{_sanitize_token(sobre_key, 40)}"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PackResult:
    """Resultado de ``CompraNetPackager.pack``."""

    success: bool
    errors: List[str] = field(default_factory=list)
    validation_passed: bool = False
    manifest_path: Optional[str] = None
    zip_path: Optional[str] = None
    staged_root: Optional[str] = None
    files: List[Dict[str, Any]] = field(default_factory=list)
    total_bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_passed": self.validation_passed,
            "success": self.success,
            "errors": list(self.errors),
            "manifest_path": self.manifest_path,
            "manifest_sha256_path": self.manifest_path,
            "zip_path": self.zip_path,
            "staged_root": self.staged_root,
            "files": list(self.files),
            "total_bytes": self.total_bytes,
        }


class CompraNetPackager:
    """
    Valida extensiones, estructura de sobres, nombres canónicos y genera manifiesto SHA-256.

    Variables de entorno (opcionales):
    - ``COMPRANET_ALLOWED_EXT``: extensiones permitidas, separadas por coma (puntos incluidos).
    - ``COMPRANET_PACKAGE_MAX_BYTES``: umbral para generar ZIP adicional (default 50 MiB).
    """

    def __init__(self) -> None:
        exts = _env_csv("COMPRANET_ALLOWED_EXT", ".doc,.docx,.pdf,.jpg,.jpeg,.png,.xlsx")
        self._allowed = {e if e.startswith(".") else f".{e}" for e in exts}
        self._max_bytes = int(os.getenv("COMPRANET_PACKAGE_MAX_BYTES", str(50 * 1024 * 1024)))

    def pack(self, session_data: Dict[str, Any]) -> PackResult:
        """
        Empaqueta y valida la propuesta bajo ``output_root`` según ``estructura_sobres``.

        Args:
            session_data: Debe incluir al menos ``output_root``, ``rfc``, ``licitacion_id`` y
                ``estructura_sobres`` (salida del DocumentPackager) o ``sobres`` explícitos.

        Returns:
            PackResult con rutas al manifiesto y, si aplica, al ZIP.
        """
        errors: List[str] = []
        output_root = session_data.get("output_root") or session_data.get("folder_raiz")
        rfc = str(session_data.get("rfc") or "").strip()
        lic = str(session_data.get("licitacion_id") or session_data.get("session_id") or "").strip()
        estructura: Dict[str, Any] = session_data.get("estructura_sobres") or {}

        if not output_root:
            return PackResult(success=False, errors=["Falta output_root/folder_raiz en session_data."])
        if not rfc:
            return PackResult(success=False, errors=["Falta RFC en session_data (requerido para nombrado)."])
        if not lic:
            return PackResult(success=False, errors=["Falta licitacion_id o session_id."])

        root = Path(str(output_root))
        if not root.is_dir():
            return PackResult(success=False, errors=[f"No existe directorio de salida: {root}"])

        rfc_s = _sanitize_token(rfc)
        lic_s = _sanitize_token(lic)

        staged = root / "_compranet_validated"
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True, exist_ok=True)

        collected: List[Tuple[Path, str, str]] = []  # src, sobre_label, seq_name

        if estructura:
            for sobre_key, info in estructura.items():
                if not isinstance(info, dict):
                    continue
                carpeta = str(info.get("carpeta") or "")
                label = _sobre_label_from_key(str(sobre_key), carpeta)
                sobre_dir = Path(carpeta) if carpeta else root / str(sobre_key)
                docs = info.get("documentos") or []
                if not isinstance(docs, list):
                    continue
                for doc in docs:
                    if not isinstance(doc, dict):
                        continue
                    archivo = doc.get("archivo")
                    if not archivo:
                        continue
                    src = sobre_dir / str(archivo)
                    if not src.is_file():
                        errors.append(f"Archivo faltante: {src}")
                        continue
                    ext = src.suffix.lower()
                    if ext not in self._allowed:
                        errors.append(f"Extensión no permitida ({ext}): {src.name}")
                        continue
                    seq = f"{int(doc.get('orden', 0)):02d}" if str(doc.get("orden", "")).isdigit() else "00"
                    canonical = f"{rfc_s}_{lic_s}_{label}_{seq}{ext}"
                    collected.append((src, label, canonical))
        else:
            # Recorrido por carpetas estándar si no hay estructura en memoria
            for name, label in (
                ("SOBRE_1_ADMINISTRATIVO", "SobreComplementaria"),
                ("SOBRE_2_TECNICO", "SobreTecnica"),
                ("SOBRE_3_ECONOMICO", "SobreEconomica"),
            ):
                sd = root / name
                if not sd.is_dir():
                    continue
                for idx, src in enumerate(sorted(sd.iterdir()), start=1):
                    if not src.is_file() or src.name.startswith("00_CARATULA"):
                        continue
                    ext = src.suffix.lower()
                    if ext not in self._allowed:
                        errors.append(f"Extensión no permitida ({ext}): {src.name}")
                        continue
                    # Nombre canónico CompraNet: RFC + id licitación + sobre + orden
                    canonical = f"{rfc_s}_{lic_s}_{label}_{idx:02d}{ext}"
                    collected.append((src, label, canonical))

        if errors:
            return PackResult(success=False, errors=errors, validation_passed=False)

        if not collected:
            return PackResult(
                success=False,
                errors=["No hay archivos válidos para empaquetar en los sobres."],
                validation_passed=False,
            )

        # Copia con nombre canónico por sobre
        for src, label, canonical in collected:
            dest_dir = staged / label
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_dir / canonical)

        files_meta: List[Dict[str, Any]] = []
        total = 0
        for path in sorted(staged.rglob("*")):
            if not path.is_file() or path.name == "MANIFIESTO_SHA256.json":
                continue
            rel = str(path.relative_to(staged)).replace("\\", "/")
            digest = _file_sha256(path)
            sz = path.stat().st_size
            total += sz
            files_meta.append(
                {
                    "path": rel,
                    "sha256": digest,
                    "bytes": sz,
                }
            )

        manifest = {
            "algorithm": "SHA-256",
            "rfc_token": rfc_s,
            "licitacion_token": lic_s,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "files": files_meta,
            "total_bytes": total,
            "zip_compatible": "ZIP_DEFLATED level 6 (stdlib zipfile)",
        }
        manifest_path = staged / "MANIFIESTO_SHA256.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        zip_path: Optional[Path] = None
        if total > self._max_bytes:
            zip_name = f"{lic_s}_CompraNet_bundle.zip"
            zip_path = root / zip_name
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for path in staged.rglob("*"):
                    if path.is_file():
                        arc = path.relative_to(staged).as_posix()
                        zf.write(path, arcname=arc)

        return PackResult(
            success=True,
            errors=[],
            validation_passed=True,
            manifest_path=str(manifest_path.resolve()),
            zip_path=str(zip_path.resolve()) if zip_path else None,
            staged_root=str(staged.resolve()),
            files=files_meta,
            total_bytes=total,
        )

def build_pack_session_data_from_outputs(
    session_id: str,
    packager_agent_data: Dict[str, Any],
    company_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Construye ``session_data`` para ``CompraNetPackager`` a partir del ``AgentOutput.data``
    del DocumentPackager y del perfil de empresa (sin valores fijos).
    """
    profile = company_data.get("master_profile") if isinstance(company_data, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    rfc = str(profile.get("rfc") or "").strip()
    lic = (
        str(company_data.get("licitacion_id") or "").strip()
        or str(company_data.get("numero_licitacion") or "").strip()
        or session_id
    )
    return {
        "session_id": session_id,
        "output_root": packager_agent_data.get("folder_raiz"),
        "folder_raiz": packager_agent_data.get("folder_raiz"),
        "rfc": rfc,
        "licitacion_id": lic,
        "estructura_sobres": packager_agent_data.get("estructura_sobres") or {},
    }
