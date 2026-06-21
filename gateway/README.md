# CatSense V0 Gateway

Python BLE logger for CatSense V0.

## Setup

Use Python 3.10 or newer.

```bash
make setup
```

Run commands from the repository root when using `make`. If you are already in
`gateway/`, use `.venv/bin/python ...`.

## Command-Line Collection

Flash the firmware first, power the XIAO nRF52840 Sense, then run:

```bash
python logger.py --label eat --cat cat001 --rate 25
```

The command-line logger is useful for quick single-label tests. Current web labels are:

- `rest`
- `parkour`
- `walk`
- `play`
- `groom`
- `eat`

For a quick hardware shake test, use:

```bash
python logger.py --label test --cat cat001 --rate 25
```

Press `Ctrl+C` to stop. The logger sends `STOP`, flushes the CSV file, and disconnects.

## Live Web Logger

For live visualization and manual behavior labels, run:

```bash
make web
```

Open the printed computer URL on the Mac, or the printed phone URL on a phone connected to the same Wi-Fi. Choose the cat id, rate, and save mode, then click Start Recording. The page shows live `ax_mg`, `ay_mg`, `az_mg`, sample count, observed rate, and battery millivolts.

Save modes:

- `daily`: default, append repeated sessions to `data/raw/{cat_id}/manual_{YYYYMMDD}.csv`
- `session`: create `manual_{YYYYMMDD_HHMMSS}.csv` for each recording
- `preview`: show live curves and predictions without saving CSV

While recording, tap a behavior button to start that label. Tap the same button again to end it and write blank labels again. The label transition is also saved in `marker`, `marker_time_iso`, and `marker_note`.

If `../models/baseline_centroid.json` exists, the web page shows a realtime prediction preview. The preview runs in the Python gateway, uses the current baseline model, and sends results to the browser over the existing event stream. Disable it with:

```bash
python web_logger.py --no-prediction
```

## Web Data Processing

After collecting data, stop recording and use the Data Processing panel at the bottom of the web page. Daily work should not require running the processing scripts by hand.

Buttons:

- Check Data: runs the raw-data report.
- Build Data: creates `../data/processed/unified_samples.csv` and `../data/processed/features.csv`.
- Train Model: creates `../data/processed/windows.csv`, `../models/baseline_centroid.json`, and `../models/baseline_report.txt`.
- Session Evaluation: creates `../models/session_eval_report.txt`.
- Run All: runs the four steps in order.

The Train Model and Run All buttons reload the realtime prediction model after training succeeds. Start the next recording to preview the updated model.

Under the hood these buttons call `dataset_report.py`, `build_dataset.py`, `train_baseline.py`, and `evaluate_by_session.py`. By default, training trims 0.8 seconds from the start and end of each labeled segment before building windows. This reduces manual label timing noise.

## Device Management and OTA

The Device Management panel can read firmware status, switch between collection and daily mode, pull cached daily samples, and run BLE OTA.

Recommended OTA flow:

- Build firmware first with `pio run` in `../firmware/xiao_nrf52840_sense`.
- Click `Flash Firmware` in the web page.
- If the device is already in DFU/bootloader mode, click `Flash Firmware` directly.
- If flashing fails with a packet notification or operation error, keep the device in DFU mode and click `Slow Retry`.
- After sending the image, the backend waits for `CatSense-V0` to advertise again. If it reports that the device is still in DFU, click `Reboot DFU`; if that still fails, press reset once and then read status.
- If desktop BLE keeps failing, download the firmware zip, click `Enter OTA`, and flash with `nRF Connect` or `Adafruit Bluefruit Connect`.

## Documentation

- `../README.zh-CN.md`
- `../docs/zh/index.md`
- `../docs/quick_start.md`
- `../docs/workflow.md`
- `../docs/data_collection.md`
- `../docs/modeling.md`
- `../docs/current_status.md`
- `../docs/open_source.md`
