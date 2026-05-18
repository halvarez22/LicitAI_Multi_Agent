#Requires -Version 5.1
<#
.SYNOPSIS
    Arranca LicitAI en local sin depender de internet (sin pulls remotos).

.DESCRIPTION
    Pensado para demo o cliente sin red: verifica Docker, imágenes locales,
    levanta el stack con política de pull desactivada, espera salud del API
    y hace smoke al frontend. Opcionalmente comprueba Ollama en el host.

    Fallbacks:
    - Si falta una imagen base (postgres, redis, chroma), avisa claramente
      (hace falta haber hecho pull/build al menos una vez con red).
    - Si `up` falla, con -AllowLocalBuild intenta `build --pull never` y vuelve a subir
      (solo funciona si Docker tiene capas en caché).
    - Si Ollama no responde, la app sube igual; el aviso indica que el LLM no funcionará.

.PARAMETER ComposeFile
    Ruta al docker-compose.yml (por defecto: raíz del repo).

.PARAMETER AllowLocalBuild
    Tras un fallo de `up`, intenta construir imágenes sin pull remoto y reintenta.

.PARAMETER PrepareWithNetwork
    Modo preparación CON internet: pull + build + up. Ejecutar antes del día offline.

.PARAMETER SkipOllamaCheck
    No comprobar el servicio Ollama en el host.

.PARAMETER OllamaBaseUrl
    URL base de Ollama en el host (por defecto http://127.0.0.1:11434).

.PARAMETER BackendHealthUrl
    URL del healthcheck del API expuesto en el host.

.PARAMETER FrontendUrl
    URL del frontend en el host.

.PARAMETER HealthTimeoutSec
    Segundos máximos esperando respuesta 200 del backend.

.EXAMPLE
    .\scripts\start_licitai_offline.ps1

.EXAMPLE
    .\scripts\start_licitai_offline.ps1 -AllowLocalBuild

.EXAMPLE
    .\scripts\start_licitai_offline.ps1 -PrepareWithNetwork
#>
[CmdletBinding()]
param(
    [string] $ComposeFile = "",
    [switch] $AllowLocalBuild,
    [switch] $PrepareWithNetwork,
    [switch] $SkipOllamaCheck,
    [string] $OllamaBaseUrl = "http://127.0.0.1:11434",
    [string] $BackendHealthUrl = "http://127.0.0.1:8001/api/v1/health",
    [string] $FrontendUrl = "http://127.0.0.1:8504/",
    [int] $HealthTimeoutSec = 120
)

Set-StrictMode -Version Latest
# Docker escribe avisos en stderr (p. ej. compose `version` obsoleto); con Stop, PS5 los trata como error.
$ErrorActionPreference = "Continue"

function Write-Info([string] $Message) {
    Write-Host "[LicitAI] $Message" -ForegroundColor Cyan
}

function Write-Warn([string] $Message) {
    Write-Host "[LicitAI] $Message" -ForegroundColor Yellow
}

function Write-Err([string] $Message) {
    Write-Host "[LicitAI] $Message" -ForegroundColor Red
}

function Test-CommandExists([string] $Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory)]
        [string] $ComposePath,
        [Parameter(Mandatory)]
        [string[]] $ComposeArgs
    )
    # No usar el nombre $Args (variable automática de PowerShell).
    $all = @("-f", $ComposePath) + $ComposeArgs
    & docker compose @all
    return $LASTEXITCODE
}

# Raíz del repo (este script vive en /scripts)
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $ComposeFile) {
    $ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
}
if (-not (Test-Path -LiteralPath $ComposeFile)) {
    Write-Err "No se encontro docker-compose en: $ComposeFile"
    exit 2
}

Write-Info "Ruta raiz del repo: $RepoRoot"
Write-Info "Compose: $ComposeFile"

if (-not (Test-CommandExists "docker")) {
    Write-Err "Docker no esta en PATH. Instala Docker Desktop y vuelve a abrir la terminal."
    exit 3
}

Write-Info "Comprobando daemon de Docker..."
try {
    docker info 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw "docker info fallo" }
}
catch {
    Write-Err "Docker no responde. Arranca Docker Desktop y reintenta."
    exit 4
}

