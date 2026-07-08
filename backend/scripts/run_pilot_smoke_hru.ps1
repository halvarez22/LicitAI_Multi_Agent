# Ejecuta suite smoke F4 (HRU) en VM piloto on-premise.
# Uso: .\backend\scripts\run_pilot_smoke_hru.ps1

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path -Parent $PSScriptRoot
Set-Location $BackendRoot
$env:PYTHONPATH = "."
Write-Host "[F4] Smoke piloto HRU..." -ForegroundColor Cyan
python scripts/smoke_pilot_onprem_hru.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[F4] OK" -ForegroundColor Green
