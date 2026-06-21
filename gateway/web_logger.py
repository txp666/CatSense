#!/usr/bin/env python3
"""Local web dashboard for live CatSense V0 collection."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import mimetypes
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from train_baseline import Row as FeatureRow
from train_baseline import extract_features


DEVICE_NAME = "CatSense-V0"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
VALID_RATES = {25, 50}
VALID_SAVE_MODES = {"daily", "session", "preview"}
DEFAULT_SAVE_MODE = "daily"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000

CSV_HEADER = (
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
    "marker",
    "marker_time_iso",
    "marker_note",
)

LABEL_ZH = {
    "rest": "休息",
    "parkour": "跑酷",
    "walk": "走动",
    "play": "玩耍",
    "groom": "舔毛",
    "eat": "进食",
}


@dataclass
class Sample:
    seq: int
    device_ms: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    battery_mv: int


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_output_dir() -> Path:
    return default_root() / "data" / "raw"


def default_model_path() -> Path:
    return default_root() / "models" / "baseline_centroid.json"


def default_firmware_zip_path() -> Path:
    return (
        default_root()
        / "firmware"
        / "xiao_nrf52840_sense"
        / ".pio"
        / "build"
        / "seeed_xiao_nrf52840_sense"
        / "firmware.zip"
    )


def firmware_info(path: Path | None = None) -> dict[str, Any]:
    target = path or default_firmware_zip_path()
    if not target.is_file():
        return {
            "exists": False,
            "path": str(target),
            "size_bytes": 0,
            "modified_iso": "",
        }

    stat = target.stat()
    return {
        "exists": True,
        "path": str(target),
        "size_bytes": stat.st_size,
        "modified_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def is_lan_ip(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(part) for part in parts]
    except ValueError:
        return False

    if octets[0] == 10:
        return True
    if octets[0] == 192 and octets[1] == 168:
        return True
    return octets[0] == 172 and 16 <= octets[1] <= 31


def get_mac_interface_ip() -> str | None:
    for interface in ("en0", "en1", "en2", "en3", "en4", "bridge100"):
        try:
            result = subprocess.run(
                ["ipconfig", "getifaddr", interface],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue

        ip = result.stdout.strip()
        if is_lan_ip(ip):
            return ip

    return None


def get_route_ip() -> str | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        except OSError:
            return None

    return ip if is_lan_ip(ip) else None


def get_lan_ip() -> str | None:
    return get_mac_interface_ip() or get_route_ip()


def print_server_urls(host: str, port: int) -> None:
    print(f"CatSense web logger listening on {host}:{port}")
    print(f"Computer: http://127.0.0.1:{port}")

    lan_ip = get_lan_ip()
    if host in {"0.0.0.0", "::"} and lan_ip:
        print(f"Phone:    http://{lan_ip}:{port}")
    elif host not in {"127.0.0.1", "localhost"}:
        print(f"Phone:    http://{host}:{port}")
    else:
        print("Phone:    unavailable because host is localhost only; restart with --host 0.0.0.0")


def parse_sample(line: str) -> Sample | None:
    parts = line.strip().split(",")
    if len(parts) != 7 or parts[0] != "CS0":
        return None

    try:
        return Sample(
            seq=int(parts[1]),
            device_ms=int(parts[2]),
            ax_mg=int(parts[3]),
            ay_mg=int(parts[4]),
            az_mg=int(parts[5]),
            battery_mv=int(parts[6]),
        )
    except ValueError:
        return None


class RealtimePredictor:
    """Run the baseline model on a rolling live sample window."""

    PREDICT_INTERVAL_MS = 500
    MIN_WINDOW_COVERAGE = 0.75
    SCORE_TEMPERATURE = 0.8
    SMOOTH_ALPHA = 0.38
    SWITCH_MARGIN = 0.045
    RAW_SWITCH_MARGIN = 0.04
    RAW_STREAK_TO_SWITCH = 3
    SWITCH_COOLDOWN_MS = 2000

    def __init__(self, model_path: Path, enabled: bool = True) -> None:
        self.model_path = model_path
        self.enabled = enabled
        self.error = ""
        self.model_type = ""
        self.model_rate_hz = 25.0
        self.window_s = 2.0
        self.feature_names: list[str] = []
        self.means: dict[str, float] = {}
        self.stds: dict[str, float] = {}
        self.centroids: dict[str, list[float]] = {}
        self.buffer: deque[Sample] = deque()
        self.last_predict_ms: int | None = None
        self.smoothed_scores: dict[str, float] = {}
        self.stable_label = ""
        self.last_switch_ms: int | None = None
        self.last_raw_label = ""
        self.raw_label_streak = 0
        self.current_prediction = self._status(self._idle_message())

        if enabled:
            self._load_model()
            self.current_prediction = self._status(self._idle_message())

    @property
    def active(self) -> bool:
        return self.enabled and not self.error and bool(self.centroids)

    def _load_model(self) -> None:
        self.error = ""
        self.centroids = {}
        if not self.model_path.is_file():
            self.error = f"Model file not found: {self.model_path}"
            return

        try:
            data = json.loads(self.model_path.read_text(encoding="utf-8"))
            self.model_type = str(data.get("model_type") or "")
            self.model_rate_hz = float(data["rate_hz"])
            self.window_s = float(data["window_s"])
            self.feature_names = [str(name) for name in data["feature_names"]]
            self.means = {str(key): float(value) for key, value in data["means"].items()}
            self.stds = {str(key): float(value) or 1.0 for key, value in data["stds"].items()}
            self.centroids = {
                str(label): [float(value) for value in values]
                for label, values in data["centroids"].items()
                if str(label) in LABEL_ZH
            }
            if not self.centroids:
                raise RuntimeError("model has no currently enabled labels")
        except Exception as exc:
            self.error = f"Could not load model: {exc}"

    def reset(self) -> dict[str, Any]:
        self.buffer.clear()
        self.last_predict_ms = None
        self._reset_smoothing()
        if self.enabled:
            self._load_model()
        self.current_prediction = self._status(self._idle_message())
        return self.current_prediction

    def add_sample(self, sample: Sample) -> dict[str, Any] | None:
        if not self.active:
            return None

        if self.buffer and sample.device_ms <= self.buffer[-1].device_ms:
            self.buffer.clear()
            self.last_predict_ms = None
            self._reset_smoothing()

        self.buffer.append(sample)
        keep_after_ms = sample.device_ms - int(self.window_s * 1000) - 1000
        while self.buffer and self.buffer[0].device_ms < keep_after_ms:
            self.buffer.popleft()

        if self.last_predict_ms is not None and sample.device_ms - self.last_predict_ms < self.PREDICT_INTERVAL_MS:
            return None

        self.last_predict_ms = sample.device_ms
        self.current_prediction = self._predict(sample.device_ms)
        return self.current_prediction

    def _predict(self, end_ms: int) -> dict[str, Any]:
        window_ms = int(round(self.window_s * 1000))
        start_ms = end_ms - window_ms
        window = [sample for sample in self.buffer if sample.device_ms >= start_ms]

        target_samples = max(2, int(round(self.model_rate_hz * self.window_s)))
        if len(window) < max(4, target_samples // 2):
            return self._status("等待窗口数据", samples=len(window))

        covered_ms = window[-1].device_ms - window[0].device_ms
        if covered_ms < window_ms * self.MIN_WINDOW_COVERAGE:
            return self._status("等待窗口数据", samples=len(window))

        rows = self._resample(window, start_ms, end_ms, target_samples)
        features = extract_features(rows)
        vector = [
            (features.get(name, 0.0) - self.means.get(name, 0.0)) / self.stds.get(name, 1.0)
            for name in self.feature_names
        ]
        distances = self._distances(vector)
        raw_scores = self._raw_scores(distances)
        smoothed_scores = self._smooth_scores(raw_scores)
        ranked = sorted(smoothed_scores.items(), key=lambda item: item[1], reverse=True)
        raw_label = str(distances[0]["label"])
        label, stability = self._stable_label(raw_label, ranked, raw_scores, end_ms)
        top_score = ranked[0][1] if ranked else 0.0
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = top_score - second_score

        top = []
        for item_label, score in ranked[:4]:
            top.append(
                {
                    "label": item_label,
                    "label_zh": LABEL_ZH.get(item_label, item_label),
                    "score": round(score, 3),
                }
            )

        best_distance = float(distances[0]["distance"])
        stable_score = smoothed_scores.get(label, top_score)
        return {
            "enabled": True,
            "ready": True,
            "label": label,
            "label_zh": LABEL_ZH.get(label, label),
            "raw_label": raw_label,
            "raw_label_zh": LABEL_ZH.get(raw_label, raw_label),
            "confidence": round(stable_score, 3),
            "margin": round(margin, 3),
            "distance": round(best_distance, 3),
            "stability": stability,
            "stability_zh": self._stability_zh(stability),
            "window_s": self.window_s,
            "samples": len(rows),
            "model_rate_hz": self.model_rate_hz,
            "model_path": str(self.model_path),
            "updated_at_iso": datetime.now().isoformat(timespec="milliseconds"),
            "message": self._prediction_message(stability, margin),
            "top": top,
        }

    def _resample(
        self,
        window: list[Sample],
        start_ms: int,
        end_ms: int,
        target_samples: int,
    ) -> list[FeatureRow]:
        rows: list[FeatureRow] = []
        index = 0
        span_ms = max(1, end_ms - start_ms)

        for seq in range(target_samples):
            target_ms = start_ms + (span_ms * seq) / max(1, target_samples - 1)
            while index + 1 < len(window) and window[index + 1].device_ms < target_ms:
                index += 1

            left = window[index]
            right = window[index + 1] if index + 1 < len(window) else left
            if target_ms <= left.device_ms or right.device_ms == left.device_ms:
                ax_mg, ay_mg, az_mg = left.ax_mg, left.ay_mg, left.az_mg
            else:
                ratio = (target_ms - left.device_ms) / (right.device_ms - left.device_ms)
                ax_mg = int(round(left.ax_mg + (right.ax_mg - left.ax_mg) * ratio))
                ay_mg = int(round(left.ay_mg + (right.ay_mg - left.ay_mg) * ratio))
                az_mg = int(round(left.az_mg + (right.az_mg - left.az_mg) * ratio))

            rows.append(
                FeatureRow(
                    file="live",
                    device_ms=int(round(target_ms)),
                    seq=seq,
                    ax_mg=ax_mg,
                    ay_mg=ay_mg,
                    az_mg=az_mg,
                    label="live",
                )
            )

        return rows

    def _distances(self, vector: list[float]) -> list[dict[str, float | str]]:
        distances: list[dict[str, float | str]] = []
        width = max(1, len(vector))
        for label, centroid in self.centroids.items():
            squared = sum((value - centroid[index]) ** 2 for index, value in enumerate(vector))
            distances.append({"label": label, "distance": math.sqrt(squared / width)})
        return sorted(distances, key=lambda item: float(item["distance"]))

    def _raw_scores(self, distances: list[dict[str, float | str]]) -> dict[str, float]:
        best_distance = float(distances[0]["distance"])
        scores: dict[str, float] = {}
        for item in distances:
            label = str(item["label"])
            distance_delta = max(0.0, float(item["distance"]) - best_distance)
            scores[label] = math.exp(-min(60.0, distance_delta / self.SCORE_TEMPERATURE))

        total = sum(scores.values()) or 1.0
        return {label: value / total for label, value in scores.items()}

    def _smooth_scores(self, raw_scores: dict[str, float]) -> dict[str, float]:
        if not self.smoothed_scores:
            self.smoothed_scores = dict(raw_scores)
        else:
            for label in self.centroids:
                old_value = self.smoothed_scores.get(label, raw_scores.get(label, 0.0))
                raw_value = raw_scores.get(label, 0.0)
                self.smoothed_scores[label] = old_value * (1.0 - self.SMOOTH_ALPHA) + raw_value * self.SMOOTH_ALPHA

        total = sum(self.smoothed_scores.values()) or 1.0
        self.smoothed_scores = {
            label: value / total
            for label, value in self.smoothed_scores.items()
        }
        return dict(self.smoothed_scores)

    def _stable_label(
        self,
        raw_label: str,
        ranked: list[tuple[str, float]],
        raw_scores: dict[str, float],
        end_ms: int,
    ) -> tuple[str, str]:
        if not ranked:
            return "", "waiting"

        if raw_label == self.last_raw_label:
            self.raw_label_streak += 1
        else:
            self.last_raw_label = raw_label
            self.raw_label_streak = 1

        candidate, candidate_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = candidate_score - second_score

        if not self.stable_label:
            self.stable_label = candidate
            self.last_switch_ms = end_ms
        elif candidate != self.stable_label:
            current_score = dict(ranked).get(self.stable_label, 0.0)
            current_raw_score = raw_scores.get(self.stable_label, 0.0)
            raw_candidate_score = raw_scores.get(raw_label, 0.0)
            strong_enough = candidate_score >= current_score + self.SWITCH_MARGIN
            cooldown_ready = (
                self.last_switch_ms is None
                or end_ms - self.last_switch_ms >= self.SWITCH_COOLDOWN_MS
            )
            raw_switch_enough = (
                raw_label != self.stable_label
                and self.raw_label_streak >= self.RAW_STREAK_TO_SWITCH
                and raw_candidate_score >= current_raw_score + self.RAW_SWITCH_MARGIN
            )
            repeated_enough = raw_label == candidate and self.raw_label_streak >= self.RAW_STREAK_TO_SWITCH
            if cooldown_ready and ((strong_enough and repeated_enough) or raw_switch_enough):
                if raw_switch_enough:
                    candidate = raw_label
                    self.smoothed_scores[candidate] = max(
                        self.smoothed_scores.get(candidate, 0.0),
                        raw_candidate_score,
                    )
                    if self.stable_label in self.smoothed_scores:
                        self.smoothed_scores[self.stable_label] = min(
                            self.smoothed_scores[self.stable_label],
                            current_raw_score,
                        )
                self.stable_label = candidate
                self.last_switch_ms = end_ms

        stable_score = dict(ranked).get(self.stable_label, candidate_score)
        if stable_score < 0.22 or margin < 0.025:
            return self.stable_label, "low_confidence"
        if self.stable_label != candidate:
            return self.stable_label, "holding"
        if stable_score >= 0.34 and margin >= 0.08:
            return self.stable_label, "stable"
        return self.stable_label, "watching"

    def _reset_smoothing(self) -> None:
        self.smoothed_scores = {}
        self.stable_label = ""
        self.last_switch_ms = None
        self.last_raw_label = ""
        self.raw_label_streak = 0

    def _stability_zh(self, stability: str) -> str:
        return {
            "stable": "稳定",
            "watching": "观察中",
            "holding": "保持中",
            "low_confidence": "低置信",
            "waiting": "等待中",
        }.get(stability, "观察中")

    def _prediction_message(self, stability: str, margin: float) -> str:
        if stability == "low_confidence":
            return "几个动作很接近，继续观察"
        if stability == "holding":
            return "新窗口变化不够明显，暂不切换"
        if stability == "stable":
            return "连续窗口较稳定"
        return f"分差 {margin:.2f}"

    def _status(self, message: str, *, samples: int = 0) -> dict[str, Any]:
        return {
            "enabled": self.active,
            "ready": False,
            "label": "",
            "label_zh": "",
            "confidence": 0.0,
            "margin": 0.0,
            "distance": 0.0,
            "window_s": self.window_s,
            "samples": samples,
            "model_rate_hz": self.model_rate_hz,
            "model_path": str(self.model_path),
            "updated_at_iso": "",
            "message": self.error if self.error else message,
            "top": [],
        }

    def _idle_message(self) -> str:
        if not self.enabled:
            return "预测已关闭"
        if self.error:
            return self.error
        return "等待采集数据"


async def find_device(device_name: str, timeout: float) -> BLEDevice:
    def matches(candidate: BLEDevice, advertisement: AdvertisementData) -> bool:
        names = {candidate.name, advertisement.local_name}
        return device_name in names

    device = await BleakScanner.find_device_by_filter(matches, timeout=timeout)
    if device is None:
        raise RuntimeError(f"Could not find BLE device named {device_name!r}.")
    return device


async def write_command(client: BleakClient, command: str) -> None:
    await client.write_gatt_char(RX_UUID, f"{command}\n".encode("ascii"), response=True)


class CatSenseWebSession:
    def __init__(self, loop: asyncio.AbstractEventLoop, model_path: Path, enable_prediction: bool) -> None:
        self.loop = loop
        self.lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.device_lock = threading.Lock()
        self.processing = False
        self.device_busy = False
        self.subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self.pending_markers: deque[dict[str, str]] = deque()
        self.task: asyncio.Task[None] | None = None
        self.stop_event: asyncio.Event | None = None
        self.predictor = RealtimePredictor(model_path, enable_prediction)
        self.reset_state()

    def reset_state(self) -> None:
        self.status = "idle"
        self.running = False
        self.connected = False
        self.current_label = ""
        self.cat_id = "cat001"
        self.rate = 25
        self.device = DEVICE_NAME
        self.save_mode = DEFAULT_SAVE_MODE
        self.output_path = ""
        self.samples = 0
        self.started_at_iso = ""
        self.start_monotonic: float | None = None
        self.last_sample_monotonic: float | None = None
        self.observed_rate_hz = 0.0
        self.battery_mv: int | None = None
        self.last_sample: dict[str, Any] | None = None
        self.prediction = self.predictor.reset()
        self.error = ""
        self.warning = ""
        self.markers: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            duration = 0.0
            if self.start_monotonic is not None:
                duration = max(0.0, time.monotonic() - self.start_monotonic)

            return {
                "status": self.status,
                "running": self.running,
                "connected": self.connected,
                "label": self.current_label,
                "current_label": self.current_label,
                "cat_id": self.cat_id,
                "rate": self.rate,
                "device": self.device,
                "save_mode": self.save_mode,
                "output_path": self.output_path,
                "samples": self.samples,
                "started_at_iso": self.started_at_iso,
                "duration_s": round(duration, 3),
                "observed_rate_hz": round(self.observed_rate_hz, 3),
                "battery_mv": self.battery_mv,
                "last_sample": self.last_sample,
                "prediction": self.prediction,
                "processing": self.processing,
                "device_busy": self.device_busy,
                "error": self.error,
                "warning": self.warning,
                "markers": list(self.markers[-20:]),
            }

    def add_subscriber(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            self.subscribers.add(subscriber)

    def remove_subscriber(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            self.subscribers.discard(subscriber)

    def broadcast(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data}
        with self.lock:
            subscribers = list(self.subscribers)

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                pass

    def update_status(self, status: str, **fields: Any) -> None:
        with self.lock:
            self.status = status
            for key, value in fields.items():
                setattr(self, key, value)
        self.broadcast("state", self.snapshot())

    def start_threadsafe(self, config: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run_coroutine_threadsafe(self.start(config), self.loop).result(timeout=5)

    def stop_threadsafe(self) -> dict[str, Any]:
        return asyncio.run_coroutine_threadsafe(self.stop(), self.loop).result(timeout=10)

    def mark_threadsafe(self, marker: str, note: str) -> dict[str, Any]:
        return asyncio.run_coroutine_threadsafe(self.mark(marker, note), self.loop).result(timeout=5)

    def set_label_threadsafe(self, label: str) -> dict[str, Any]:
        return asyncio.run_coroutine_threadsafe(self.set_label(label), self.loop).result(timeout=5)

    def process_threadsafe(self, action: str) -> dict[str, Any]:
        if not self.process_lock.acquire(blocking=False):
            raise RuntimeError("Data processing is already running.")

        should_reload_model = False
        with self.lock:
            if self.running:
                self.process_lock.release()
                raise RuntimeError("Stop recording before running data processing.")
            if self.device_busy:
                self.process_lock.release()
                raise RuntimeError("Wait for device operation to finish before running data processing.")
            self.processing = True
        self.broadcast("state", self.snapshot())

        try:
            action = action.strip().lower()
            actions = {
                "report": [("检查数据", "dataset_report.py")],
                "build": [("构建数据", "build_dataset.py")],
                "train": [("训练模型", "train_baseline.py")],
                "evaluate": [("Session 评估", "evaluate_by_session.py")],
                "all": [
                    ("检查数据", "dataset_report.py"),
                    ("构建数据", "build_dataset.py"),
                    ("训练模型", "train_baseline.py"),
                    ("Session 评估", "evaluate_by_session.py"),
                ],
            }
            if action not in actions:
                raise RuntimeError("Unknown processing action.")

            started = datetime.now().isoformat(timespec="milliseconds")
            gateway_dir = Path(__file__).resolve().parent
            env = os.environ.copy()
            env.setdefault("PYTHONPYCACHEPREFIX", "/private/tmp/catsense_pycache")
            results: list[dict[str, Any]] = []
            ok = True

            for title, script in actions[action]:
                command = [sys.executable, script]
                before = time.monotonic()
                try:
                    completed = subprocess.run(
                        command,
                        cwd=gateway_dir,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=False,
                    )
                    returncode = completed.returncode
                    stdout = completed.stdout.strip()
                    stderr = completed.stderr.strip()
                except subprocess.TimeoutExpired as exc:
                    returncode = -1
                    stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
                    stderr = f"Timed out after {exc.timeout} seconds."
                except OSError as exc:
                    returncode = -1
                    stdout = ""
                    stderr = str(exc)

                duration_s = time.monotonic() - before
                step = {
                    "title": title,
                    "script": script,
                    "returncode": returncode,
                    "duration_s": round(duration_s, 3),
                    "stdout": stdout,
                    "stderr": stderr,
                }
                results.append(step)
                if returncode != 0:
                    ok = False
                    break
                if script == "train_baseline.py":
                    should_reload_model = True

            if ok and should_reload_model:
                with self.lock:
                    self.prediction = self.predictor.reset()

            finished = datetime.now().isoformat(timespec="milliseconds")
            summary = self._summarize_process_results(results)
            payload = {
                "action": action,
                "ok": ok,
                "started_at_iso": started,
                "finished_at_iso": finished,
                "results": results,
                "summary": summary,
            }
            self.broadcast("process", payload)
            return payload
        finally:
            with self.lock:
                self.processing = False
            self.broadcast("state", self.snapshot())
            if self.process_lock.locked():
                self.process_lock.release()

    def _summarize_process_results(self, results: list[dict[str, Any]]) -> list[str]:
        summary: list[str] = []
        for result in results:
            title = str(result.get("title") or "数据处理")
            stdout = str(result.get("stdout") or "")
            for line in stdout.splitlines():
                translated = self._translate_summary_line(line.strip())
                if translated:
                    summary.append(f"{title}：{translated}")
            if result.get("returncode") != 0:
                summary.append(f"{title}：失败，退出码 {result.get('returncode')}")
        return summary

    def _translate_summary_line(self, line: str) -> str:
        if not line:
            return ""

        collect_need = self._translate_collect_need_line(line)
        if collect_need:
            return collect_need

        if "=" not in line:
            return ""

        pairs: dict[str, str] = {}
        for part in line.split():
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            pairs[key] = value

        parts: list[str] = []
        if "samples" in pairs:
            parts.append(f"样本数 {pairs['samples']}")
        if "sessions" in pairs:
            parts.append(f"Session {pairs['sessions']}")
        if "windows" in pairs:
            parts.append(f"窗口数 {pairs['windows']}")
        if "labels" in pairs:
            labels = "、".join(LABEL_ZH.get(label, label) for label in pairs["labels"].split(",") if label)
            parts.append(f"标签 {labels}")
        if "session_holdout_accuracy" in pairs:
            parts.append(f"Session 留出准确率 {self._format_accuracy(pairs['session_holdout_accuracy'])}")
        if "train_accuracy" in pairs:
            parts.append(f"训练准确率 {self._format_accuracy(pairs['train_accuracy'])}")
        if "test_accuracy" in pairs:
            parts.append(f"测试准确率 {self._format_accuracy(pairs['test_accuracy'])}")
        if "time_gaps_over_200ms" in pairs:
            parts.append(f"时间间隔异常 {pairs['time_gaps_over_200ms']}")
        if "seq_gaps" in pairs:
            parts.append(f"序号跳变 {pairs['seq_gaps']}")
        if "markers" in pairs:
            parts.append(f"标记事件 {pairs['markers']}")
        if "parse_errors" in pairs:
            parts.append(f"解析错误 {pairs['parse_errors']}")
        if "features" in pairs:
            parts.append(f"{self._output_file_name(pairs['features'])}：{pairs['features']}")
        if "model" in pairs:
            parts.append(f"模型文件：{pairs['model']}")
        if "report" in pairs:
            parts.append(f"报告文件：{pairs['report']}")

        return "，".join(parts)

    def _translate_collect_need_line(self, line: str) -> str:
        if not line.startswith("- ") or "collect about" not in line:
            return ""

        item = line[2:].strip()
        if ":" not in item:
            return f"待补采：{item}"

        label_part, detail = item.split(":", 1)
        label_name = label_part.split("(", 1)[0].strip()
        current = detail.split(" now", 1)[0].strip()
        more = detail.rsplit("collect about", 1)[-1].replace("more", "").strip()
        return f"待补采：{label_name} 当前 {current}，建议再采集约 {more}"

    def _format_accuracy(self, value: str) -> str:
        try:
            number = float(value)
        except ValueError:
            return value
        if 0.0 <= number <= 1.0:
            return f"{number * 100:.1f}%"
        return f"{number:.3f}"

    def _output_file_name(self, path: str) -> str:
        name = Path(path).name
        if name == "features.csv":
            return "特征文件"
        if name == "windows.csv":
            return "窗口文件"
        if name == "unified_samples.csv":
            return "统一样本文件"
        return "输出文件"

    def device_progress(
        self,
        action: str,
        percent: int,
        message: str,
        *,
        state: str = "running",
        detail: str = "",
    ) -> None:
        self.broadcast(
            "device_progress",
            {
                "action": action,
                "action_zh": self._device_action_name(action),
                "percent": max(0, min(100, int(percent))),
                "message": message,
                "state": state,
                "detail": detail,
                "updated_at_iso": datetime.now().isoformat(timespec="milliseconds"),
            },
        )

    def device_threadsafe(self, config: dict[str, Any]) -> dict[str, Any]:
        action = str(config.get("action") or "").strip().lower()
        scan_timeout = float(config.get("scan_timeout") or 30)
        connect_retries = max(1, int(config.get("connect_retries") or 2))
        if action in {"flash", "flash_fast", "flash_safe", "reboot_dfu"}:
            timeout = 900.0
        else:
            timeout = max(90.0, scan_timeout * connect_retries + 70.0)
        future = asyncio.run_coroutine_threadsafe(self.device_operation(config), self.loop)
        return future.result(timeout=timeout)

    async def device_operation(self, config: dict[str, Any]) -> dict[str, Any]:
        started = datetime.now().isoformat(timespec="milliseconds")
        action = str(config.get("action") or "").strip().lower()
        device = str(config.get("device") or DEVICE_NAME).strip()
        cat_id = str(config.get("cat_id") or "cat001").strip() or "cat001"
        scan_timeout = float(config.get("scan_timeout") or 30)
        connect_retries = max(1, int(config.get("connect_retries") or 2))
        out_dir = Path(str(config.get("out") or default_output_dir())).expanduser().resolve()

        if not self.device_lock.acquire(blocking=False):
            raise RuntimeError("Device operation is already running.")

        with self.lock:
            if self.running:
                self.device_lock.release()
                raise RuntimeError("Stop recording before running device operations.")
            if self.processing:
                self.device_lock.release()
                raise RuntimeError("Wait for data processing to finish before running device operations.")
            self.device_busy = True
            self.error = ""

        self.broadcast("state", self.snapshot())
        self.broadcast("log", {"message": f"Device action started: {self._device_action_name(action)}"})
        self.device_progress(action, 5, "准备执行设备操作")

        try:
            payload = await self._run_device_operation(
                action=action,
                device=device,
                cat_id=cat_id,
                out_dir=out_dir,
                scan_timeout=scan_timeout,
                connect_retries=connect_retries,
                started=started,
            )
        except Exception as exc:
            error_message = self._friendly_device_error(str(exc))
            payload = {
                "action": action,
                "action_zh": self._device_action_name(action),
                "ok": False,
                "started_at_iso": started,
                "finished_at_iso": datetime.now().isoformat(timespec="milliseconds"),
                "summary": [f"失败：{error_message}"],
                "lines": [],
                "samples": 0,
                "output_path": "",
                "error": error_message,
            }
            self.device_progress(action, 100, f"失败：{error_message}", state="error")
            self.broadcast("error", {"message": error_message})
        finally:
            with self.lock:
                self.device_busy = False
            self.broadcast("state", self.snapshot())
            self.device_lock.release()

        self.broadcast("device", payload)
        return payload

    def _friendly_device_error(self, message: str) -> str:
        if "Operation Failed" in message and "notification from device" in message:
            return (
                "DFU bootloader 拒绝了部分固件数据。请让电脑靠近板子，保持板子红灯闪烁的 DFU 状态，"
                "然后使用“慢速重试”。"
            )
        if "Could not find BLE DFU device" in message:
            return (
                "没有扫描到 DFU bootloader。请确认板子已经红灯闪烁，或先点“进入 OTA”；"
                "如果仍失败，双击 reset 进入 bootloader 后再点“刷写固件”。"
            )
        return message

    async def _run_device_operation(
        self,
        *,
        action: str,
        device: str,
        cat_id: str,
        out_dir: Path,
        scan_timeout: float,
        connect_retries: int,
        started: str,
    ) -> dict[str, Any]:
        if action not in {
            "status",
            "collect",
            "daily",
            "upload",
            "clear",
            "ota",
            "flash",
            "flash_fast",
            "flash_safe",
            "reboot_dfu",
        }:
            raise RuntimeError("Unknown device action.")

        if action == "reboot_dfu":
            return await self._run_dfu_reboot_operation(
                action=action,
                device=device,
                scan_timeout=scan_timeout,
                started=started,
            )

        if action in {"flash", "flash_fast", "flash_safe"}:
            return await self._run_flash_operation(
                action=action,
                device=device,
                scan_timeout=scan_timeout,
                connect_retries=connect_retries,
                started=started,
            )

        line_queue: asyncio.Queue[str] = asyncio.Queue()
        notify_buffer = bytearray()
        client: BleakClient | None = None
        notify_started = False

        def handle_notify(_: int, data: bytearray) -> None:
            notify_buffer.extend(data)
            while b"\n" in notify_buffer:
                raw_line, _, remainder = notify_buffer.partition(b"\n")
                notify_buffer[:] = remainder
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    line_queue.put_nowait(line)

        lines: list[str] = []
        uploaded_samples: list[Sample] = []
        output_path: Path | None = None

        try:
            self.device_progress(action, 10, f"扫描 {device}")
            client = await self._connect_device_for_operation(device, scan_timeout, connect_retries)
            self.device_progress(action, 45, "已连接设备")
            await client.start_notify(TX_UUID, handle_notify)
            notify_started = True
            await asyncio.sleep(0.2)
            self.device_progress(action, 55, "已打开通知通道")

            if action == "status":
                self.device_progress(action, 70, "读取状态和缓存信息")
                await write_command(client, "STATUS")
                await asyncio.sleep(0.1)
                await write_command(client, "CACHE")
                self.device_progress(action, 85, "等待设备返回")
                lines = await self._collect_device_lines(line_queue, total_timeout_s=3.0)
            elif action == "collect":
                self.device_progress(action, 70, "切换到采集模式")
                await write_command(client, "MODE COLLECT")
                await asyncio.sleep(0.3)
                await write_command(client, "STATUS")
                await asyncio.sleep(0.1)
                await write_command(client, "CACHE")
                self.device_progress(action, 85, "确认采集模式")
                lines = await self._collect_device_lines(line_queue, total_timeout_s=3.5)
            elif action == "daily":
                self.device_progress(action, 70, "切换到日常工作模式")
                await write_command(client, "MODE DAILY")
                await asyncio.sleep(0.3)
                await write_command(client, "STATUS")
                await asyncio.sleep(0.1)
                await write_command(client, "CACHE")
                self.device_progress(action, 85, "确认日常模式")
                lines = await self._collect_device_lines(line_queue, total_timeout_s=3.5)
            elif action == "clear":
                self.device_progress(action, 70, "清空设备缓存")
                await write_command(client, "CLEAR")
                await asyncio.sleep(0.2)
                await write_command(client, "CACHE")
                self.device_progress(action, 85, "确认缓存状态")
                lines = await self._collect_device_lines(line_queue, total_timeout_s=3.0)
            elif action == "ota":
                self.device_progress(action, 70, "发送 DFU 命令")
                await write_command(client, "DFU")
                self.device_progress(action, 82, "等待设备确认并重启")
                lines = await self._collect_device_lines(
                    line_queue,
                    total_timeout_s=4.0,
                    quiet_timeout_s=0.7,
                )
                self.device_progress(action, 95, "设备即将进入 OTA/DFU 模式")
            elif action == "upload":
                self.device_progress(action, 70, "请求上传缓存")
                await write_command(client, "UPLOAD")
                self.device_progress(action, 80, "接收缓存数据")
                lines = await self._collect_device_lines(
                    line_queue,
                    total_timeout_s=60.0,
                    quiet_timeout_s=1.5,
                    until=lambda line: line == "UPLOAD END",
                )
                self.device_progress(action, 92, "保存上传数据")
                uploaded_samples = [sample for line in lines if (sample := parse_sample(line)) is not None]
                output_path = self._write_uploaded_cache_csv(
                    samples=uploaded_samples,
                    cat_id=cat_id,
                    device=device,
                    out_dir=out_dir,
                )
        finally:
            if client is not None and client.is_connected:
                if notify_started:
                    try:
                        await client.stop_notify(TX_UUID)
                    except Exception as exc:
                        self.broadcast("log", {"message": f"Could not stop device notifications: {exc}"})
                try:
                    await client.disconnect()
                except Exception as exc:
                    self.broadcast("log", {"message": f"Could not disconnect device cleanly: {exc}"})

        finished = datetime.now().isoformat(timespec="milliseconds")
        payload = {
            "action": action,
            "action_zh": self._device_action_name(action),
            "ok": True,
            "started_at_iso": started,
            "finished_at_iso": finished,
            "summary": self._summarize_device_operation(action, lines, uploaded_samples, output_path),
            "lines": lines[-120:],
            "samples": len(uploaded_samples),
            "output_path": str(output_path) if output_path is not None else "",
        }
        if action == "ota":
            self.device_progress(action, 100, "已进入 OTA/DFU，等待用手机 App 刷写固件", state="waiting")
        else:
            self.device_progress(action, 100, "设备操作完成", state="done")
        return payload

    async def _run_flash_operation(
        self,
        *,
        action: str,
        device: str,
        scan_timeout: float,
        connect_retries: int,
        started: str,
    ) -> dict[str, Any]:
        firmware_path = default_firmware_zip_path()
        if not firmware_path.is_file():
            raise RuntimeError(f"firmware.zip not found: {firmware_path}")

        lines: list[str] = []
        self.device_progress(action, 8, "检查固件包")

        dfu_ready = await self._dfu_device_available(timeout=5.0)
        if dfu_ready:
            lines.append("DFU device already advertising")
            self.device_progress(action, 20, "已发现 DFU bootloader")
        else:
            self.device_progress(action, 12, "未发现 DFU，先让设备进入 OTA")
            try:
                ota_lines = await self._enter_ota_mode_for_flash(
                    action=action,
                    device=device,
                    scan_timeout=scan_timeout,
                    connect_retries=connect_retries,
                )
                lines.extend(ota_lines)
                self.device_progress(action, 22, "等待 bootloader 重新广播")
                await asyncio.sleep(2.0)
            except Exception as exc:
                self.device_progress(action, 18, "普通固件连接失败，检查是否已在 DFU")
                dfu_ready = await self._dfu_device_available(timeout=12.0)
                if not dfu_ready:
                    raise
                lines.append(f"CatSense device connection failed, but DFU bootloader is advertising: {exc}")
                self.device_progress(action, 22, "已发现 DFU bootloader")

        def on_dfu_progress(percent: int, message: str, state: str) -> None:
            self.device_progress(action, percent, message, state=state)

        profile = {
            "flash_safe": "safe",
            "flash_fast": "fast",
        }.get(action, "balanced")

        await asyncio.to_thread(
            self._run_ble_dfu_flash,
            firmware_path,
            scan_timeout,
            profile,
            on_dfu_progress,
        )

        self.device_progress(action, 98, "确认设备重启并重新广播")
        rebooted = await self._wait_for_app_reboot(device=device, timeout=18.0)
        if not rebooted:
            still_dfu = await self._dfu_device_available(timeout=3.0)
            if still_dfu:
                raise RuntimeError(
                    "固件数据已发送，但设备仍停留在 DFU bootloader。请按一下 reset；"
                    "如果反复出现，请使用手机 App 或 USB bootloader 刷写。"
                )
            lines.append("Firmware sent, but CatSense advertising was not confirmed after reset.")

        finished = datetime.now().isoformat(timespec="milliseconds")
        payload = {
            "action": action,
            "action_zh": self._device_action_name(action),
            "ok": True,
            "started_at_iso": started,
            "finished_at_iso": finished,
            "summary": [
                "BLE OTA 刷写完成。",
                "设备已重新广播 CatSense 固件。",
                f"固件包：{firmware_path}",
            ],
            "lines": lines[-120:],
            "samples": 0,
            "output_path": str(firmware_path),
        }
        self.device_progress(action, 100, "刷写完成，已确认设备重新广播", state="done")
        return payload

    async def _run_dfu_reboot_operation(
        self,
        *,
        action: str,
        device: str,
        scan_timeout: float,
        started: str,
    ) -> dict[str, Any]:
        def on_dfu_progress(percent: int, message: str, state: str) -> None:
            self.device_progress(action, percent, message, state=state)

        await asyncio.to_thread(
            self._run_dfu_system_reset,
            scan_timeout,
            on_dfu_progress,
        )

        self.device_progress(action, 92, "确认设备重新广播")
        rebooted = await self._wait_for_app_reboot(device=device, timeout=18.0)
        if not rebooted:
            still_dfu = await self._dfu_device_available(timeout=3.0)
            if still_dfu:
                raise RuntimeError("已发送 DFU 重启命令，但设备仍停留在 bootloader。请按一下 reset。")
            raise RuntimeError("已发送 DFU 重启命令，但没有确认 CatSense-V0 重新广播。")

        finished = datetime.now().isoformat(timespec="milliseconds")
        payload = {
            "action": action,
            "action_zh": self._device_action_name(action),
            "ok": True,
            "started_at_iso": started,
            "finished_at_iso": finished,
            "summary": [
                "已发送 DFU 重启命令。",
                "设备已重新广播 CatSense 固件。",
            ],
            "lines": [],
            "samples": 0,
            "output_path": "",
        }
        self.device_progress(action, 100, "DFU 已重启回 CatSense", state="done")
        return payload

    async def _dfu_device_available(self, *, timeout: float) -> bool:
        try:
            from ble_dfu import find_dfu_device
        except Exception as exc:
            raise RuntimeError(f"BLE DFU support is unavailable: {exc}") from exc

        device = await find_dfu_device(timeout)
        return device is not None

    async def _wait_for_app_reboot(self, *, device: str, timeout: float) -> bool:
        try:
            found = await find_device(device, timeout)
        except Exception:
            return False
        return found is not None

    def _run_ble_dfu_flash(
        self,
        firmware_path: Path,
        scan_timeout: float,
        profile: str,
        progress_callback: Any,
    ) -> None:
        try:
            from ble_dfu import run_ble_dfu
        except Exception as exc:
            raise RuntimeError(f"BLE DFU support is unavailable: {exc}") from exc

        run_ble_dfu(
            firmware_path,
            scan_timeout=max(45.0, scan_timeout),
            profile=profile,
            progress_callback=progress_callback,
        )

    def _run_dfu_system_reset(
        self,
        scan_timeout: float,
        progress_callback: Any,
    ) -> None:
        try:
            from ble_dfu import run_dfu_system_reset
        except Exception as exc:
            raise RuntimeError(f"BLE DFU support is unavailable: {exc}") from exc

        run_dfu_system_reset(
            scan_timeout=max(20.0, scan_timeout),
            progress_callback=progress_callback,
        )

    async def _enter_ota_mode_for_flash(
        self,
        *,
        action: str,
        device: str,
        scan_timeout: float,
        connect_retries: int,
    ) -> list[str]:
        line_queue: asyncio.Queue[str] = asyncio.Queue()
        notify_buffer = bytearray()
        client: BleakClient | None = None
        notify_started = False

        def handle_notify(_: int, data: bytearray) -> None:
            notify_buffer.extend(data)
            while b"\n" in notify_buffer:
                raw_line, _, remainder = notify_buffer.partition(b"\n")
                notify_buffer[:] = remainder
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    line_queue.put_nowait(line)

        try:
            client = await self._connect_device_for_operation(device, scan_timeout, connect_retries)
            await client.start_notify(TX_UUID, handle_notify)
            notify_started = True
            await asyncio.sleep(0.2)
            self.device_progress(action, 16, "发送 DFU 命令")
            await write_command(client, "DFU")
            self.device_progress(action, 18, "等待设备断开并进入 bootloader")
            return await self._collect_device_lines(
                line_queue,
                total_timeout_s=4.0,
                quiet_timeout_s=0.7,
            )
        finally:
            if client is not None and client.is_connected:
                if notify_started:
                    try:
                        await client.stop_notify(TX_UUID)
                    except Exception:
                        pass
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _connect_device_for_operation(self, device_name: str, scan_timeout: float, attempts: int) -> BleakClient:
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            client: BleakClient | None = None
            try:
                self.broadcast("log", {"message": f"Scanning for {device_name} ({attempt}/{attempts})..."})
                device = await find_device(device_name, scan_timeout)
                self.broadcast("log", {"message": f"Connecting to {device_name} ({attempt}/{attempts})..."})
                client = BleakClient(device)
                await client.connect()
                if not client.is_connected:
                    raise RuntimeError(f"Failed to connect to {device_name}.")
                self.broadcast("log", {"message": f"Connected to {device_name}."})
                return client
            except Exception as exc:
                last_error = exc
                if client is not None:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
                if attempt < attempts:
                    self.broadcast("log", {"message": f"Device connection failed: {exc}. Retrying..."})
                    await asyncio.sleep(2.0)

        raise RuntimeError(f"Could not connect to {device_name} after {attempts} attempt(s): {last_error}")

    async def _collect_device_lines(
        self,
        line_queue: asyncio.Queue[str],
        *,
        total_timeout_s: float,
        quiet_timeout_s: float = 0.45,
        until: Any | None = None,
    ) -> list[str]:
        lines: list[str] = []
        deadline = time.monotonic() + total_timeout_s

        while time.monotonic() < deadline:
            wait_s = max(0.05, min(quiet_timeout_s, deadline - time.monotonic()))
            try:
                line = await asyncio.wait_for(line_queue.get(), timeout=wait_s)
            except asyncio.TimeoutError:
                if lines:
                    break
                continue

            lines.append(line)
            if until is not None and until(line):
                break

        return lines

    def _write_uploaded_cache_csv(
        self,
        *,
        samples: list[Sample],
        cat_id: str,
        device: str,
        out_dir: Path,
    ) -> Path | None:
        if not samples:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = out_dir / cat_id / f"daily_upload_{timestamp}.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        upload_time_iso = datetime.now().isoformat(timespec="milliseconds")

        with output_path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADER)
            for index, sample in enumerate(samples):
                writer.writerow(
                    (
                        upload_time_iso,
                        sample.device_ms,
                        sample.seq,
                        sample.ax_mg,
                        sample.ay_mg,
                        sample.az_mg,
                        sample.battery_mv,
                        "",
                        cat_id,
                        device,
                        "cache_upload" if index == 0 else "",
                        upload_time_iso if index == 0 else "",
                        "daily cache upload" if index == 0 else "",
                    )
                )

        return output_path

    def _summarize_device_operation(
        self,
        action: str,
        lines: list[str],
        samples: list[Sample],
        output_path: Path | None,
    ) -> list[str]:
        summary: list[str] = []
        if action == "status":
            summary.append("已读取设备状态。")
        elif action == "collect":
            summary.append("已请求切换到采集模式。")
        elif action == "daily":
            summary.append("已请求切换到日常工作模式。")
        elif action == "clear":
            summary.append("已请求清空设备本地缓存。")
        elif action == "ota":
            info = firmware_info()
            summary.append("已请求设备进入 OTA/DFU 模式。")
            summary.append("设备会断开当前连接，并以 bootloader/DFU 模式重新广播。")
            if info["exists"]:
                summary.append(f"固件包：{info['path']}")
            else:
                summary.append("注意：未找到 firmware.zip，请先编译固件。")
        elif action == "upload":
            summary.append(f"已拉取缓存样本 {len(samples)} 行。")
            if output_path is not None:
                summary.append(f"保存文件：{output_path}")
            else:
                summary.append("没有保存文件：设备缓存为空，或没有收到 CS0 样本行。")
            if lines and lines[-1] != "UPLOAD END":
                summary.append("注意：没有收到 UPLOAD END，上传可能不完整。")

        for line in lines:
            translated = self._translate_device_line(line)
            if translated:
                summary.append(translated)

        return summary

    def _translate_device_line(self, line: str) -> str:
        if line.startswith("STATUS"):
            pairs = self._parse_device_pairs(line)
            mode = pairs.get("mode", "")
            mode_zh = {"collect": "采集模式", "daily": "日常工作模式"}.get(mode, mode or "未知")
            parts = [f"模式 {mode_zh}"]
            if "sampling" in pairs:
                parts.append(f"实时采样 {'开' if pairs['sampling'] == '1' else '关'}")
            if "rate" in pairs:
                parts.append(f"采集采样率 {pairs['rate']}Hz")
            if "daily_rate" in pairs:
                parts.append(f"日常采样率 {pairs['daily_rate']}Hz")
            if "battery_mv" in pairs:
                parts.append(f"电池 {pairs['battery_mv']}mV")
            if "tx_power_dbm" in pairs:
                parts.append(f"发射功率 {pairs['tx_power_dbm']}dBm")
            if "cache_rows" in pairs:
                parts.append(f"缓存行 {pairs['cache_rows']}")
            if "cache_bytes" in pairs:
                parts.append(f"缓存 {self._format_bytes(pairs['cache_bytes'])}")
            if "cache_dropped" in pairs:
                parts.append(f"丢弃 {pairs['cache_dropped']}")
            if "fs" in pairs:
                parts.append(f"文件系统 {'正常' if pairs['fs'] == '1' else '不可用'}")
            return "设备状态：" + "，".join(parts)

        if line.startswith("CACHE"):
            pairs = self._parse_device_pairs(line)
            parts: list[str] = []
            if "rows" in pairs:
                parts.append(f"缓存行 {pairs['rows']}")
            if "bytes" in pairs:
                parts.append(f"已用 {self._format_bytes(pairs['bytes'])}")
            if "max_bytes" in pairs:
                parts.append(f"上限 {self._format_bytes(pairs['max_bytes'])}")
            if "buffered" in pairs:
                parts.append(f"待刷写 {self._format_bytes(pairs['buffered'])}")
            if "dropped" in pairs:
                parts.append(f"丢弃 {pairs['dropped']}")
            return "缓存状态：" + "，".join(parts)

        if line.startswith("UPLOAD BEGIN"):
            pairs = self._parse_device_pairs(line)
            rows = pairs.get("rows", "0")
            used = self._format_bytes(pairs.get("bytes", "0"))
            return f"开始上传：设备缓存 {rows} 行，{used}。"

        if line == "UPLOAD END":
            return "上传结束。"
        if line == "OK MODE DAILY":
            return "设备确认：日常工作模式。"
        if line == "OK MODE COLLECT":
            return "设备确认：采集模式。"
        if line == "OK CLEAR":
            return "设备确认：缓存已清空。"
        if line == "OK DFU":
            return "设备确认：准备进入 OTA/DFU。"
        if line.startswith("ERR"):
            return f"设备错误：{line}"
        return ""

    def _parse_device_pairs(self, line: str) -> dict[str, str]:
        pairs: dict[str, str] = {}
        for part in line.replace(",", " ").split():
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            pairs[key.strip()] = value.strip()
        return pairs

    def _format_bytes(self, value: str) -> str:
        try:
            size = int(value)
        except ValueError:
            return value
        if size >= 1024:
            return f"{size / 1024:.1f}KB"
        return f"{size}B"

    def _device_action_name(self, action: str) -> str:
        return {
            "status": "读取状态",
            "collect": "采集模式",
            "daily": "日常工作模式",
            "upload": "拉取缓存",
            "clear": "清空缓存",
            "ota": "进入 OTA",
            "flash": "刷写固件",
            "flash_fast": "快速刷写",
            "flash_safe": "慢速刷写",
            "reboot_dfu": "重启 DFU",
        }.get(action, action or "设备操作")

    async def start(self, config: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.running:
                raise RuntimeError("A recording is already running.")
            if self.processing:
                raise RuntimeError("Wait for data processing to finish before recording.")
            if self.device_busy:
                raise RuntimeError("Wait for device operation to finish before recording.")

        cat_id = str(config.get("cat_id") or "cat001").strip()
        device = str(config.get("device") or DEVICE_NAME).strip()
        rate = int(config.get("rate") or 25)
        scan_timeout = float(config.get("scan_timeout") or 30)
        connect_retries = max(1, int(config.get("connect_retries") or 3))
        out_dir = Path(str(config.get("out") or default_output_dir())).expanduser().resolve()
        save_mode = str(config.get("save_mode") or DEFAULT_SAVE_MODE).strip().lower()

        if not cat_id:
            raise RuntimeError("Cat id is required.")
        if rate not in VALID_RATES:
            raise RuntimeError("Rate must be 25 or 50.")
        if save_mode not in VALID_SAVE_MODES:
            raise RuntimeError(f"Save mode must be one of: {', '.join(sorted(VALID_SAVE_MODES))}.")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path: Path | None
        append_csv = False
        if save_mode == "preview":
            output_path = None
        elif save_mode == "daily":
            output_path = out_dir / cat_id / f"manual_{datetime.now().strftime('%Y%m%d')}.csv"
            append_csv = True
        else:
            output_path = out_dir / cat_id / f"manual_{timestamp}.csv"

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)

        with self.lock:
            self.reset_state()
            self.status = "scanning"
            self.running = True
            self.current_label = ""
            self.cat_id = cat_id
            self.rate = rate
            self.device = device
            self.save_mode = save_mode
            self.output_path = str(output_path) if output_path is not None else "仅实时预览，不保存 CSV"
            self.error = ""
            self.warning = ""

        self.pending_markers.clear()
        self.stop_event = asyncio.Event()
        self.task = asyncio.create_task(
            self._run_collection(
                output_path=output_path,
                device=device,
                cat_id=cat_id,
                rate=rate,
                save_mode=save_mode,
                append_csv=append_csv,
                scan_timeout=scan_timeout,
                connect_retries=connect_retries,
            )
        )
        self.broadcast("state", self.snapshot())
        self.broadcast("log", {"message": f"Scanning for {device}... Save mode: {save_mode}"})
        return self.snapshot()

    async def stop(self) -> dict[str, Any]:
        if not self.running:
            return self.snapshot()

        self.update_status("stopping")
        if self.stop_event is not None:
            self.stop_event.set()

        if self.task is not None and not self.task.done():
            try:
                await asyncio.wait_for(self.task, timeout=8)
            except asyncio.TimeoutError:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass

        return self.snapshot()

    async def mark(self, marker: str, note: str) -> dict[str, Any]:
        if not self.running:
            raise RuntimeError("Start a recording before adding markers.")

        marker = (marker or "mark").strip()[:64] or "mark"
        note = (note or "").strip()[:160]
        event = {
            "marker": marker,
            "note": note,
            "marker_time_iso": datetime.now().isoformat(timespec="milliseconds"),
            "sample_index": self.samples,
        }
        self.pending_markers.append(event)

        with self.lock:
            self.markers.append(event)

        self.broadcast("mark", event)
        self.broadcast("state", self.snapshot())
        return event

    async def set_label(self, label: str) -> dict[str, Any]:
        if not self.running:
            raise RuntimeError("Start a recording before setting a label.")

        label = (label or "").strip()[:64]
        event = {
            "marker": f"start:{label}" if label else "end",
            "note": "",
            "marker_time_iso": datetime.now().isoformat(timespec="milliseconds"),
            "sample_index": self.samples,
            "label": label,
            "action": "label_start" if label else "label_end",
        }
        self.pending_markers.append(event)

        with self.lock:
            self.current_label = label
            self.markers.append(event)

        self.broadcast("mark", event)
        self.broadcast("state", self.snapshot())
        return event

    async def _connect_with_retries(self, device_name: str, scan_timeout: float, attempts: int) -> BleakClient:
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            if self.stop_event and self.stop_event.is_set():
                raise asyncio.CancelledError()

            self.update_status("scanning")
            self.broadcast("log", {"message": f"Scanning for {device_name} ({attempt}/{attempts})..."})
            device = await find_device(device_name, scan_timeout)

            self.update_status("connecting")
            self.broadcast("log", {"message": f"Connecting to {device_name} ({attempt}/{attempts})..."})
            client = BleakClient(device)

            try:
                await client.connect()
                if not client.is_connected:
                    raise RuntimeError(f"Failed to connect to {device_name}.")
                return client
            except Exception as exc:
                last_error = exc
                try:
                    if client.is_connected:
                        await client.disconnect()
                except Exception:
                    pass
                if attempt < attempts:
                    self.broadcast("log", {"message": f"Connection failed: {exc}. Retrying..."})
                    await asyncio.sleep(2.0)

        raise RuntimeError(f"Could not connect to {device_name} after {attempts} attempt(s): {last_error}")

    async def _run_collection(
        self,
        *,
        output_path: Path | None,
        device: str,
        cat_id: str,
        rate: int,
        save_mode: str,
        append_csv: bool,
        scan_timeout: float,
        connect_retries: int,
    ) -> None:
        line_queue: asyncio.Queue[str] = asyncio.Queue()
        notify_buffer = bytearray()
        client: BleakClient | None = None
        csv_file = None
        writer: csv._writer | None = None
        notify_started = False

        def handle_notify(_: int, data: bytearray) -> None:
            notify_buffer.extend(data)
            while b"\n" in notify_buffer:
                raw_line, _, remainder = notify_buffer.partition(b"\n")
                notify_buffer[:] = remainder
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    line_queue.put_nowait(line)

        try:
            client = await self._connect_with_retries(device, scan_timeout, connect_retries)
            self.update_status("connected", connected=True)
            self.broadcast("log", {"message": f"Connected to {device}."})

            if output_path is not None:
                needs_header = (
                    not append_csv
                    or not output_path.exists()
                    or output_path.stat().st_size == 0
                )
                csv_file = output_path.open("a" if append_csv else "w", newline="", buffering=1)
                writer = csv.writer(csv_file)
                if needs_header:
                    writer.writerow(CSV_HEADER)

            await client.start_notify(TX_UUID, handle_notify)
            notify_started = True
            await asyncio.sleep(0.2)
            await write_command(client, f"RATE {rate}")
            await asyncio.sleep(0.1)
            await write_command(client, "START")

            started_at_iso = datetime.now().isoformat(timespec="milliseconds")
            with self.lock:
                self.status = "recording"
                self.started_at_iso = started_at_iso
                self.start_monotonic = time.monotonic()
                self.last_sample_monotonic = self.start_monotonic
            self.broadcast("state", self.snapshot())
            if output_path is None:
                self.broadcast("log", {"message": "Preview mode: not saving CSV."})
            elif append_csv:
                self.broadcast("log", {"message": f"Appending to {output_path}."})
            else:
                self.broadcast("log", {"message": f"Recording to {output_path}."})

            while self.stop_event is not None and not self.stop_event.is_set():
                if client is not None and not client.is_connected:
                    raise RuntimeError(f"Disconnected from {device}.")

                last_sample = self.last_sample_monotonic or time.monotonic()
                timeout = max(0.1, min(1.0, 5.0 - (time.monotonic() - last_sample)))

                try:
                    line = await asyncio.wait_for(line_queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    if time.monotonic() - last_sample >= 5.0:
                        with self.lock:
                            self.warning = "No data received in 5 seconds."
                        self.broadcast("warning", {"message": self.warning})
                        self.broadcast("state", self.snapshot())
                    continue

                sample = parse_sample(line)
                if sample is None:
                    if not line.startswith("OK "):
                        self.broadcast("log", {"message": f"Device: {line}"})
                    continue

                markers = []
                while self.pending_markers:
                    markers.append(self.pending_markers.popleft())

                with self.lock:
                    label_for_row = self.current_label

                for item in markers:
                    if "label" in item:
                        label_for_row = item["label"]

                marker = "|".join(item["marker"] for item in markers)
                marker_time_iso = "|".join(item["marker_time_iso"] for item in markers)
                marker_note = " | ".join(item["note"] for item in markers if item.get("note"))
                host_time_iso = datetime.now().isoformat(timespec="milliseconds")

                if writer is not None:
                    writer.writerow(
                        (
                            host_time_iso,
                            sample.device_ms,
                            sample.seq,
                            sample.ax_mg,
                            sample.ay_mg,
                            sample.az_mg,
                            sample.battery_mv,
                            label_for_row,
                            cat_id,
                            device,
                            marker,
                            marker_time_iso,
                            marker_note,
                        )
                    )

                now = time.monotonic()
                with self.lock:
                    self.samples += 1
                    self.last_sample_monotonic = now
                    duration = now - (self.start_monotonic or now)
                    self.observed_rate_hz = self.samples / duration if duration > 0 else 0.0
                    self.battery_mv = sample.battery_mv
                    self.current_label = label_for_row
                    self.warning = ""
                    sample_payload = {
                        "host_time_iso": host_time_iso,
                        "device_ms": sample.device_ms,
                        "seq": sample.seq,
                        "ax_mg": sample.ax_mg,
                        "ay_mg": sample.ay_mg,
                        "az_mg": sample.az_mg,
                        "battery_mv": sample.battery_mv,
                        "label": label_for_row,
                        "marker": marker,
                        "marker_time_iso": marker_time_iso,
                        "marker_note": marker_note,
                    }
                    self.last_sample = sample_payload

                self.broadcast("sample", sample_payload)
                if marker:
                    if writer is not None:
                        self.broadcast("log", {"message": f"Marker saved: {marker}"})
                    else:
                        self.broadcast("log", {"message": f"Marker noted in preview: {marker}"})

                prediction = self.predictor.add_sample(sample)
                if prediction is not None:
                    with self.lock:
                        self.prediction = prediction
                    self.broadcast("prediction", prediction)

                if writer is not None and csv_file is not None and self.samples % rate == 0:
                    csv_file.flush()
                    self.broadcast("state", self.snapshot())
                elif self.samples % rate == 0:
                    self.broadcast("state", self.snapshot())

        except asyncio.CancelledError:
            self.broadcast("log", {"message": "Recording cancelled."})
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
            self.broadcast("error", {"message": str(exc)})
        finally:
            if client is not None and client.is_connected:
                try:
                    await write_command(client, "STOP")
                    await asyncio.sleep(0.1)
                except Exception as exc:
                    self.broadcast("log", {"message": f"Could not send STOP: {exc}"})

                if notify_started:
                    try:
                        await client.stop_notify(TX_UUID)
                    except Exception as exc:
                        self.broadcast("log", {"message": f"Could not stop notifications: {exc}"})

                try:
                    await client.disconnect()
                except Exception as exc:
                    self.broadcast("log", {"message": f"Could not disconnect cleanly: {exc}"})

            if csv_file is not None:
                csv_file.flush()
                csv_file.close()

            with self.lock:
                final_error = self.error
                self.running = False
                self.connected = False
                self.status = "error" if final_error else "idle"

            if self.samples:
                if output_path is None:
                    self.broadcast("log", {"message": f"Previewed {self.samples} samples; no CSV saved."})
                elif save_mode == "daily":
                    self.broadcast("log", {"message": f"Appended {self.samples} samples to {output_path}."})
                else:
                    self.broadcast("log", {"message": f"Saved {self.samples} samples to {output_path}."})
            self.broadcast("state", self.snapshot())


class CatSenseRequestHandler(BaseHTTPRequestHandler):
    session: CatSenseWebSession
    static_dir: Path

    server_version = "CatSenseWeb/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/events":
            self.handle_events()
            return
        if parsed.path == "/api/state":
            self.send_json(HTTPStatus.OK, self.session.snapshot())
            return
        if parsed.path == "/api/firmware":
            self.send_json(HTTPStatus.OK, firmware_info())
            return
        if parsed.path == "/firmware/latest.zip":
            self.serve_firmware_zip()
            return

        path = "/index.html" if parsed.path == "/" else parsed.path
        self.serve_static(path)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json(HTTPStatus.OK, self.session.snapshot(), include_body=False)
            return
        if parsed.path == "/api/firmware":
            self.send_json(HTTPStatus.OK, firmware_info(), include_body=False)
            return
        if parsed.path == "/firmware/latest.zip":
            self.serve_firmware_zip(include_body=False)
            return

        path = "/index.html" if parsed.path == "/" else parsed.path
        self.serve_static(path, include_body=False)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json_body()
            if parsed.path == "/api/start":
                result = self.session.start_threadsafe(payload)
            elif parsed.path == "/api/stop":
                result = self.session.stop_threadsafe()
            elif parsed.path == "/api/label":
                result = self.session.set_label_threadsafe(str(payload.get("label") or ""))
            elif parsed.path == "/api/mark":
                result = self.session.mark_threadsafe(
                    str(payload.get("marker") or "mark"),
                    str(payload.get("note") or ""),
                )
            elif parsed.path == "/api/process":
                result = self.session.process_threadsafe(str(payload.get("action") or ""))
            elif parsed.path == "/api/device":
                result = self.session.device_threadsafe(payload)
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
                return
            self.send_json(HTTPStatus.OK, result)
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, status: HTTPStatus, payload: dict[str, Any], *, include_body: bool = True) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def serve_static(self, request_path: str, *, include_body: bool = True) -> None:
        relative = request_path.lstrip("/")
        if ".." in Path(relative).parts:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return

        target = self.static_dir / relative
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_length = target.stat().st_size
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(target.read_bytes())

    def serve_firmware_zip(self, *, include_body: bool = True) -> None:
        target = default_firmware_zip_path()
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "firmware.zip not found; build firmware first")
            return

        content = target.read_bytes() if include_body else b""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Content-Disposition", 'attachment; filename="catsense-v0-firmware.zip"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(content)

    def handle_events(self) -> None:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        self.session.add_subscriber(subscriber)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            self.write_sse("state", self.session.snapshot())
            while True:
                try:
                    payload = subscriber.get(timeout=15)
                    self.write_sse(payload["event"], payload["data"])
                except queue.Empty:
                    self.write_sse("ping", {"time": datetime.now().isoformat(timespec="seconds")})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.session.remove_subscriber(subscriber)

    def write_sse(self, event: str, payload: dict[str, Any]) -> None:
        body = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the CatSense V0 live web logger.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", type=Path, default=default_model_path())
    parser.add_argument("--no-prediction", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    static_dir = Path(__file__).resolve().parent / "web"

    loop = asyncio.new_event_loop()
    session = CatSenseWebSession(loop, args.model.expanduser().resolve(), not args.no_prediction)
    loop_thread = threading.Thread(target=loop.run_forever, name="catsense-ble-loop", daemon=True)
    loop_thread.start()

    CatSenseRequestHandler.session = session
    CatSenseRequestHandler.static_dir = static_dir

    try:
        server = ThreadingHTTPServer((args.host, args.port), CatSenseRequestHandler)
    except OSError as exc:
        if exc.errno == 48:
            print(
                f"Port {args.port} is already in use. Stop the existing web_logger.py "
                f"or start this one with --port {args.port + 1}.",
                file=sys.stderr,
            )
        raise

    shutdown_requested = threading.Event()

    def shutdown(_: int, __: Any) -> None:
        if shutdown_requested.is_set():
            return
        shutdown_requested.set()
        threading.Thread(target=server.shutdown, name="catsense-http-shutdown", daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print_server_urls(args.host, args.port)
    try:
        server.serve_forever()
    finally:
        try:
            session.stop_threadsafe()
        except Exception:
            pass
        server.server_close()
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
