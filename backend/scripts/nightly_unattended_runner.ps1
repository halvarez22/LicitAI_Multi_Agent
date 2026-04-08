param(
    [string]$SessionId = "la-51-gyn-051gyn025-n-8-2024_vigilancia",
    [string]$ApiBase = "http://127.0.0.1:8001/api/v1",
    [int]$Retries = 2,
    [int]$PollSec = 5,
    [int]$MaxWaitSec = 10800
)

$ErrorActionPreference = "Stop"
# Evita que salida STDERR informativa de comandos nativos (python)
# se trate como excepción cuando el exit code es 0.
$PSNativeCommandUseErrorActionPreference = $false

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts | $Message" | Tee-Object -FilePath $script:LogFile -Append
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Split-Path -Parent $scriptDir
$repoDir = Split-Path -Parent $backendDir
$logsDir = Join-Path $repoDir "logs"
$outDir = Join-Path $repoDir "out"
$oracleRealDir = Join-Path $outDir "oracle_real"
$script:LogFile = Join-Path $logsDir "nightly_unattended.log"

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
New-Item -ItemType Directory -Path $oracleRealDir -Force | Out-Null

Set-Location $backendDir

Write-Log "=== Inicio runner nocturno desatendido ==="
Write-Log "SessionId=$SessionId ApiBase=$ApiBase Retries=$Retries PollSec=$PollSec MaxWaitSec=$MaxWaitSec"

for ($attempt = 1; $attempt -le $Retries; $attempt++) {
    Write-Log "Intento $attempt/${Retries}: lanzando E2E monitor"

    $env:E2E_API_BASE = $ApiBase
    $env:E2E_SESSION_ID = $SessionId
    $env:E2E_POLL_SEC = "$PollSec"
    $env:E2E_MAX_WAIT_SEC = "$MaxWaitSec"
    $env:E2E_LOG_COMPLIANCE_TICKS = "1"

    python -u scripts/e2e_monitor_job.py 2>&1 | Tee-Object -FilePath $script:LogFile -Append
    $e2eExit = $LASTEXITCODE
    Write-Log "E2E exit code=$e2eExit"

    if ($e2eExit -ne 0) {
        Write-Log "E2E no completó OK. Esperando 60s para reintento."
        Start-Sleep -Seconds 60
        continue
    }

    Write-Log "Exportando inputs Oracle..."
    python scripts/export_oracle_inputs.py --session-id $SessionId --out ..\out\oracle_real 2>&1 | Tee-Object -FilePath $script:LogFile -Append
    $exportExit = $LASTEXITCODE
    Write-Log "Export exit code=$exportExit"
    if ($exportExit -ne 0) {
        Write-Log "Export falló. Reintento en 60s."
        Start-Sleep -Seconds 60
        continue
    }

    Write-Log "Ejecutando Oracle validator..."
    python scripts/run_oracle.py --analysis ..\out\oracle_real\analysis.json --compliance ..\out\oracle_real\compliance.json --economic ..\out\oracle_real\economic.json --out ..\out 2>&1 | Tee-Object -FilePath $script:LogFile -Append
    $oracleExit = $LASTEXITCODE
    Write-Log "Oracle exit code=$oracleExit"
    if ($oracleExit -ne 0) {
        Write-Log "Oracle reportó salida no-cero. Reintento en 60s."
        Start-Sleep -Seconds 60
        continue
    }

    Write-Log "Corriendo pytest gate..."
    python -m pytest tests/test_fase5_experience_pipeline.py tests/test_agent_hardening_v4.py tests/test_oracle.py -q --tb=no 2>&1 | Tee-Object -FilePath $script:LogFile -Append
    $pytestExit = $LASTEXITCODE
    Write-Log "Pytest exit code=$pytestExit"

    if ($pytestExit -eq 0) {
        Write-Log "SUCCESS: corrida nocturna validada (E2E+Oracle+pytest)."
        exit 0
    }

    Write-Log "Pytest falló. Reintento en 60s."
    Start-Sleep -Seconds 60
}

Write-Log "FIN con fallo: agotados los reintentos."
exit 1
