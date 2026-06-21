# Contributing to CatSense V0

CatSense V0 is currently a prototype. Contributions should keep the project easy to build, easy to audit, and safe for pet/home privacy.

## Development Setup

Firmware:

```bash
make firmware
```

Gateway:

```bash
make setup
make check
```

On Windows PowerShell, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

## Before Submitting Changes

Run the relevant checks:

```bash
make check
```

For web UI changes, open the web logger locally and verify:

- The page loads on Mac.
- The phone URL works from the same Wi-Fi.
- Behavior buttons toggle labels correctly.
- CSV output still has the expected columns.

## Data Contributions

Do not submit private raw data by default.

If contributing example data:

- Use anonymous `cat_id` values.
- Remove personal notes.
- Keep files small.
- Describe collar placement and label meaning.
- Prefer synthetic or deliberately public sample data.

## Code Style

- Keep dependencies minimal.
- Prefer clear scripts over hidden notebook state.
- Keep raw data, processed data, and model outputs out of git unless explicitly intended as public examples.
- Document any protocol or CSV schema change in `docs/protocol.md`.

## Good First Tasks

- Improve `dataset_report.py` with more quality checks.
- Add session metadata to web recordings.
- Improve train/test split by recording session.
- Add RSSI or connection quality display to the web UI.
- Expand the synthetic example dataset.
- Add hardware mounting notes or photos after privacy review.
