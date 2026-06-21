#!/usr/bin/env python3
"""Build CatSense feature datasets from own raw recordings."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from train_baseline import LABEL_NAMES, Row, build_windows, split_segments, trim_segments, write_windows_csv


UNIFIED_SAMPLE_HEADER = (
    "source",
    "host_time_iso",
    "device_ms",
    "seq",
    "ax_mg",
    "ay_mg",
    "az_mg",
    "battery_mv",
    "label",
    "cat_id",
    "device_id",
    "raw_label",
    "file",
)


@dataclass
class DatasetStats:
    rows_by_source: Counter[str]
    rows_by_label: Counter[str]
    windows_by_source: Counter[str]
    windows_by_label: Counter[str]


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = default_root()
    parser = argparse.ArgumentParser(description="Build CatSense V0 processed feature datasets.")
    parser.add_argument("--raw", type=Path, default=root / "data" / "raw")
    parser.add_argument("--processed", type=Path, default=root / "data" / "processed")
    parser.add_argument("--window-s", type=float, default=2.0)
    parser.add_argument("--step-s", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=25.0)
    parser.add_argument(
        "--trim-edge-s",
        type=float,
        default=0.8,
        help="Drop this many seconds from each labeled segment edge before feature windows.",
    )
    return parser.parse_args()


def read_own_rows(raw_dir: Path) -> list[Row]:
    rows: list[Row] = []
    for path in sorted(raw_dir.glob("**/*.csv")):
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for record in reader:
                try:
                    source_label = (record.get("label") or "").strip()
                    label = source_label if source_label in LABEL_NAMES else ""
                    cat_id = (record.get("cat_id") or path.parent.name).strip()
                    device_id = (record.get("device_id") or "CatSense-V0").strip()
                    rows.append(
                        Row(
                            source="own",
                            host_time_iso=(record.get("host_time_iso") or "").strip(),
                            file=path.name,
                            device_ms=int(record["device_ms"]),
                            seq=int(record["seq"]),
                            ax_mg=int(record["ax_mg"]),
                            ay_mg=int(record["ay_mg"]),
                            az_mg=int(record["az_mg"]),
                            label=label,
                            cat_id=cat_id,
                            device_id=device_id,
                            raw_label=source_label,
                            battery_mv=int(record.get("battery_mv") or -1),
                        )
                    )
                except (KeyError, ValueError):
                    continue
    return rows


def build_feature_windows(
    rows: list[Row],
    *,
    window_s: float,
    step_s: float,
    rate: float,
    trim_edge_s: float,
) -> list:
    window_samples = max(2, int(round(window_s * rate)))
    step_samples = max(1, int(round(step_s * rate)))
    trainable_rows = [row for row in rows if row.label]
    trainable_rows.sort(key=lambda row: (row.source, row.file, row.cat_id, row.device_ms, row.seq))
    segments = split_segments(trainable_rows)
    segments, _ = trim_segments(segments, trim_edge_s, window_samples)
    return build_windows(segments, window_samples, step_samples)


def write_unified_samples(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(UNIFIED_SAMPLE_HEADER)
        for row in rows:
            writer.writerow(
                (
                    row.source,
                    row.host_time_iso,
                    row.device_ms,
                    row.seq,
                    row.ax_mg,
                    row.ay_mg,
                    row.az_mg,
                    row.battery_mv,
                    row.label,
                    row.cat_id,
                    row.device_id,
                    row.raw_label,
                    row.file,
                )
            )


def summarize(rows: list[Row], windows: list) -> DatasetStats:
    return DatasetStats(
        rows_by_source=Counter(row.source for row in rows),
        rows_by_label=Counter(row.label or "<blank>" for row in rows),
        windows_by_source=Counter(window.source for window in windows),
        windows_by_label=Counter(window.label for window in windows),
    )


def print_counter(title: str, counter: Counter[str]) -> None:
    print(title)
    if not counter:
        print("- none")
        return
    for key, count in counter.most_common():
        print(f"- {key}: {count}")


def main() -> int:
    args = parse_args()

    rows = read_own_rows(args.raw)
    if not rows:
        print(f"No rows found under {args.raw}")
        return 1

    rows.sort(key=lambda row: (row.source, row.file, row.cat_id, row.device_ms, row.seq))
    windows = build_feature_windows(
        rows,
        window_s=args.window_s,
        step_s=args.step_s,
        rate=args.rate,
        trim_edge_s=args.trim_edge_s,
    )

    args.processed.mkdir(parents=True, exist_ok=True)
    write_unified_samples(args.processed / "unified_samples.csv", rows)
    write_windows_csv(args.processed / "features.csv", windows, sorted(windows[0].features) if windows else [])

    stats = summarize(rows, windows)
    print(f"samples={len(rows)} windows={len(windows)}")
    print(f"unified_samples={args.processed / 'unified_samples.csv'}")
    print(f"features={args.processed / 'features.csv'}")
    print_counter("sample_sources", stats.rows_by_source)
    print_counter("sample_labels", stats.rows_by_label)
    print_counter("window_sources", stats.windows_by_source)
    print_counter("window_labels", stats.windows_by_label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
