# Script para ejecutar tests localmente en Windows (PowerShell)
# ! IMPORTANTE: Ejecutar siempre desde el directorio 'backend/'
# Uso: .\scripts\run_tests.ps1

Write-Host "Iniciando Suite de Tests LicitAI (Backend)..." -ForegroundColor Cyan

# Aseguramos PYTHONPATH para que encuentre 'app'
$env:PYTHONPATH = ".;$env:PYTHONPATH"

# Ejecutamos pytest
python -m pytest tests/ --tb=short $args
