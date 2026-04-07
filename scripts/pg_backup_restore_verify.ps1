#Requires -Version 5.1
<#
.SYNOPSIS
    Backup lógico (pg_dump) de PostgreSQL y verificación por restore a una base temporal.

.DESCRIPTION
    Pensado para el contenedor `database` del docker-compose del proyecto.
    Condición GO Beta Estable: evidenciar que el dump es restaurable y que los datos coinciden.

.PARAMETER ComposeProject
    Prefijo del nombre del contenedor (por defecto se detecta el contenedor *database*).

.PARAMETER BackupDir
    Carpeta donde guardar el .sql (por defecto repo/backups/staging_evidence).

.EXAMPLE
    .\scripts\pg_backup_restore_verify.ps1
#>
param(
    [string]$BackupDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "backups\staging_evidence"),
    [string]$ContainerName = ""
)

$ErrorActionPreference = "Stop"

function Resolve-DatabaseContainer {
    param([string]$Name)
    if ($Name) { return $Name }
    $id = docker ps --filter "name=database" --format "{{.Names}}" | Select-Object -First 1
    if (-not $id) { throw "No se encontró contenedor con nombre *database*. Levanta el stack: docker compose up -d" }
    return $id.Trim()
}

$container = Resolve-DatabaseContainer $ContainerName
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$dumpFile = Join-Path $BackupDir "licitaciones_${ts}.sql"
$evidenceFile = Join-Path $BackupDir "EVIDENCIA_RESTORE_${ts}.txt"

Write-Host "[1/4] pg_dump -> $dumpFile" -ForegroundColor Cyan
docker exec $container pg_dump -U postgres -d licitaciones --no-owner --clean --if-exists 2>$null | Out-File -FilePath $dumpFile -Encoding utf8
$len = (Get-Item $dumpFile).Length
if ($len -lt 1024) { throw "Dump sospechosamente pequeño ($len bytes). Revisa logs de pg_dump." }

Write-Host "[2/4] CREATE DATABASE licitaciones_restore_verify (drop si existe)" -ForegroundColor Cyan
docker exec $container psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS licitaciones_restore_verify;" | Out-Null
docker exec $container psql -U postgres -d postgres -c "CREATE DATABASE licitaciones_restore_verify;" | Out-Null

Write-Host "[3/4] Restore (pipe) -> licitaciones_restore_verify" -ForegroundColor Cyan
Get-Content -Raw -LiteralPath $dumpFile -Encoding UTF8 | docker exec -i $container psql -U postgres -d licitaciones_restore_verify -v ON_ERROR_STOP=1 | Out-Null

Write-Host "[4/4] Comparar conteos por tabla (public)" -ForegroundColor Cyan
$tables = docker exec $container psql -U postgres -d licitaciones -t -A -c `
    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
$tables = $tables -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }

$lines = @()
$lines += "Fecha UTC: $(Get-Date -Format u)"
$lines += "Contenedor: $container"
$lines += "Dump: $dumpFile ($len bytes)"
$lines += ""
$allOk = $true
foreach ($t in $tables) {
    $o = (docker exec $container psql -U postgres -d licitaciones -t -A -c "SELECT count(*) FROM public.`"$t`";").Trim()
    $r = (docker exec $container psql -U postgres -d licitaciones_restore_verify -t -A -c "SELECT count(*) FROM public.`"$t`";").Trim()
    $ok = ($o -eq $r)
    if (-not $ok) { $allOk = $false }
    $lines += "TABLE $t orig=$o restore=$r OK=$ok"
}

$lines += ""
$lines += "RESULTADO_GLOBAL: $(if ($allOk) { 'PASS' } else { 'FAIL' })"
$lines | Set-Content -Path $evidenceFile -Encoding UTF8

Write-Host $lines
if (-not $allOk) { throw "Verificación de conteos falló. Ver $evidenceFile" }
Write-Host "OK. Evidencia: $evidenceFile" -ForegroundColor Green
