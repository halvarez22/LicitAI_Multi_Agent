# E2E definitivo desatendido: pytest + orquestador (PDF sintetico + poll job) + 3 bases reales (inteligencia).
# Uso (raíz repo):
#   powershell -ExecutionPolicy Bypass -File .\scripts\e2e_definitivo_unattended.ps1
# Salida: data/e2e_outputs/e2e_definitivo_YYYYMMDD_HHMMSS.log y JSONs en backend/scripts/
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$OutDir = Join-Path $Root "data\e2e_outputs"
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $OutDir "e2e_definitivo_$Stamp.log"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "=== INICIO E2E DEFINITIVO $Stamp ==="
Write-Log "Log: $Log"

$env:E2E_API_URL = "http://127.0.0.1:8001/api/v1"

Write-Log "Fase 1/3: pytest dentro del contenedor backend (mismo entorno que produccion)"
Push-Location $Root
try {
    # El Python del host puede traer httpx/starlette incompatibles; en Docker coincide con requirements.txt
    $outPy = docker compose exec -T backend python -m pytest tests -q --tb=short 2>&1
    $codePytest = $LASTEXITCODE
    $outPy | ForEach-Object { Write-Log $_ }
} finally {
    Pop-Location
}
Write-Log "pytest (docker) exit code: $codePytest"

Write-Log "Fase 2/3: e2e_orchestrator_run.py (sintetico + jobs)"
$env:E2E_ORCH_TIMEOUT_SEC = "3600"
Push-Location (Join-Path $Root "backend")
try {
    $outOr = python scripts\e2e_orchestrator_run.py 2>&1
    $codeOrch = $LASTEXITCODE
    $outOr | ForEach-Object { Write-Log $_ }
} finally {
    Pop-Location
}
Write-Log "orchestrator E2E exit code: $codeOrch"

Write-Log "Fase 3/3: e2e_bases_inteligencia.py (max 3 PDFs, timeout job 7200s c/u)"
$env:E2E_MAX_FILES = "3"
$env:E2E_JOB_TIMEOUT_SEC = "7200"
$env:E2E_POLL_SEC = "5"
Push-Location (Join-Path $Root "backend")
try {
    $outIn = python scripts\e2e_bases_inteligencia.py 2>&1
    $codeIntel = $LASTEXITCODE
    $outIn | ForEach-Object { Write-Log $_ }
} finally {
    Pop-Location
}
Write-Log "inteligencia E2E exit code: $codeIntel"

$final = 0
if ($codePytest -ne 0) { $final = 1 }
if ($codeOrch -ne 0) { $final = 1 }
if ($codeIntel -ne 0) { $final = 1 }
Write-Log "=== FIN E2E DEFINITIVO - exit agregado: $final (0=todo OK) ==="
exit $final
