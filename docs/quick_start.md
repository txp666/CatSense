# Quick Start

This guide gets CatSense V0 from firmware flashing to a first labeled CSV.

## 1. Flash Firmware

```bash
make firmware
make upload
```

Open the serial monitor:

```bash
pio device monitor
```

Expected logs:

```text
CatSense V0 boot
IMU init ok
Battery <mv> mV
BLE tx power 8 dBm
BLE advertising
```

## 2. Install Gateway Dependencies

```bash
make setup
```

## 3. Start the Web Logger

```bash
make web
```

The logger prints URLs like:

```text
Computer: http://127.0.0.1:8000
Phone:    http://<your-lan-ip>:8000
```

Use the `Phone` URL from a phone on the same Wi-Fi as the Mac.

## 4. Record Data

1. Power the collar and keep it close enough for BLE.
2. Open the web page.
3. Set `cat_id`.
4. Click `开始记录`.
5. Tap a behavior button when that behavior starts.
6. Tap the same button again when it ends.
7. Click `停止记录`.

CSV files are saved under:

```text
data/raw/{cat_id}/manual_{YYYYMMDD_HHMMSS}.csv
```

## 5. Check Dataset Quality

```bash
make report
```

This reports seconds per label, sample rate, battery range, gaps, and labels that need more data.

## 6. Train the Baseline

```bash
make train
```

Outputs:

```text
data/processed/windows.csv
models/baseline_centroid.json
models/baseline_report.txt
```
