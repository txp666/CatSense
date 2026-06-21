# Current Status

Date: 2026-06-22

## Implemented

- XIAO nRF52840 Sense firmware
- LSM6DS3 accelerometer sampling
- BLE UART protocol
- Battery voltage reading
- BLE TX power set to `+8 dBm`
- Python command-line logger
- Local web logger with phone access on same Wi-Fi
- Manual behavior button labeling
- Realtime baseline prediction preview in the web logger
- Realtime prediction smoothing and switch hysteresis
- Firmware collection mode / daily mode
- Daily mode internal LittleFS cache and periodic BLE upload window
- Web OTA/DFU direct flashing with slow retry
- Dataset QA script
- Own-data feature build script
- Baseline training script
- Session holdout evaluation script
- Segment edge trimming before training windows
- Open-source baseline files, synthetic examples, lightweight CI, and privacy notes

## Current Label Coverage

Latest `dataset_report.py` summary:

| Label | Name | Seconds | Status |
| --- | --- | ---: | --- |
| `rest` | 休息 | 292.8 | OK |
| `parkour` | 跑酷 | 156.0 | OK |
| `walk` | 走动 | 254.0 | OK |
| `play` | 玩耍 | 313.1 | OK |
| `groom` | 舔毛 | 260.4 | OK |
| `eat` | 进食 | 288.0 | OK |

## Current Baseline

Latest `train_baseline.py` random-window summary:

```text
windows=1236
labels=eat,groom,parkour,play,rest,walk
trim_edge_s=0.800
train_accuracy=0.730
test_accuracy=0.718
```

Interpretation:

- Good enough to prove the pipeline.
- Not good enough for a public performance claim.
- Good enough to start the next engineering phase for a 6-label checkpoint.
- `roll` and `litter` are disabled in the current web label set; historical disabled labels remain only in `raw_label` and are not used for training.
- Training now trims 0.8 seconds from each labeled segment edge to reduce manual label timing noise.

## Session Evaluation

Latest `evaluate_by_session.py` summary:

```text
sessions=16/16
windows=1236
accuracy=0.576
```

Interpretation:

- This is stricter than the random-window split.
- `eat` and `parkour` are comparatively stronger.
- `groom` and `walk` are the next targeted data gaps.

## Realtime Preview

The web logger loads `models/baseline_centroid.json` by default and predicts from a rolling 2-second window. The page shows the current top prediction and relative scores for nearby labels.

The displayed label is smoothed. A new raw prediction must repeat and beat the current displayed label by a margin before the UI switches, so short window noise does not make the label flicker.

Important limits:

- Prediction is only a preview and is not saved as ground truth.
- Manual labels remain the source of truth for training.
- Current scores are nearest-centroid relative stability scores, not calibrated probabilities.

## Immediate Next Steps

1. Keep the current 6-label baseline artifacts as a pipeline checkpoint.
2. Improve evaluation split by session/day.
3. Tune prediction smoothing after real collar sessions.
4. Add hardware mounting photos or enclosure diagrams after privacy review.
