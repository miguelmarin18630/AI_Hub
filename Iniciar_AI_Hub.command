#!/bin/bash
# Abre AI Hub en macOS (o Linux) con python3.
cd "$(dirname "$0")" || exit 1

PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "No encuentro python3. Instala Python 3.10+ desde https://www.python.org/downloads/macos/"
  echo "o con: brew install python-tk"
  read -r -p "Pulsa Enter para cerrar…" _
  exit 1
fi

"$PY" -m compileall aihub >/dev/null 2>&1 || true
"$PY" AIHub.pyw "$@"
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "AI Hub terminó con un error (código $status)."
  read -r -p "Pulsa Enter para cerrar…" _
fi
exit $status