#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${PROJECT_DIRECTORY}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Fehler: Keine virtuelle Umgebung unter ${PROJECT_DIRECTORY}/.venv gefunden." >&2
    echo "Erstelle sie mit: python3 -m venv .venv" >&2
    exit 1
fi

if ! "${VENV_PYTHON}" -c "import PyInstaller" 2>/dev/null; then
    echo "Fehler: PyInstaller ist in der virtuellen Umgebung nicht installiert." >&2
    echo "Installiere die Abhängigkeiten mit: .venv/bin/python -m pip install -r requirements.txt" >&2
    exit 1
fi

cd "${PROJECT_DIRECTORY}"
"${VENV_PYTHON}" -m PyInstaller --clean --noconfirm bildbetrachter.spec

if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Fertig: ${PROJECT_DIRECTORY}/dist/BildBlick.app"
else
    echo "Fertig: ${PROJECT_DIRECTORY}/dist/BildBlick"
fi
