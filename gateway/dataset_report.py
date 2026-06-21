#!/usr/bin/env python3
"""Summarize CatSense raw CSV recordings."""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable


LABEL_NAMES = {
    "rest": "休息",
    "parkour": "跑酷",
    "walk": "走动",
    "play": "玩耍",
    "groom": "舔毛",
    "eat": "进食",
}

EXPECTED_LABELS = tuple(LABEL_NAMES)
MAX_NORMAL_GAP_MS = 200


@dataclass
class Row:
    file: Path
    line: int
    device_ms: int
    seq: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    battery_mv: int
    label: str
    marker: str

    @property
    def magnitude_mg(self) -> float:
        return math.sqrt(self.ax_mg * self.ax_mg + self.ay_mg * self.ay_mg + self.az_mg * self.az_mg)


def default_raw_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "raw"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize CatSense V0 raw CSV data.")
    parser.add_argument("--raw", type=Path, default=default_raw_dir(), help="Raw data directory.")
    parser.add_argument("--target-seconds", type=float, default=120.0, help="Target seconds per label.")
    parser.add_argument("--min-seconds", type=float, default=30.0, help="Minimum useful seconds per label.")
    return parser.parse_args()


def read_rows(files: Iterable[Path]) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    errors: list[str] = []

    for path in files:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for line, record in enumerate(reader, start=2):
                try:
                    rows.append(
                        Row(
                            file=path,
                            line=line,
                            device_ms=int(record["device_ms"]),
                            seq=int(record["seq"]),
                            ax_mg=int(record["ax_mg"]),
                            ay_mg=int(record["ay_mg"]),
                            az_mg=int(record["az_mg"]),
                            battery_mv=int(record["battery_mv"]),
                            label=(record.get("label") or "").strip(),
                            marker=(record.get("marker") or "").strip(),
                        )
                    )
                except (KeyError, ValueError) as exc:
                    errors.append(f"{path}:{line}: {exc}")

    return rows, errors


def contiguous_seconds(rows: list[Row]) -> float:
    seconds = 0.0
    previous: Row | None = None

    for row in rows:
        if previous is not None and row.file == previous.file:
            delta_ms = row.device_ms - previous.device_ms
            if 0 < delta_ms <= MAX_NORMAL_GAP_MS:
                seconds += delta_ms / 1000.0
        previous = row

    return seconds


def status_for(seconds: float, target_seconds: float, min_seconds: float) -> str:
    if seconds >= target_seconds:
        return "OK"
    if seconds >= min_seconds:
        return "LOW"
    return "NEED"


def display_label(label: str) -> str:
    if not label:
        return "未标记"
    return LABEL_NAMES.get(label, "停用标签")


def print_file_summary(files: list[Path], rows_by_file: dict[Path, list[Row]]) -> None:
    print("Files")
    print("file, rows, duration_s, rate_hz, battery_mv, labels")
    for path in files:
        rows = rows_by_file[path]
        if not rows:
            print(f"{path.name}, 0, 0.0, 0.00, -, -")
            continue

        duration_s = max(0.0, (rows[-1].device_ms - rows[0].device_ms) / 1000.0)
        rate_hz = len(rows) / duration_s if duration_s else 0.0
        battery = f"{min(row.battery_mv for row in rows)}-{max(row.battery_mv for row in rows)}"
        labels = Counter(row.label for row in rows)
        label_text = " ".join(
            f"{display_label(label)}:{count}" for label, count in labels.most_common(5)
        )
        print(f"{path.name}, {len(rows)}, {duration_s:.1f}, {rate_hz:.2f}, {battery}, {label_text}")
    print()


def print_label_summary(rows: list[Row], target_seconds: float, min_seconds: float) -> None:
    rows_by_label: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        rows_by_label[row.label].append(row)

    print("Labels")
    print("label, name, rows, seconds, segments, mean_mag_mg, status")
    for label in EXPECTED_LABELS:
        label_rows = rows_by_label[label]
        seconds = contiguous_seconds(label_rows)
        segments = count_segments(label_rows)
        mean_mag = mean(row.magnitude_mg for row in label_rows) if label_rows else 0.0
        status = status_for(seconds, target_seconds, min_seconds)
        print(
            f"{label}, {LABEL_NAMES[label]}, {len(label_rows)}, {seconds:.1f}, "
            f"{segments}, {mean_mag:.0f}, {status}"
        )

    blank_rows = rows_by_label.get("", [])
    if blank_rows:
        seconds = contiguous_seconds(blank_rows)
        print(f"<blank>, 未标记, {len(blank_rows)}, {seconds:.1f}, {count_segments(blank_rows)}, -, -")
    print()


def count_segments(rows: list[Row]) -> int:
    if not rows:
        return 0

    segments = 1
    previous = rows[0]
    for row in rows[1:]:
        if row.file != previous.file or row.device_ms - previous.device_ms > MAX_NORMAL_GAP_MS:
            segments += 1
        previous = row
    return segments


def print_quality_summary(rows_by_file: dict[Path, list[Row]], parse_errors: list[str]) -> None:
    time_gaps = 0
    seq_gaps = 0
    markers = 0

    for rows in rows_by_file.values():
        markers += sum(1 for row in rows if row.marker)
        previous: Row | None = None
        for row in rows:
            if previous is not None:
                if row.device_ms - previous.device_ms > MAX_NORMAL_GAP_MS:
                    time_gaps += 1
                if row.seq - previous.seq != 1:
                    seq_gaps += 1
            previous = row

    print("Quality")
    print(f"time_gaps_over_{MAX_NORMAL_GAP_MS}ms={time_gaps}")
    print(f"seq_gaps={seq_gaps}")
    print(f"markers={markers}")
    print(f"parse_errors={len(parse_errors)}")
    if parse_errors:
        for error in parse_errors[:10]:
            print(error)
    print()


def print_next_steps(rows: list[Row], target_seconds: float, min_seconds: float) -> None:
    rows_by_label: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        rows_by_label[row.label].append(row)

    needs = []
    lows = []
    for label in EXPECTED_LABELS:
        seconds = contiguous_seconds(rows_by_label[label])
        missing = max(0.0, target_seconds - seconds)
        if seconds < min_seconds:
            needs.append((label, seconds, missing))
        elif seconds < target_seconds:
            lows.append((label, seconds, missing))

    print("Next")
    if needs:
        print("Collect first:")
        for label, seconds, missing in needs:
            print(f"- {LABEL_NAMES[label]} ({label}): {seconds:.0f}s now, collect about {missing:.0f}s more")
    if lows:
        print("Then balance:")
        for label, seconds, missing in lows:
            print(f"- {LABEL_NAMES[label]} ({label}): {seconds:.0f}s now, collect about {missing:.0f}s more")
    if not needs and not lows:
        print("All labels have enough data for a first baseline model.")


def main() -> int:
    args = parse_args()
    files = sorted(args.raw.glob("**/*.csv"))
    if not files:
        print(f"No CSV files found under {args.raw}")
        return 1

    rows, parse_errors = read_rows(files)
    rows_by_file: dict[Path, list[Row]] = defaultdict(list)
    for row in rows:
        rows_by_file[row.file].append(row)

    print_file_summary(files, rows_by_file)
    print_label_summary(rows, args.target_seconds, args.min_seconds)
    print_quality_summary(rows_by_file, parse_errors)
    print_next_steps(rows, args.target_seconds, args.min_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