Push-Location $RepoRoot
try {
    if ($PrepareWithNetwork) {
        Write-Info "Modo -PrepareWithNetwork: pull + build + up (requiere internet)."
        $code = Invoke-Compose -ComposePath $ComposeFile -ComposeArgs @("pull")
        if ($code -ne 0) {
            Write-Warn "pull devolvio codigo $code; se continua con build/up."
        }
        $code = Invoke-Compose -ComposePath $ComposeFile -ComposeArgs @("build")
        if ($code -ne 0) {
            Write-Err "docker compose build fallo (codigo $code)."
            exit 5
        }
        $code = Invoke-Compose -ComposePath $ComposeFile -ComposeArgs @("up", "-d")
        if ($code -ne 0) {
            Write-Err "docker compose up -d fallo (codigo $code)."
            exit 6
        }
    }
    else {
        # Sin pulls remotos (Compose v2+)
        $env:COMPOSE_PULL_POLICY = "never"
        Write-Info "COMPOSE_PULL_POLICY=never (sin descarga de imagenes desde registries)."

        $imgOut = & docker compose -f $ComposeFile config --images 2>&1 | ForEach-Object { "$_" }
        $imagesRaw = $imgOut | Where-Object { $_ -notmatch '^time=' -and $_.Trim() -ne '' }
        if ($LASTEXITCODE -ne 0 -or -not $imagesRaw) {
            Write-Warn "No se pudo listar imagenes con compose config --images; se omite prechequeo."
        }
        else {
            $missing = @()
            foreach ($line in $imagesRaw) {
                $img = $line.Trim()
                if (-not $img) { continue }
                docker image inspect $img 1>$null 2>$null
                if ($LASTEXITCODE -ne 0) {
                    $missing += $img
                }
            }
            if ($missing.Count -gt 0) {
                Write-Warn "Faltan imagenes locales (sin red no se pueden bajar desde registry):"
                $missing | ForEach-Object { Write-Warn "  - $_" }
                Write-Warn "Ejecuta una vez con red: .\scripts\start_licitai_offline.ps1 -PrepareWithNetwork"
                if (-not $AllowLocalBuild) {
                    Write-Warn "O reintenta con -AllowLocalBuild si tienes capas Docker en cache para construir."
                }
            }
        }

        Write-Info "docker compose up -d..."
        $code = Invoke-Compose -ComposePath $ComposeFile -ComposeArgs @("up", "-d")
        if ($code -ne 0 -and $AllowLocalBuild) {
            Write-Warn "up fallo (codigo $code). Fallback: build sin pull remoto..."
            $code = Invoke-Compose -ComposePath $ComposeFile -ComposeArgs @("build", "--pull", "never")
            if ($code -ne 0) {
                Write-Err "build --pull never fallo (codigo $code). Sin cache no hay build offline."
                exit 7
            }
            $code = Invoke-Compose -ComposePath $ComposeFile -ComposeArgs @("up", "-d")
        }
        if ($code -ne 0) {
            Write-Err "docker compose up -d fallo (codigo $code)."
            exit 8
        }
    }

    Write-Info "Esperando API ($BackendHealthUrl) hasta $HealthTimeoutSec s..."
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSec)
    $ok = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $BackendHealthUrl -TimeoutSec 5
            if ($r.StatusCode -eq 200) {
                $ok = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $ok) {
        Write-Err "El backend no respondio 200 a tiempo. Revisa: docker compose logs backend"
        exit 9
    }
    Write-Info "Backend OK."

    try {
        $f = Invoke-WebRequest -UseBasicParsing -Uri $FrontendUrl -TimeoutSec 10
        if ($f.StatusCode -eq 200) {
            Write-Info "Frontend OK ($FrontendUrl)."
        }
        else {
            Write-Warn "Frontend respondio $($f.StatusCode). Abre la URL en el navegador para validar."
        }
    }
    catch {
        Write-Warn "No se pudo comprobar el frontend ($FrontendUrl): $($_.Exception.Message)"
    }

    if (-not $SkipOllamaCheck) {
        try {
            $o = Invoke-WebRequest -UseBasicParsing -Uri "$OllamaBaseUrl/api/tags" -TimeoutSec 5
            if ($o.StatusCode -eq 200) {
                Write-Info "Ollama responde en $OllamaBaseUrl (modelos locales disponibles para el API)."
            }
        }
        catch {
            Write-Warn "Ollama no responde en $OllamaBaseUrl. El stack Docker esta arriba, pero analisis/chat que usen LLM fallaran hasta que Ollama este en marcha en el host."
            Write-Warn "Fallback: inicia Ollama en Windows y asegurate de tener el modelo ya descargado (ollama pull ... con red antes)."
        }
    }

    Write-Host ""
    Write-Info "Listo. UI: $FrontendUrl  |  API health: $BackendHealthUrl"
    Write-Warn "Sin internet: las fuentes Google en index.html/index.css pueden no cargar; la UI usa fuentes del sistema."
    Write-Info "Parar stack:  docker compose -f `"$ComposeFile`" down"
}
finally {
    Pop-Location
    Remove-Item Env:COMPOSE_PULL_POLICY -ErrorAction SilentlyContinue
}

exit 0
