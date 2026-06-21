#!/usr/bin/env python3
"""BLE CSV logger for CatSense V0."""

from __future__ import annotations

import argparse
import asyncio
import csv
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


DEVICE_NAME = "CatSense-V0"
SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
VALID_RATES = (25, 50)
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
)


@dataclass
class Sample:
    seq: int
    device_ms: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    battery_mv: int


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log CatSense V0 BLE IMU data to CSV.")
    parser.add_argument("--label", required=True, help="Behavior label, for example sleep/eat/groom/active.")
    parser.add_argument("--cat", required=True, dest="cat_id", help="Cat id, for example cat001.")
    parser.add_argument("--rate", required=True, type=int, choices=VALID_RATES, help="Sampling rate in Hz.")
    parser.add_argument("--out", type=Path, default=None, help="Output directory. Default: ../data/raw.")
    parser.add_argument("--device", default=DEVICE_NAME, help=f"BLE device name. Default: {DEVICE_NAME}.")
    parser.add_argument("--scan-timeout", type=float, default=30.0, help="BLE scan timeout in seconds.")
    parser.add_argument("--connect-retries", type=int, default=3, help="BLE connection retry count. Default: 3.")
    return parser.parse_args(list(argv))


def default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "raw"


def build_output_path(args: argparse.Namespace) -> Path:
    base_dir = args.out if args.out is not None else default_output_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir.expanduser().resolve() / args.cat_id / f"{args.label}_{timestamp}.csv"


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


async def find_device(device_name: str, timeout: float) -> BLEDevice:
    print(f"Scanning for {device_name}...")

    def matches(candidate: BLEDevice, advertisement: AdvertisementData) -> bool:
        names = {candidate.name, advertisement.local_name}
        return device_name in names

    device = await BleakScanner.find_device_by_filter(matches, timeout=timeout)
    if device is None:
        raise RuntimeError(f"Could not find BLE device named {device_name!r}.")
    return device


async def write_command(client: BleakClient, command: str) -> None:
    payload = f"{command}\n".encode("ascii")
    await client.write_gatt_char(RX_UUID, payload, response=True)


async def connect_with_retries(args: argparse.Namespace) -> BleakClient:
    last_error: Exception | None = None
    attempts = max(1, args.connect_retries)

    for attempt in range(1, attempts + 1):
        device = await find_device(args.device, args.scan_timeout)
        client = BleakClient(device)
        try:
            print(f"Connecting to {args.device} ({attempt}/{attempts})...")
            await client.connect()
            if not client.is_connected:
                raise RuntimeError(f"Failed to connect to {args.device}.")
            return client
        except Exception as exc:
            last_error = exc
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:
                pass

            if attempt < attempts:
                print(f"Warning: connection attempt failed: {exc}. Retrying...")
                await asyncio.sleep(2.0)

    raise RuntimeError(f"Could not connect to {args.device} after {attempts} attempt(s): {last_error}")


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass


async def run_logger(args: argparse.Namespace) -> None:
    output_path = build_output_path(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)

    line_queue: asyncio.Queue[str] = asyncio.Queue()
    notify_buffer = bytearray()

    def handle_notify(_: int, data: bytearray) -> None:
        notify_buffer.extend(data)
        while b"\n" in notify_buffer:
            raw_line, _, remainder = notify_buffer.partition(b"\n")
            notify_buffer[:] = remainder
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                line_queue.put_nowait(line)

    samples = 0
    start_time = time.monotonic()
    last_sample_time = start_time
    last_stats_time = start_time
    last_warning_time = 0.0
    csv_file = None

    try:
        client = await connect_with_retries(args)
        try:
            print(f"Connected to {args.device}")
            print(f"Label: {args.label}")
            print(f"Cat: {args.cat_id}")
            print(f"Rate: {args.rate}Hz")
            print(f"Saving to: {output_path}")
            print()

            csv_file = output_path.open("w", newline="", buffering=1)
            writer = csv.writer(csv_file)
            writer.writerow(CSV_HEADER)

            notify_started = False
            try:
                await client.start_notify(TX_UUID, handle_notify)
                notify_started = True
                await asyncio.sleep(0.2)
                await write_command(client, f"RATE {args.rate}")
                await asyncio.sleep(0.1)
                await write_command(client, "START")

                while not stop_event.is_set():
                    if not client.is_connected:
                        raise RuntimeError(f"Disconnected from {args.device}.")

                    now = time.monotonic()
                    timeout = max(0.1, min(1.0, 5.0 - (now - last_sample_time)))

                    try:
                        line = await asyncio.wait_for(line_queue.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        now = time.monotonic()
                        if now - last_sample_time >= 5.0 and now - last_warning_time >= 5.0:
                            print("Warning: no data received in 5 seconds")
                            last_warning_time = now
                        continue

                    sample = parse_sample(line)
                    if sample is None:
                        if not line.startswith("OK "):
                            print(f"Device: {line}")
                        continue

                    host_time_iso = datetime.now().isoformat(timespec="milliseconds")
                    writer.writerow(
                        (
                            host_time_iso,
                            sample.device_ms,
                            sample.seq,
                            sample.ax_mg,
                            sample.ay_mg,
                            sample.az_mg,
                            sample.battery_mv,
                            args.label,
                            args.cat_id,
                            args.device,
                        )
                    )

                    samples += 1
                    last_sample_time = time.monotonic()

                    if samples % args.rate == 0:
                        csv_file.flush()

                    if last_sample_time - last_stats_time >= 10.0:
                        duration = last_sample_time - start_time
                        observed_rate = samples / duration if duration > 0 else 0.0
                        print(f"Samples: {samples} | Duration: {duration:.1f}s | Rate: {observed_rate:.1f}Hz")
                        last_stats_time = last_sample_time
            finally:
                if client.is_connected:
                    try:
                        await write_command(client, "STOP")
                        await asyncio.sleep(0.1)
                    except Exception as exc:
                        print(f"Warning: could not send STOP: {exc}", file=sys.stderr)

                    if notify_started:
                        try:
                            await client.stop_notify(TX_UUID)
                        except Exception as exc:
                            print(f"Warning: could not stop notifications: {exc}", file=sys.stderr)
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception as exc:
                    print(f"Warning: could not disconnect cleanly: {exc}", file=sys.stderr)
    finally:
        if csv_file is not None:
            csv_file.flush()
            csv_file.close()
            print(f"Saved {samples} samples to {output_path}")


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(run_logger(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
