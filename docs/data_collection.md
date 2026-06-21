# Data Collection Guide

CatSense V0 labels are manual. The web page records continuously; tapping a behavior button sets the current label for future rows. Tapping the same button again clears the label.

## Label Set

| CSV label | Web label | Meaning |
| --- | --- | --- |
| `rest` | 休息 | lying, sitting still, relaxed resting |
| `parkour` | 跑酷 | rapid running, climbing, jumping bursts |
| `walk` | 走动 | normal walking or slow moving |
| `play` | 玩耍 | playing without full parkour intensity |
| `groom` | 舔毛 | licking or grooming body |
| `eat` | 进食 | eating dry or wet food |

## Recording Rules

- Record real collar placement whenever possible.
- Keep the same `cat_id` for the same cat.
- Use `manual_*.csv` from the web logger for behavior training.
- Leave label blank when behavior is unknown or transition is messy.
- Prefer several short clean segments over one long noisy segment.

## Collar Placement Notes

Record placement in your experiment notes when possible:

- Tightness: loose, normal, tight
- Device position: under neck, side, top
- Collar rotation: stable or rotating
- Battery/board enclosure: bare board, taped, printed case

These factors change accelerometer patterns and should be varied once the basic model works.

## Minimum Data Targets

For a first baseline:

- Minimum useful: 30 seconds per label
- Recommended first target: 120 seconds per label
- Better target: 5-10 minutes per label

For an open-source dataset:

- Multiple cats
- Multiple days
- Multiple collar placements
- Notes for each recording session

## Disconnections

If BLE disconnects before you tap the same action button again:

- Samples already written keep their current label.
- The CSV is flushed and closed.
- No artificial end marker is added.
- The next recording starts with a blank label.

This is acceptable for training because windows are built only from recorded samples.

## Quality Checks

Run:

```bash
cd gateway
python dataset_report.py
```

Investigate:

- `parse_errors > 0`
- many large time gaps
- very low sample rate
- labels with too few seconds
- long labeled segments that were actually mixed behavior
