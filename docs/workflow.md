# CatSense V0 Workflow

This document records what each project step does, what it needs, and what counts as done.

## Step 1. Hardware Bring-Up

Purpose: confirm the board, IMU, battery measurement, and BLE stack work.

Input:
- Seeed Studio XIAO nRF52840 Sense
- Battery connected to the board battery pads/connector
- USB cable for flashing and logs

Output:
- Firmware boots
- IMU initializes
- BLE advertises as `CatSense-V0`
- Battery millivolts print in serial logs

Done when:
- Serial shows `IMU init ok`
- Serial shows `BLE tx power 8 dBm`
- The gateway can connect and receive `CS0,...` samples

## Step 2. Firmware Sampling

Purpose: stream acceleration and battery data over BLE.

Input:
- Firmware in `firmware/xiao_nrf52840_sense`
- Host command: `START`, `STOP`, `RATE 25`, or `RATE 50`

Output:
- BLE Notify lines:

```csv
CS0,seq,device_ms,ax_mg,ay_mg,az_mg,battery_mv
```

Requirements:
- Sequence number must increase
- `device_ms` must increase
- Battery should refresh about every 5 seconds
- Default BLE TX power is `+8 dBm`

## Step 3. Data Collection

Purpose: record real behavior data with manual labels.

Input:
- BLE samples from the collar
- Manual label button events from the web page

Output:
- Raw CSV files in `data/raw/{cat_id}/`
- Each row has acceleration, battery, label, and marker metadata

Done when:
- Each target label has enough clean seconds
- Labels are not obviously wrong
- The report has no parse errors

Target for V0:
- Minimum useful: 30 seconds per label
- First baseline target: 120 seconds per label
- Better target: 5-10 minutes per label across multiple days and collar placements

## Step 4. Dataset QA

Purpose: decide whether the current data is good enough for training.

Command:

```bash
cd gateway
python dataset_report.py
```

Output:
- Label seconds
- Segment counts
- Sample rate per file
- Battery range
- Time gaps and sequence gaps

Done when:
- All labels needed for the current model are `OK`
- Any `LOW` labels are accepted intentionally or scheduled for more collection
- `parse_errors=0`

## Step 5. Baseline Training

Purpose: verify that the dataset can produce a measurable model.

Command:

```bash
cd gateway
python train_baseline.py
```

Output:
- `data/processed/windows.csv`
- `models/baseline_centroid.json`
- `models/baseline_report.txt`

Current baseline:
- 2-second windows
- 1-second step
- Hand-written statistical features
- Nearest-centroid classifier
- No third-party ML dependency

Done when:
- Training script completes
- Report includes train/test accuracy and per-label metrics
- Confusion matrix identifies the next data/model problem

## Step 6. Model Iteration

Purpose: improve from a sanity-check baseline to a usable classifier.

Current state:
- Web logger can load `models/baseline_centroid.json`
- Live samples are converted into rolling 2-second windows
- The page shows a realtime prediction preview and top relative scores
- Displayed labels use smoothing and switch hysteresis

Likely next work:
- Add more data for weak labels
- Split by recording segment or day, not random window only
- Try tree-based models or lightweight neural networks
- Tune smoothing thresholds with real collar sessions

Done when:
- Test accuracy and per-label recall are acceptable for a V0 demo
- False positives for similar labels are understood
- Model artifacts and label schema are versioned

## Step 7. Open Source Release

Purpose: make the project understandable and safe for others to try.

Done when:
- README explains the project and limitations
- Docs explain hardware, collection, protocol, and training
- Raw private pet data is excluded from git
- License and privacy notes are included
- Public example data is synthetic or intentionally public
- Issues list has clear starter tasks
