#!/bin/bash
# Script para ejecutar tests localmente en Linux/macOS
# Uso: ./scripts/run_tests.sh

echo -e "\033[0;36mIniciando Suite de Tests LicitAI (Backend)...\033[0m"

# Aseguramos PYTHONPATH para que encuentre 'app'
export PYTHONPATH=$PYTHONPATH:.

# Ejecutamos pytest
python -m pytest tests/ --tb=short "$@"
