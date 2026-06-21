#!/usr/bin/env python3
"""Train a no-dependency baseline classifier from own CatSense data."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


LABEL_NAMES = {
    "rest": "rest",
    "parkour": "parkour",
    "walk": "walk",
    "play": "play",
    "groom": "groom",
    "eat": "eat",
}

MAX_GAP_MS = 200
RANDOM_SEED = 42
TRAINABLE_EXCLUDED_LABELS = {"", "unknown"}
FEATURE_METADATA_COLUMNS = {
    "source",
    "label",
    "raw_label",
    "cat_id",
    "device_id",
    "file",
    "segment_id",
    "start_seq",
    "end_seq",
    "start_ms",
    "end_ms",
}


@dataclass
class Row:
    file: str
    device_ms: int
    seq: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    label: str
    source: str = "own"
    cat_id: str = ""
    device_id: str = ""
    raw_label: str = ""
    host_time_iso: str = ""
    battery_mv: int = -1


@dataclass
class Window:
    label: str
    file: str
    segment_id: str
    start_seq: int
    end_seq: int
    start_ms: int
    end_ms: int
    features: dict[str, float]
    source: str = "own"
    cat_id: str = ""
    device_id: str = ""
    raw_label: str = ""


@dataclass
class TrimStats:
    trim_edge_s: float
    from_features: bool = False
    original_segments: int = 0
    trimmed_segments: int = 0
    dropped_segments: int = 0
    original_rows: int = 0
    trimmed_rows: int = 0
    dropped_rows: int = 0


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = default_root()
    parser = argparse.ArgumentParser(description="Train a CatSense V0 baseline model.")
    parser.add_argument("--raw", type=Path, default=root / "data" / "raw")
    parser.add_argument("--features", type=Path, default=root / "data" / "processed" / "features.csv")
    parser.add_argument("--processed", type=Path, default=root / "data" / "processed")
    parser.add_argument("--models", type=Path, default=root / "models")
    parser.add_argument(
        "--model-name",
        default="baseline_centroid",
        help="Output model basename without extension. Default keeps web_logger.py compatibility.",
    )
    parser.add_argument("--window-s", type=float, default=2.0)
    parser.add_argument("--step-s", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=25.0)
    parser.add_argument("--min-windows", type=int, default=8)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument(
        "--trim-edge-s",
        type=float,
        default=0.8,
        help="Drop this many seconds from the start and end of each labeled segment before windowing.",
    )
    return parser.parse_args()


def output_paths(models_dir: Path, model_name: str) -> tuple[Path, Path]:
    safe_name = Path(model_name).name.removesuffix(".json")
    model_path = models_dir / f"{safe_name}.json"
    if safe_name == "baseline_centroid":
        report_path = models_dir / "baseline_report.txt"
    else:
        report_path = models_dir / f"{safe_name}_report.txt"
    return model_path, report_path


def read_rows(raw_dir: Path) -> list[Row]:
    rows: list[Row] = []
    for path in sorted(raw_dir.glob("**/*.csv")):
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for record in reader:
                label = (record.get("label") or "").strip()
                if not label or label not in LABEL_NAMES:
                    continue
                cat_id = (record.get("cat_id") or path.parent.name).strip()
                device_id = (record.get("device_id") or "CatSense-V0").strip()
                rows.append(
                    Row(
                        file=path.name,
                        device_ms=int(record["device_ms"]),
                        seq=int(record["seq"]),
                        ax_mg=int(record["ax_mg"]),
                        ay_mg=int(record["ay_mg"]),
                        az_mg=int(record["az_mg"]),
                        label=label,
                        source="own",
                        cat_id=cat_id,
                        device_id=device_id,
                        raw_label=label,
                        host_time_iso=(record.get("host_time_iso") or "").strip(),
                        battery_mv=int(record.get("battery_mv") or -1),
                    )
                )
    return rows


def split_segments(rows: list[Row]) -> list[list[Row]]:
    segments: list[list[Row]] = []
    current: list[Row] = []
    previous: Row | None = None

    for row in rows:
        same_segment = (
            previous is not None
            and row.source == previous.source
            and row.file == previous.file
            and row.cat_id == previous.cat_id
            and row.label == previous.label
            and 0 < row.device_ms - previous.device_ms <= MAX_GAP_MS
            and row.seq > previous.seq
        )
        if current and not same_segment:
            segments.append(current)
            current = []
        current.append(row)
        previous = row

    if current:
        segments.append(current)
    return segments


def trim_segments(
    segments: list[list[Row]],
    trim_edge_s: float,
    window_samples: int,
) -> tuple[list[list[Row]], TrimStats]:
    trim_ms = max(0, int(round(trim_edge_s * 1000)))
    stats = TrimStats(trim_edge_s=max(0.0, trim_edge_s))
    stats.original_segments = len(segments)
    stats.original_rows = sum(len(segment) for segment in segments)

    if trim_ms <= 0:
        stats.trimmed_segments = len(segments)
        stats.trimmed_rows = stats.original_rows
        return segments, stats

    trimmed: list[list[Row]] = []
    for segment in segments:
        if not segment:
            continue

        start_ms = segment[0].device_ms + trim_ms
        end_ms = segment[-1].device_ms - trim_ms
        kept = [row for row in segment if start_ms <= row.device_ms <= end_ms]

        if len(kept) < window_samples:
            stats.dropped_segments += 1
            stats.dropped_rows += len(segment)
            continue

        stats.trimmed_segments += 1
        stats.trimmed_rows += len(kept)
        stats.dropped_rows += len(segment) - len(kept)
        trimmed.append(kept)

    return trimmed, stats


def build_windows(segments: list[list[Row]], window_samples: int, step_samples: int) -> list[Window]:
    windows: list[Window] = []
    segment_counts: Counter[str] = Counter()

    for segment in segments:
        if len(segment) < window_samples:
            continue

        first = segment[0]
        label = first.label
        segment_key = f"{first.source}_{label}"
        segment_counts[segment_key] += 1
        segment_id = f"{segment_key}_{segment_counts[segment_key]:04d}"

        for start in range(0, len(segment) - window_samples + 1, step_samples):
            rows = segment[start : start + window_samples]
            windows.append(
                Window(
                    label=label,
                    file=rows[0].file,
                    segment_id=segment_id,
                    start_seq=rows[0].seq,
                    end_seq=rows[-1].seq,
                    start_ms=rows[0].device_ms,
                    end_ms=rows[-1].device_ms,
                    features=extract_features(rows),
                    source=rows[0].source,
                    cat_id=rows[0].cat_id,
                    device_id=rows[0].device_id,
                    raw_label=rows[0].raw_label,
                )
            )

    return windows


def extract_features(rows: list[Row]) -> dict[str, float]:
    axes = {
        "ax": [row.ax_mg for row in rows],
        "ay": [row.ay_mg for row in rows],
        "az": [row.az_mg for row in rows],
    }
    magnitude = [
        math.sqrt(row.ax_mg * row.ax_mg + row.ay_mg * row.ay_mg + row.az_mg * row.az_mg)
        for row in rows
    ]

    features: dict[str, float] = {
        "duration_ms": float(rows[-1].device_ms - rows[0].device_ms),
        "samples": float(len(rows)),
    }
    for name, values in {**axes, "mag": magnitude}.items():
        add_stats(features, name, values)

    for name, values in axes.items():
        diffs = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
        add_stats(features, f"d_{name}", diffs)

    mag_diffs = [abs(magnitude[index] - magnitude[index - 1]) for index in range(1, len(magnitude))]
    add_stats(features, "d_mag", mag_diffs)
    return features


def add_stats(features: dict[str, float], prefix: str, values: list[float]) -> None:
    if not values:
        values = [0.0]

    avg = mean(values)
    variance = mean([(value - avg) ** 2 for value in values])
    rms = math.sqrt(mean([value * value for value in values]))
    sorted_values = sorted(values)
    features[f"{prefix}_mean"] = avg
    features[f"{prefix}_std"] = math.sqrt(variance)
    features[f"{prefix}_min"] = min(values)
    features[f"{prefix}_max"] = max(values)
    features[f"{prefix}_range"] = max(values) - min(values)
    features[f"{prefix}_rms"] = rms
    features[f"{prefix}_p25"] = percentile(sorted_values, 0.25)
    features[f"{prefix}_p75"] = percentile(sorted_values, 0.75)


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = q * (len(sorted_values) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return sorted_values[lower]
    weight = index - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def filter_labels(windows: list[Window], min_windows: int) -> tuple[list[Window], list[str]]:
    counts = Counter(window.label for window in windows)
    kept_labels = sorted(label for label, count in counts.items() if count >= min_windows)
    kept = [window for window in windows if window.label in kept_labels]
    return kept, kept_labels


def read_feature_windows(path: Path) -> tuple[list[Window], list[str]]:
    windows: list[Window] = []
    feature_names_from_file: list[str] = []

    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return [], []

        feature_names_from_file = [
            name for name in reader.fieldnames if name not in FEATURE_METADATA_COLUMNS
        ]

        for record in reader:
            source = (record.get("source") or "own").strip()
            label = (record.get("label") or "").strip()
            if source != "own":
                continue
            if label not in LABEL_NAMES:
                continue
            if label in TRAINABLE_EXCLUDED_LABELS:
                continue
            if not label:
                continue

            try:
                features = {name: float(record[name]) for name in feature_names_from_file}
                windows.append(
                    Window(
                        source=source,
                        label=label,
                        raw_label=(record.get("raw_label") or label).strip(),
                        cat_id=(record.get("cat_id") or "").strip(),
                        device_id=(record.get("device_id") or "").strip(),
                        file=(record.get("file") or "").strip(),
                        segment_id=(record.get("segment_id") or "").strip(),
                        start_seq=int(float(record.get("start_seq") or 0)),
                        end_seq=int(float(record.get("end_seq") or 0)),
                        start_ms=int(float(record.get("start_ms") or 0)),
                        end_ms=int(float(record.get("end_ms") or 0)),
                        features=features,
                    )
                )
            except (KeyError, ValueError) as exc:
                raise RuntimeError(f"Invalid feature row in {path}: {exc}") from exc

    return windows, feature_names_from_file


def train_test_split(windows: list[Window], test_ratio: float) -> tuple[list[Window], list[Window]]:
    rng = random.Random(RANDOM_SEED)
    by_label: dict[str, list[Window]] = defaultdict(list)
    for window in windows:
        by_label[window.label].append(window)

    train: list[Window] = []
    test: list[Window] = []
    for label_windows in by_label.values():
        shuffled = list(label_windows)
        rng.shuffle(shuffled)
        if len(shuffled) == 1:
            train.extend(shuffled)
            continue
        test_count = min(len(shuffled) - 1, max(1, int(round(len(shuffled) * test_ratio))))
        test.extend(shuffled[:test_count])
        train.extend(shuffled[test_count:])

    return train, test


def feature_names(windows: list[Window]) -> list[str]:
    names = sorted(windows[0].features)
    return names


def standardizer(windows: list[Window], names: list[str]) -> tuple[dict[str, float], dict[str, float]]:
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for name in names:
        values = [window.features[name] for window in windows]
        avg = mean(values)
        variance = mean([(value - avg) ** 2 for value in values])
        std = math.sqrt(variance) or 1.0
        means[name] = avg
        stds[name] = std
    return means, stds


def vectorize(window: Window, names: list[str], means: dict[str, float], stds: dict[str, float]) -> list[float]:
    return [(window.features[name] - means[name]) / stds[name] for name in names]


def train_centroids(
    windows: list[Window], names: list[str], means: dict[str, float], stds: dict[str, float]
) -> dict[str, list[float]]:
    vectors_by_label: dict[str, list[list[float]]] = defaultdict(list)
    for window in windows:
        vectors_by_label[window.label].append(vectorize(window, names, means, stds))

    centroids: dict[str, list[float]] = {}
    for label, vectors in vectors_by_label.items():
        centroids[label] = [mean([vector[index] for vector in vectors]) for index in range(len(names))]
    return centroids


def predict(vector: list[float], centroids: dict[str, list[float]]) -> str:
    best_label = ""
    best_distance = float("inf")
    for label, centroid in centroids.items():
        distance = sum((value - centroid[index]) ** 2 for index, value in enumerate(vector))
        if distance < best_distance:
            best_distance = distance
            best_label = label
    return best_label


def evaluate(
    windows: list[Window],
    names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
    centroids: dict[str, list[float]],
) -> dict[str, Any]:
    labels = sorted(centroids)
    confusion: dict[str, Counter[str]] = {label: Counter() for label in labels}
    correct = 0
    for window in windows:
        pred = predict(vectorize(window, names, means, stds), centroids)
        confusion[window.label][pred] += 1
        if pred == window.label:
            correct += 1

    total = len(windows)
    metrics = {}
    for label in labels:
        tp = confusion[label][label]
        predicted = sum(confusion[actual][label] for actual in labels)
        actual = sum(confusion[label].values())
        precision = tp / predicted if predicted else 0.0
        recall = tp / actual if actual else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        metrics[label] = {"precision": precision, "recall": recall, "f1": f1, "support": actual}

    return {
        "accuracy": correct / total if total else 0.0,
        "total": total,
        "labels": labels,
        "metrics": metrics,
        "confusion": {label: dict(confusion[label]) for label in labels},
    }


def write_windows_csv(path: Path, windows: list[Window], names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "source",
                "label",
                "raw_label",
                "cat_id",
                "device_id",
                "file",
                "segment_id",
                "start_seq",
                "end_seq",
                "start_ms",
                "end_ms",
                *names,
            ]
        )
        for window in windows:
            writer.writerow(
                [
                    window.source,
                    window.label,
                    window.raw_label,
                    window.cat_id,
                    window.device_id,
                    window.file,
                    window.segment_id,
                    window.start_seq,
                    window.end_seq,
                    window.start_ms,
                    window.end_ms,
                    *[window.features[name] for name in names],
                ]
            )


def write_report(
    path: Path,
    train_eval: dict[str, Any],
    test_eval: dict[str, Any],
    counts: Counter[str],
    source_counts: Counter[str],
    trim_stats: TrimStats,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        handle.write("CatSense V0 baseline nearest-centroid report\n")
        handle.write("============================================\n\n")
        handle.write("Preprocessing\n")
        handle.write(f"trim_edge_s={trim_stats.trim_edge_s:.3f}\n")
        if trim_stats.from_features:
            handle.write("input=prebuilt_features\n")
            handle.write(f"feature_segments={trim_stats.trimmed_segments}\n")
            handle.write(f"feature_window_sample_sum={trim_stats.trimmed_rows}\n\n")
        else:
            handle.write("input=raw_rows\n")
            handle.write(f"segments_original={trim_stats.original_segments}\n")
            handle.write(f"segments_used={trim_stats.trimmed_segments}\n")
            handle.write(f"segments_dropped_after_trim={trim_stats.dropped_segments}\n")
            handle.write(f"rows_original={trim_stats.original_rows}\n")
            handle.write(f"rows_used_after_trim={trim_stats.trimmed_rows}\n")
            handle.write(f"rows_dropped_by_trim={trim_stats.dropped_rows}\n\n")
        handle.write("Window counts by label\n")
        for label, count in counts.most_common():
            handle.write(f"- {label}: {count}\n")
        handle.write("\n")
        handle.write("Window counts by source\n")
        for source, count in source_counts.most_common():
            handle.write(f"- {source}: {count}\n")
        handle.write("\n")
        write_eval_section(handle, "Train", train_eval)
        write_eval_section(handle, "Test", test_eval)


def write_eval_section(handle: Any, title: str, result: dict[str, Any]) -> None:
    handle.write(f"{title}\n")
    handle.write(f"accuracy={result['accuracy']:.3f} total={result['total']}\n")
    handle.write("label, precision, recall, f1, support\n")
    for label in result["labels"]:
        metric = result["metrics"][label]
        handle.write(
            f"{label}, {metric['precision']:.3f}, {metric['recall']:.3f}, "
            f"{metric['f1']:.3f}, {metric['support']}\n"
        )
    handle.write("confusion actual -> predicted counts\n")
    for label in result["labels"]:
        handle.write(f"{label}: {result['confusion'][label]}\n")
    handle.write("\n")


def main() -> int:
    args = parse_args()
    window_samples = max(2, int(round(args.window_s * args.rate)))
    step_samples = max(1, int(round(args.step_s * args.rate)))

    use_features = args.features.is_file()
    if use_features:
        windows, names = read_feature_windows(args.features)
        trim_stats = TrimStats(trim_edge_s=max(0.0, args.trim_edge_s))
        trim_stats.from_features = True
        trim_stats.trimmed_segments = len({window.segment_id for window in windows})
        trim_stats.original_segments = trim_stats.trimmed_segments
        trim_stats.trimmed_rows = sum(int(window.features.get("samples", 0.0)) for window in windows)
        trim_stats.original_rows = trim_stats.trimmed_rows
    else:
        rows = read_rows(args.raw)
        if not rows:
            print(f"No labeled rows found under {args.raw}")
            return 1

        segments = split_segments(rows)
        segments, trim_stats = trim_segments(segments, args.trim_edge_s, window_samples)
        windows = build_windows(segments, window_samples, step_samples)
        names = feature_names(windows)

    windows, labels = filter_labels(windows, args.min_windows)
    if len(labels) < 2:
        print("Need at least two labels with enough windows to train.")
        return 1

    train, test = train_test_split(windows, args.test_ratio)
    means, stds = standardizer(train, names)
    centroids = train_centroids(train, names, means, stds)
    train_eval = evaluate(train, names, means, stds, centroids)
    test_eval = evaluate(test, names, means, stds, centroids)
    counts = Counter(window.label for window in windows)
    source_counts = Counter(window.source for window in windows)

    args.processed.mkdir(parents=True, exist_ok=True)
    args.models.mkdir(parents=True, exist_ok=True)
    write_windows_csv(args.processed / "windows.csv", windows, names)
    model_path, report_path = output_paths(args.models, args.model_name)

    model = {
        "model_type": "nearest_centroid",
        "rate_hz": args.rate,
        "window_s": args.window_s,
        "step_s": args.step_s,
        "trim_edge_s": max(0.0, args.trim_edge_s),
        "training_source": "own",
        "labels": sorted(centroids),
        "feature_names": names,
        "means": means,
        "stds": stds,
        "centroids": centroids,
        "label_counts": dict(counts),
        "source_counts": dict(source_counts),
        "test_accuracy": test_eval["accuracy"],
    }
    model_path.write_text(json.dumps(model, indent=2, ensure_ascii=False))
    write_report(report_path, train_eval, test_eval, counts, source_counts, trim_stats)

    print(f"windows={len(windows)} labels={','.join(sorted(centroids))}")
    print(f"source=own source_counts={dict(source_counts)}")
    print(
        f"trim_edge_s={trim_stats.trim_edge_s:.3f} "
        f"segments_used={trim_stats.trimmed_segments}/{trim_stats.original_segments} "
        f"rows_used={trim_stats.trimmed_rows}/{trim_stats.original_rows}"
    )
    print(f"train_accuracy={train_eval['accuracy']:.3f} test_accuracy={test_eval['accuracy']:.3f}")
    print(f"features={args.processed / 'windows.csv'}")
    print(f"model={model_path}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
