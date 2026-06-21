#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
if [ -x "gateway/.venv/bin/python" ]; then
  PYTHON_BIN="gateway/.venv/bin/python"
elif [ -x "gateway/.venv/Scripts/python.exe" ]; then
  PYTHON_BIN="gateway/.venv/Scripts/python.exe"
fi

echo "Python: $($PYTHON_BIN --version)"
$PYTHON_BIN -m py_compile gateway/*.py

if command -v node >/dev/null 2>&1; then
  node --check gateway/web/app.js
else
  echo "Skipping JS syntax check: node not found"
fi

PIO_BIN="$(sh scripts/find-platformio.sh 2>/dev/null || true)"

if [ -n "$PIO_BIN" ]; then
  (cd firmware/xiao_nrf52840_sense && "$PIO_BIN" run)
else
  echo "Skipping firmware build: pio not found"
fi

echo "Checks completed."
