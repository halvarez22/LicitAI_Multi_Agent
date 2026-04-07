# Prueba E2E API: bases reales (nativo + escaneado)
# Uso: desde la raiz del repo licitaciones-ai:
#   powershell -ExecutionPolicy Bypass -File .\scripts\e2e-run-bases-reales.ps1
$ErrorActionPreference = "Stop"
$BaseDir = "C:\LicitAI_Multi_Agent\bases y convocatorias de prueba"
$Api = "http://127.0.0.1:8001/api/v1"
$OutDir = Join-Path $PSScriptRoot "..\data\e2e_outputs"
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

function Invoke-E2E-ForPdf {
    param(
        [string]$Label,
        [string]$PdfFileName,
        [int]$ProcessTimeoutSec = 3600
    )
    $pdfPath = Join-Path $BaseDir $PdfFileName
    if (-not (Test-Path -LiteralPath $pdfPath)) {
        Write-Host "FALTA ARCHIVO: $pdfPath" -ForegroundColor Red
        return
    }
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $sessionName = [uri]::EscapeDataString("E2E $Label $stamp")
    Write-Host "`n=== $Label ===" -ForegroundColor Cyan
    Write-Host "Archivo: $PdfFileName ($( [math]::Round((Get-Item -LiteralPath $pdfPath).Length / 1MB, 2) ) MB)"

    $create = curl.exe -s -X POST "$Api/sessions/create?name=$sessionName"
    $createObj = $create | ConvertFrom-Json
    if (-not $createObj.success) {
        Write-Host "Create session failed: $create" -ForegroundColor Red
        return
    }
    $sid = $createObj.data.session_id
    Write-Host "session_id: $sid"

    Write-Host "Subiendo..."
    $up = curl.exe -s -X POST "$Api/upload/upload" -F "file=@$pdfPath" -F "session_id=$sid" --max-time 7200
    $upObj = $up | ConvertFrom-Json
    if (-not $upObj.success) {
        Write-Host "Upload failed: $up" -ForegroundColor Red
        return
    }
    Write-Host "doc_id: $($upObj.data.doc_id)"

    $safeLabel = $Label -replace '\s','_'
    $processOut = Join-Path $OutDir "process_${safeLabel}_$stamp.json"
    $bodyPath = Join-Path $OutDir "body_process_${safeLabel}_$stamp.json"
    $bodyObj = @{ session_id = $sid; company_id = $null; company_data = @{ mode = "analysis_only" } } | ConvertTo-Json -Compress -Depth 5
    # UTF-8 sin BOM (evita 422 en FastAPI si se usa archivo)
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($bodyPath, $bodyObj, $utf8NoBom)
    Write-Host "agents/process (timeout ${ProcessTimeoutSec}s)..."
    curl.exe -s -X POST "$Api/agents/process" -H "Content-Type: application/json" --data-binary "@$bodyPath" -o $processOut --max-time $ProcessTimeoutSec -w "`nHTTP:%{http_code}`n"
    if (Test-Path $processOut) {
        Write-Host "Respuesta guardada: $processOut"
        $raw = Get-Content -LiteralPath $processOut -Raw -Encoding UTF8
        try {
            $pj = $raw | ConvertFrom-Json
            Write-Host "status API: $($pj.status)"
        } catch { Write-Host "(JSON parcial o error al parsear)" }
    }

    $dict = curl.exe -s "$Api/sessions/$sid/dictamen"
    Set-Content -Path (Join-Path $OutDir "dictamen_${safeLabel}_$stamp.json") -Value $dict -Encoding UTF8
    Write-Host "dictamen GET guardado (suele estar vacío si no hubo POST desde UI)."

    $list = curl.exe -s "$Api/upload/list/$sid"
    Set-Content -Path (Join-Path $OutDir "documents_${safeLabel}_$stamp.json") -Value $list -Encoding UTF8
}

Write-Host "Health:" -ForegroundColor Yellow
curl.exe -s "http://127.0.0.1:8001/api/v1/health"
Write-Host ""

# 1) Texto nativo
Invoke-E2E-ForPdf -Label "Nativo VIGILANCIA" -PdfFileName "LA-51-GYN-051GYN025-N-8-2024 VIGILANCIA.pdf" -ProcessTimeoutSec 3600

# 2) Escaneado (archivo grande)
Invoke-E2E-ForPdf -Label "Escaneado OPM" -PdfFileName "Bases licitacion OPM-001-2026.pdf" -ProcessTimeoutSec 7200

Write-Host "`nListo. Salida en: $OutDir" -ForegroundColor Green
