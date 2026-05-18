# =============================================================================
# E2E corporativo + licitación — PARA LA PRUEBA (una sola ejecución)
# =============================================================================
# Requisitos: API en http://127.0.0.1:8001 (docker-compose o local).
#
# Uso (raíz del repo):
#   powershell -ExecutionPolicy Bypass -File .\scripts\e2e_corporate_PARA_LA_PRUEBA.ps1
#
# Modo rápido (sin Acta de 7MB, solo CIF + logo; orquestador igual con bases+costos):
#   powershell -ExecutionPolicy Bypass -File .\scripts\e2e_corporate_PARA_LA_PRUEBA.ps1 -Rapido
#
# Salida: JSON + MD en .\data\e2e_outputs\ y copia en el Escritorio (si existe).
# =============================================================================

param(
    [switch]$Rapido
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root "backend"
$OutDir = Join-Path $Root "data\e2e_outputs"
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

$env:PYTHONUNBUFFERED = "1"
$env:E2E_API_URL = "http://127.0.0.1:8001/api/v1"
$env:E2E_REPORT_DESKTOP = "1"
$env:E2E_POLL_SEC = "5"

if ($Rapido) {
    Write-Host "[PRUEBA] Modo RAPIDO: sin Acta Constitutiva (CIF + logo + bases + costos + orquestador)."
    $env:E2E_CORP_MINIMAL = "1"
    $env:E2E_COMPANY_ANALYZE_TIMEOUT_SEC = "900"
    $env:E2E_JOB_TIMEOUT_SEC = "7200"
} else {
    Write-Host "[PRUEBA] Modo COMPLETO: Acta + CIF + logo (OCR del acta puede tardar mucho)."
    $env:E2E_CORP_MINIMAL = "0"
    $env:E2E_COMPANY_ANALYZE_TIMEOUT_SEC = "7200"
    $env:E2E_JOB_TIMEOUT_SEC = "7200"
}

Write-Host "[PRUEBA] API: $($env:E2E_API_URL)"
Write-Host "[PRUEBA] Logs adicionales: $OutDir\e2e_corporate_trace_*.log (si el script Python escribe trace)"
Push-Location $Backend
try {
    python scripts\e2e_corporate_licitacion_desatendido.py
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host "[PRUEBA] Codigo salida Python: $code (0=exito segun script)"
exit $code
