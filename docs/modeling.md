# Modeling Notes

CatSense V0 currently has a local baseline model. It is meant to verify the dataset and training pipeline, not to be the final behavior classifier.

## Pipeline

Input:

```text
data/raw/{cat_id}/manual_*.csv
```

Process:

1. Read own raw CSV.
2. Convert rows into the unified sample schema.
3. Split into contiguous label segments.
4. Drop blank labels.
5. Trim the start and end of each labeled segment.
6. Build 2-second windows with 1-second step.
7. Extract statistical features from `ax_mg`, `ay_mg`, `az_mg`, and magnitude.
8. Train a nearest-centroid classifier.
9. Write model and report files.

Command:

```bash
cd gateway
python build_dataset.py
python train_baseline.py
```

Outputs:

```text
data/processed/features.csv
data/processed/windows.csv
models/baseline_centroid.json
models/baseline_report.txt
```

## Edge Trimming

Manual labels have reaction-time error. The training script therefore trims each labeled segment before building windows:

```bash
python train_baseline.py --trim-edge-s 0.8
```

This keeps raw CSV files unchanged, drops 0.8 seconds from the start and end of each labeled segment, and ignores segments that are too short to contain a full 2-second window after trimming. Disable it with `--trim-edge-s 0`.

## Realtime Web Preview

The web logger loads the baseline model by default:

```bash
cd gateway
python web_logger.py --host 0.0.0.0 --port 8000
```

Runtime behavior:

- Keep a rolling 2-second buffer of live samples.
- Resample the buffer to the model's training rate and window size.
- Reuse the same feature extraction function as `train_baseline.py`.
- Compare the standardized feature vector with each label centroid.
- Smooth label scores over consecutive windows.
- Switch the displayed label only after repeated support and enough margin.
- Send the top prediction and relative scores to the browser over SSE.

The preview can be disabled:

```bash
python web_logger.py --no-prediction
```

The preview does not write predictions into raw CSV files. Raw training data should only use manual labels.

## Feature Families

For each window:

- Axis mean/std/min/max/range/RMS
- Axis p25/p75
- Magnitude mean/std/min/max/range/RMS
- First-difference statistics for motion intensity
- Duration and sample count

## Current Baseline Result

Latest run:

```text
windows=1236
labels=eat,groom,parkour,play,rest,walk
trim_edge_s=0.800
train_accuracy=0.730
test_accuracy=0.718
```

Known limitation:

- `roll` and `litter` are disabled in the current label set and excluded from training.
- `groom`, `walk`, and `play` are often confused.
- Current train/test split is random by window, so it is optimistic compared with a future split by session/day/cat.
- Realtime scores are relative nearest-centroid stability scores, not calibrated probabilities.

## What Accuracy Means Now

The current baseline only proves:

- CSV format is usable
- Feature extraction works
- Model artifact can be generated
- Confusion matrix can reveal data issues

It does not yet prove:

- Real-world performance on a new cat
- Stable predictions during long recordings
- Robustness to collar rotation

## Next Model Requirements

Before claiming a useful V0 model:

- All labels should have at least 120 seconds, preferably more.
- Evaluation should split by recording session, not only random windows.
- Similar labels should have targeted data: `walk`, `groom`, `play`.
- Prediction smoothing should be tuned with real collar sessions.
- Model version should include label schema and window settings.
