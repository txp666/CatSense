# Open Source Preparation

This project is intended to become open source, but raw pet/home recordings should be treated carefully.

## Repository Policy

Commit:

- Firmware source
- Gateway source
- Web logger source
- Documentation
- Small synthetic or example CSV
- Model/training code

Do not commit by default:

- Raw personal recordings in `data/raw/`
- Large processed datasets
- Private cat names, home notes, Wi-Fi details, or device identifiers
- Local virtual environments

Current `.gitignore` excludes:

```text
data/raw/*
data/processed/*
models/*
.venv/
.pio/
```

The repository keeps `data/raw/.gitkeep`, `data/processed/.gitkeep`, and
`models/.gitkeep` only as directory placeholders. Public examples belong in
`examples/synthetic/`; private recordings should not be moved there.

## Recommended Before Public Release

- Add real hardware photos or enclosure diagrams after checking privacy.
- Verify `make setup`, `make check`, and `make firmware` from a clean checkout.
- Verify the web logger from a clean virtual environment.
- Prepare any real public example data according to the requirements below.

## Suggested Project Positioning

CatSense V0 is a research/prototyping project for collecting cat collar IMU data. It is not a medical device, not a safety device, and not a production pet tracker.

## Good First Issues

- Add session metadata notes to the web logger.
- Add CSV export validation.
- Add realtime RSSI display if available from BLE backend.
- Expand the synthetic sample dataset.
- Improve baseline evaluation by recording session or day.
- Improve realtime prediction visualization and explanations.

## Own Example Data Requirements

Before publishing any self-collected example data:

- Remove personal notes.
- Use anonymous `cat_id` values.
- Document collar placement.
- Document approximate cat size/age only if owner is comfortable.
- Include consent statement for contributors.
- Avoid video/photo unless explicitly intended for the dataset.
