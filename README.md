# CatSense V0

CatSense V0 is a minimal open-source cat behavior data collection collar prototype.

The V0 goal is simple:

```text
XIAO nRF52840 Sense -> IMU acceleration -> BLE -> Python/web logger -> CSV files -> baseline model -> realtime preview
```

V0 does not include a native phone app, cloud sync, production-grade all-day storage, or aggressive low-power optimization. It focuses on collecting stable real-world accelerometer data and validating a first local training pipeline. The firmware and web gateway include an early daily-cache mode and BLE OTA/DFU workflow.

![CatSense V0 system flow](docs/assets/system-flow.svg)

## Quick Commands

From the repository root:

```bash
make setup      # create gateway/.venv and install Python deps
make web        # run the local web logger on 0.0.0.0:8000
make check      # run lightweight source checks
make firmware   # build firmware with PlatformIO
make upload     # upload firmware over USB
make pipeline   # run data QA, processing, training, and evaluation
```

Private recordings, processed datasets, and generated models are ignored by
default. Public examples live under `examples/`.

Windows note: the `Makefile` is intended for Git Bash/MSYS-style shells. It
also detects PlatformIO's default Windows path,
`%USERPROFILE%\.platformio\penv\Scripts\pio.exe`. In PowerShell, use
`powershell -ExecutionPolicy Bypass -File scripts/check.ps1` for checks.

## Hardware

- Seeed Studio XIAO nRF52840 Sense
- Built-in 6-axis IMU
- BLE-capable host computer or Raspberry Pi
- USB cable for flashing and serial logs

Important: the regular Seeed Studio XIAO nRF52840 does not include the Sense board's IMU. Use the XIAO nRF52840 Sense for this firmware.

## Repository Layout

```text
catsense-v0/
├── firmware/
│   └── xiao_nrf52840_sense/
├── gateway/
├── data/
│   └── raw/
├── models/
└── docs/
```

## Documentation

- [中文 README](README.zh-CN.md)
- [中文文档](docs/zh/index.md)
- [Diagrams](docs/diagrams.md)
- [Quick Start](docs/quick_start.md)
- [Project Workflow](docs/workflow.md)
- [Data Collection Guide](docs/data_collection.md)
- [BLE Protocol](docs/protocol.md)
- [OTA / DFU](docs/protocol.md#ota--dfu)
- [Modeling Notes](docs/modeling.md)
- [Current Status](docs/current_status.md)
- [Open Source Preparation](docs/open_source.md)
- [Contributing](CONTRIBUTING.md)

## Flash Firmware

Install PlatformIO, then build and upload:

```bash
make firmware
make upload
```

This project includes a local PlatformIO board definition because the default
`nordicnrf52` registry does not currently list the Seeed XIAO nRF52840 Sense.
The firmware uses Seeed's official nRF52 Arduino core package so the XIAO pin
map and onboard IMU power pins are correct.

Open the serial monitor:

```bash
pio device monitor
```

Expected boot logs:

```text
CatSense V0 boot
IMU init ok
Battery <mv> mV
BLE tx power 8 dBm
BLE advertising
```

If the board prints `IMU init failed`, confirm that the hardware is the XIAO nRF52840 Sense, not the non-Sense model.

## Run Python Logger

Use Python 3.10 or newer:

```bash
make setup
cd gateway
.venv/bin/python logger.py --label eat --cat cat001 --rate 25
```

The logger scans for the BLE device named `CatSense-V0`, connects, sends `RATE 25`, sends `START`, and saves samples to:

```text
data/raw/{cat_id}/{label}_{YYYYMMDD_HHMMSS}.csv
```

Press `Ctrl+C` to stop. The logger sends `STOP`, flushes the CSV file, and disconnects.

For a browser UI with live curves and manual behavior labels:

```bash
make web
```

Then open the printed URL. Use the `Phone` URL from a phone connected to the same Wi-Fi. By default, web recordings append to `data/raw/{cat_id}/manual_{YYYYMMDD}.csv` so repeated start/stop sessions do not create many files. The page can also use per-session CSV files or preview-only mode. Tap a behavior button to fill the CSV `label` column; tap the same button again to return to blank labels. Label transitions are also written to `marker`, `marker_time_iso`, and `marker_note`.

If `models/baseline_centroid.json` exists, the web page also shows a realtime prediction preview from the rolling 2-second baseline window. This preview is not written into raw CSV files and should not replace manual labels.

## First Data Collection

Current web labels:

| Label | Meaning |
| --- | --- |
| `rest` | 休息 |
| `parkour` | 跑酷 |
| `walk` | 走动 |
| `play` | 玩耍 |
| `groom` | 舔毛 |
| `eat` | 进食 |

For a first hardware test:

```bash
python logger.py --label test --cat cat001 --rate 25
```

Move or shake the XIAO gently and confirm that `ax_mg`, `ay_mg`, and `az_mg` change in the generated CSV.
