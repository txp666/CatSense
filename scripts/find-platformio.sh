#!/usr/bin/env sh
set -eu

if command -v pio >/dev/null 2>&1; then
  command -v pio
  exit 0
fi

if command -v platformio >/dev/null 2>&1; then
  command -v platformio
  exit 0
fi

if [ -x "${HOME:-}/.platformio/penv/bin/pio" ]; then
  printf '%s\n' "$HOME/.platformio/penv/bin/pio"
  exit 0
fi

if [ -x "${HOME:-}/.platformio/penv/Scripts/pio.exe" ]; then
  printf '%s\n' "$HOME/.platformio/penv/Scripts/pio.exe"
  exit 0
fi

if [ -n "${USERPROFILE:-}" ] && command -v cygpath >/dev/null 2>&1; then
  win_home="$(cygpath "$USERPROFILE" 2>/dev/null || true)"
  if [ -n "$win_home" ] && [ -x "$win_home/.platformio/penv/Scripts/pio.exe" ]; then
    printf '%s\n' "$win_home/.platformio/penv/Scripts/pio.exe"
    exit 0
  fi
fi

exit 1
