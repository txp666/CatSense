$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$PythonBin = "python"
if (Test-Path "gateway/.venv/Scripts/python.exe") {
  $PythonBin = "gateway/.venv/Scripts/python.exe"
} elseif (Test-Path "gateway/.venv/bin/python") {
  $PythonBin = "gateway/.venv/bin/python"
}

Write-Host "Python: " -NoNewline
& $PythonBin --version
& $PythonBin -m py_compile (Get-ChildItem gateway/*.py | ForEach-Object { $_.FullName })

if (Get-Command node -ErrorAction SilentlyContinue) {
  node --check gateway/web/app.js
} else {
  Write-Host "Skipping JS syntax check: node not found"
}

$PioBin = $null
if (Get-Command pio -ErrorAction SilentlyContinue) {
  $PioBin = (Get-Command pio).Source
} elseif (Get-Command platformio -ErrorAction SilentlyContinue) {
  $PioBin = (Get-Command platformio).Source
} elseif (Test-Path "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe") {
  $PioBin = "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe"
}

if ($PioBin) {
  Push-Location firmware/xiao_nrf52840_sense
  try {
    & $PioBin run
  } finally {
    Pop-Location
  }
} else {
  Write-Host "Skipping firmware build: pio not found"
}

Write-Host "Checks completed."
