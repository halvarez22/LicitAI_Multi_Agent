# Crea los dos PRs de liberacion (pytest + Item D). Requiere: gh auth login
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "Instala GitHub CLI: https://cli.github.com/"
}

gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ejecuta primero: gh auth login --web" -ForegroundColor Yellow
    exit 1
}

$pr1Body = @"
## Summary
- Restaura ``ValidationReport``, ``Conflict`` y ``ValidatorAgent`` en ``validator.py`` (Fase 3 / backtracking).
- Actualiza ``test_downloads_zip_flag.py`` a ``delivery_zip_available`` + ``_compranet_validated``.

## Resultado
- ``pytest tests --collect-only``: 1999 tests, 0 errores de coleccion
- Tests de los 3 archivos: 9/9 PASS en Docker

## Test plan
- [x] ``docker compose exec -e ENVIRONMENT=test backend python -m pytest tests/test_downloads_zip_flag.py tests/test_fase3_critic.py tests/test_fase3_validator.py -q``
- [x] ``docker compose exec backend python -m pytest tests --collect-only -q``
"@

$pr2Body = @"
## Summary
- Matriz de captura universal: ``provenance_ui`` por celda, ``capture_matrix_meta``, resumen X de Y.
- Gate D.23 por ``source_doc_id`` + catalogo (fallback nombre solo legacy).
- Convergencia tri-canal UI | CSV | TSV; regresion ZB; UI ``CaptureMatrixPanel`` con badges.

## Test plan
- [x] Bundle Item D: 36/36 PASS en Docker
- [x] ``e2e_agenda_hitl_complete.py`` incluye tri_channel y capture_matrix_meta

## Merge
Recomendado despues del PR ``fix/pytest-collection-errors`` (sin conflictos de archivos).
"@

Write-Host "Creando PR 1: fix/pytest-collection-errors..." -ForegroundColor Cyan
$pr1Url = gh pr create `
    --base main `
    --head fix/pytest-collection-errors `
    --title "fix(tests): pytest sin errores de coleccion" `
    --body $pr1Body 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host $pr1Url
    Write-Host "PR1 puede existir ya. Lista: gh pr list --head fix/pytest-collection-errors" -ForegroundColor Yellow
} else {
    Write-Host "PR1: $pr1Url" -ForegroundColor Green
}

Write-Host "Creando PR 2: feat/item-d-matriz-economica-universal..." -ForegroundColor Cyan
$pr2Url = gh pr create `
    --base main `
    --head feat/item-d-matriz-economica-universal `
    --title "feat(item-d): matriz economica universal HITL" `
    --body $pr2Body 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host $pr2Url
    Write-Host "PR2 puede existir ya. Lista: gh pr list --head feat/item-d-matriz-economica-universal" -ForegroundColor Yellow
} else {
    Write-Host "PR2: $pr2Url" -ForegroundColor Green
}

Write-Host "`nListo. Orden de merge: PR1 (pytest) -> PR2 (Item D)" -ForegroundColor Green
