#!/usr/bin/env python3
"""Evaluate the baseline model with whole recording sessions held out."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from train_baseline import (
    Window,
    predict,
    read_feature_windows,
    standardizer,
    train_centroids,
    vectorize,
)


@dataclass
class FoldResult:
    session: str
    train_windows: int
    test_windows: int
    accuracy: float
    labels: list[str]
    confusion: dict[str, Counter[str]]


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = default_root()
    parser = argparse.ArgumentParser(description="Evaluate CatSense V0 by holding out whole CSV sessions.")
    parser.add_argument("--features", type=Path, default=root / "data" / "processed" / "features.csv")
    parser.add_argument("--reports", type=Path, default=root / "models")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--min-windows", type=int, default=8)
    parser.add_argument("--min-test-windows", type=int, default=1)
    return parser.parse_args()


def labels_with_min_windows(windows: list[Window], min_windows: int) -> set[str]:
    counts = Counter(window.label for window in windows)
    return {label for label, count in counts.items() if count >= min_windows}


def evaluate_fold(
    *,
    session: str,
    train: list[Window],
    test: list[Window],
    feature_names: list[str],
) -> FoldResult:
    means, stds = standardizer(train, feature_names)
    centroids = train_centroids(train, feature_names, means, stds)
    labels = sorted(centroids)
    confusion: dict[str, Counter[str]] = {label: Counter() for label in labels}
    correct = 0

    for window in test:
        prediction = predict(vectorize(window, feature_names, means, stds), centroids)
        confusion[window.label][prediction] += 1
        if prediction == window.label:
            correct += 1

    return FoldResult(
        session=session,
        train_windows=len(train),
        test_windows=len(test),
        accuracy=correct / len(test) if test else 0.0,
        labels=labels,
        confusion=confusion,
    )


def aggregate_confusion(folds: list[FoldResult]) -> dict[str, Counter[str]]:
    labels = sorted({label for fold in folds for label in fold.labels})
    confusion: dict[str, Counter[str]] = {label: Counter() for label in labels}
    for fold in folds:
        for label, counts in fold.confusion.items():
            confusion.setdefault(label, Counter()).update(counts)
    return confusion


def metrics_from_confusion(confusion: dict[str, Counter[str]]) -> dict[str, Any]:
    labels = sorted(confusion)
    total = sum(sum(counts.values()) for counts in confusion.values())
    correct = sum(confusion[label][label] for label in labels)
    metrics = {}

    for label in labels:
        tp = confusion[label][label]
        predicted = sum(confusion[actual][label] for actual in labels)
        actual = sum(confusion[label].values())
        precision = tp / predicted if predicted else 0.0
        recall = tp / actual if actual else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        metrics[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": actual,
        }

    return {
        "accuracy": correct / total if total else 0.0,
        "total": total,
        "labels": labels,
        "metrics": metrics,
        "confusion": confusion,
    }


def write_report(
    path: Path,
    *,
    features_path: Path,
    windows: list[Window],
    folds: list[FoldResult],
    skipped: list[str],
    min_windows: int,
    min_test_windows: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    confusion = aggregate_confusion(folds)
    overall = metrics_from_confusion(confusion)

    with path.open("w") as handle:
        handle.write("CatSense V0 session holdout evaluation\n")
        handle.write("======================================\n\n")
        handle.write("Input\n")
        handle.write(f"features={features_path}\n")
        handle.write(f"windows={len(windows)}\n")
        handle.write(f"sessions_total={len({window.file for window in windows})}\n")
        handle.write(f"sessions_evaluated={len(folds)}\n")
        handle.write(f"sessions_skipped={len(skipped)}\n")
        handle.write(f"min_windows={min_windows}\n")
        handle.write(f"min_test_windows={min_test_windows}\n\n")

        handle.write("Overall\n")
        handle.write(f"accuracy={overall['accuracy']:.3f} total={overall['total']}\n")
        handle.write("label, precision, recall, f1, support\n")
        for label in overall["labels"]:
            metric = overall["metrics"][label]
            handle.write(
                f"{label}, {metric['precision']:.3f}, {metric['recall']:.3f}, "
                f"{metric['f1']:.3f}, {metric['support']}\n"
            )
        handle.write("\n")

        handle.write("Session results\n")
        handle.write("session, test_windows, train_windows, accuracy, labels\n")
        for fold in sorted(folds, key=lambda item: item.session):
            handle.write(
                f"{fold.session}, {fold.test_windows}, {fold.train_windows}, "
                f"{fold.accuracy:.3f}, {'/'.join(fold.labels)}\n"
            )
        handle.write("\n")

        handle.write("Confusion actual -> predicted counts\n")
        for label in overall["labels"]:
            handle.write(f"{label}: {dict(confusion[label])}\n")

        if skipped:
            handle.write("\nSkipped sessions\n")
            for item in skipped:
                handle.write(f"- {item}\n")


def main() -> int:
    args = parse_args()
    report_path = args.report or args.reports / "session_eval_report.txt"

    if not args.features.is_file():
        print(f"Features file not found: {args.features}")
        print("Run build_dataset.py first.")
        return 1

    windows, feature_names = read_feature_windows(args.features)
    if not windows:
        print(f"No feature windows found in {args.features}")
        return 1

    sessions = sorted({window.file for window in windows})
    folds: list[FoldResult] = []
    skipped: list[str] = []

    for session in sessions:
        train_all = [window for window in windows if window.file != session]
        test_all = [window for window in windows if window.file == session]
        train_labels = labels_with_min_windows(train_all, args.min_windows)
        if len(train_labels) < 2:
            skipped.append(f"{session}: fewer than two train labels with {args.min_windows}+ windows")
            continue

        train = [window for window in train_all if window.label in train_labels]
        test = [window for window in test_all if window.label in train_labels]
        if len(test) < args.min_test_windows:
            skipped.append(f"{session}: no test windows with labels present in train")
            continue

        folds.append(
            evaluate_fold(
                session=session,
                train=train,
                test=test,
                feature_names=feature_names,
            )
        )

    if not folds:
        print("No sessions could be evaluated.")
        return 1

    write_report(
        report_path,
        features_path=args.features,
        windows=windows,
        folds=folds,
        skipped=skipped,
        min_windows=args.min_windows,
        min_test_windows=args.min_test_windows,
    )

    overall = metrics_from_confusion(aggregate_confusion(folds))
    print(f"sessions={len(folds)}/{len(sessions)} windows={overall['total']}")
    print(f"session_holdout_accuracy={overall['accuracy']:.3f}")
    print(f"labels={','.join(overall['labels'])}")
    print(f"report={report_path}")
    if skipped:
        print(f"skipped_sessions={len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
