"""BLE DFU transport for Adafruit/Nordic legacy DFU packages."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


NRFUTIL_SITE_PACKAGES = (
    Path.home()
    / ".platformio"
    / "packages"
    / "tool-adafruit-nrfutil"
    / "site-packages"
)
if NRFUTIL_SITE_PACKAGES.is_dir() and str(NRFUTIL_SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(NRFUTIL_SITE_PACKAGES))

from nordicsemi.dfu.dfu import Dfu  # noqa: E402
from nordicsemi.dfu.dfu_transport import DfuEvent  # noqa: E402
import nordicsemi.dfu.dfu_transport_ble as dfu_transport_ble  # noqa: E402
from nordicsemi.dfu.dfu_transport_ble import (  # noqa: E402
    DfuErrorCodeBle,
    DfuOpcodesBle,
    DfuTransportBle,
)


DFU_SERVICE_UUID = "00001530-1212-efde-1523-785feabcd123"
DFU_CONTROL_UUID = "00001531-1212-efde-1523-785feabcd123"
DFU_PACKET_UUID = "00001532-1212-efde-1523-785feabcd123"
DFU_PROFILES = {
    "safe": {"prn": 1, "delay_s": 0.025, "label": "慢速可靠"},
    "balanced": {"prn": 2, "delay_s": 0.006, "label": "均衡"},
    "fast": {"prn": 10, "delay_s": 0.0, "label": "快速"},
}
DEFAULT_DFU_PROFILE = "balanced"
DFU_CONNECT_ATTEMPTS = 3
DFU_ACTIVATE_DISCONNECT_GRACE_S = 1.0
DFU_REBOOT_OBSERVE_S = 2.0

# The default legacy DFU setting acknowledges every 10 packets. That is fast,
# but macOS/CoreBluetooth can queue write-without-response packets too
# aggressively for the XIAO bootloader. Use a balanced packet receipt interval.
dfu_transport_ble.NUM_OF_PACKETS_BETWEEN_NOTIF = DFU_PROFILES[DEFAULT_DFU_PROFILE]["prn"]


ProgressCallback = Callable[[int, str, str], None]


def normalize_bytes(data: Any) -> bytes:
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        return data.encode("latin1")
    if isinstance(data, int):
        return bytes([data])
    return bytes(data)


def is_dfu_advertisement(device: BLEDevice, advertisement: AdvertisementData) -> bool:
    names = {
        str(device.name or ""),
        str(advertisement.local_name or ""),
    }
    service_uuids = {uuid.lower() for uuid in (advertisement.service_uuids or [])}
    if DFU_SERVICE_UUID in service_uuids:
        return True
    return any(name in {"DfuTarg", "DFU", "DFU OTA"} or "dfu" in name.lower() for name in names if name)


async def find_dfu_device(timeout: float) -> BLEDevice | None:
    return await BleakScanner.find_device_by_filter(is_dfu_advertisement, timeout=timeout)


class BleakDfuTransport(DfuTransportBle):
    """Synchronous legacy BLE DFU transport implemented on top of bleak."""

    def __init__(
        self,
        *,
        scan_timeout: float,
        profile: str = DEFAULT_DFU_PROFILE,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        super().__init__()
        self.scan_timeout = scan_timeout
        self.profile = DFU_PROFILES.get(profile, DFU_PROFILES[DEFAULT_DFU_PROFILE])
        self.progress_callback = progress_callback
        self.client: BleakClient | None = None
        self.opened = False
        self.last_error = DfuErrorCodeBle.SUCCESS
        self.received_response = threading.Event()
        self.state_lock = threading.Lock()
        self.waiting_for_notification = False
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.loop.run_forever, name="catsense-dfu-ble", daemon=True)
        self.loop_thread.start()

    def open(self) -> None:
        super().open()
        self._run(self._open_async())

    def close(self) -> None:
        self._run(self._close_async())

    def shutdown(self) -> None:
        try:
            self.close()
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop_thread.join(timeout=2)

    def is_open(self) -> bool:
        return self.opened

    def send_packet_data(self, data: Any) -> None:
        self._run(self._write_packet(normalize_bytes(data)))

    def send_control_data(self, opcode: int, data: Any = b"") -> None:
        payload = bytes([opcode]) + normalize_bytes(data)
        self._run(self._write_control(payload))

    def get_received_response(self) -> bool:
        return self.received_response.is_set()

    def clear_received_response(self) -> None:
        self.received_response.clear()
        with self.state_lock:
            self.last_error = DfuErrorCodeBle.SUCCESS

    def is_waiting_for_notification(self) -> bool:
        with self.state_lock:
            return self.waiting_for_notification

    def set_waiting_for_notification(self) -> None:
        with self.state_lock:
            self.waiting_for_notification = True

    def get_last_error(self) -> int:
        with self.state_lock:
            return self.last_error

    def get_activate_wait_time(self) -> float:
        return 2.0

    def send_activate_firmware(self) -> None:
        self._run(self._activate_and_wait_for_reset())

    async def _open_async(self) -> None:
        if self.client is not None and self.client.is_connected:
            self.opened = True
            return

        last_error: Exception | None = None
        for attempt in range(1, DFU_CONNECT_ATTEMPTS + 1):
            try:
                self._progress(28, f"扫描 DFU 设备（{attempt}/{DFU_CONNECT_ATTEMPTS}）")
                device = await find_dfu_device(self.scan_timeout)
                if device is None:
                    raise RuntimeError("Could not find BLE DFU device.")

                self._progress(35, f"连接 DFU 设备（{attempt}/{DFU_CONNECT_ATTEMPTS}）")
                self.client = BleakClient(device)
                await self.client.connect()
                if not self.client.is_connected:
                    raise RuntimeError("Failed to connect to BLE DFU device.")

                await asyncio.sleep(0.4)
                await self.client.start_notify(DFU_CONTROL_UUID, self._handle_notify)
                self.opened = True
                self._progress(40, "DFU 通道已连接")
                return
            except Exception as exc:
                last_error = exc
                await self._close_async()
                if attempt < DFU_CONNECT_ATTEMPTS:
                    self._progress(34, f"DFU 连接失败，准备重试：{exc}")
                    await asyncio.sleep(1.5)

        raise RuntimeError(
            f"Could not connect to BLE DFU device after {DFU_CONNECT_ATTEMPTS} attempts: {last_error}"
        )

    async def _close_async(self) -> None:
        client = self.client
        self.opened = False
        if client is None:
            return

        if client.is_connected:
            try:
                await client.stop_notify(DFU_CONTROL_UUID)
            except Exception:
                pass
            try:
                await client.disconnect()
            except Exception:
                pass
        self.client = None

    async def _disconnect_async(self) -> None:
        client = self.client
        self.opened = False
        self.client = None
        if client is None or not client.is_connected:
            return
        try:
            await client.disconnect()
        except Exception:
            pass

    async def _write_control(self, payload: bytes) -> None:
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("DFU control channel is not connected.")
        await self.client.write_gatt_char(DFU_CONTROL_UUID, payload, response=True)
        await asyncio.sleep(0.02)

    async def _write_packet(self, payload: bytes) -> None:
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("DFU packet channel is not connected.")
        await self.client.write_gatt_char(DFU_PACKET_UUID, payload, response=False)
        if self.profile["delay_s"] > 0:
            await asyncio.sleep(float(self.profile["delay_s"]))

    async def _activate_and_wait_for_reset(self) -> None:
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("DFU control channel is not connected.")

        self._progress(94, "发送固件激活和重启命令")
        try:
            await self.client.write_gatt_char(
                DFU_CONTROL_UUID,
                bytes([DfuOpcodesBle.ACTIVATE_FIRMWARE_AND_RESET]),
                response=True,
            )
        except Exception:
            if self.client is None or not self.client.is_connected:
                self._progress(97, "bootloader 已断开，等待设备重启")
                return
            raise

        if await self._wait_for_disconnect(DFU_ACTIVATE_DISCONNECT_GRACE_S):
            self._progress(97, "bootloader 已断开，等待设备重启")
            return

        self._progress(96, "激活命令已发送，断开 DFU 连接触发重启")
        await self._disconnect_async()
        await asyncio.sleep(DFU_REBOOT_OBSERVE_S)

    async def _wait_for_disconnect(self, timeout_s: float) -> bool:
        deadline = self.loop.time() + timeout_s
        while self.loop.time() < deadline:
            if self.client is None or not self.client.is_connected:
                return True
            await asyncio.sleep(0.25)
        return self.client is None or not self.client.is_connected

    def _handle_notify(self, _: Any, data: bytearray) -> None:
        payload = bytes(data)
        if not payload:
            return

        opcode = payload[0]
        if opcode == DfuOpcodesBle.RESPONSE and len(payload) >= 3:
            with self.state_lock:
                self.last_error = payload[2]
                self.waiting_for_notification = False
            self.received_response.set()
            return

        if opcode == DfuOpcodesBle.PKT_RCPT_NOTIF:
            with self.state_lock:
                self.waiting_for_notification = False

    def _run(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=max(30.0, self.scan_timeout + 20.0))

    def _progress(self, percent: int, message: str, state: str = "running") -> None:
        if self.progress_callback is not None:
            self.progress_callback(percent, message, state)


def run_ble_dfu(
    firmware_zip: Path,
    *,
    scan_timeout: float,
    profile: str = DEFAULT_DFU_PROFILE,
    progress_callback: ProgressCallback | None = None,
) -> None:
    active_profile = DFU_PROFILES.get(profile, DFU_PROFILES[DEFAULT_DFU_PROFILE])
    dfu_transport_ble.NUM_OF_PACKETS_BETWEEN_NOTIF = int(active_profile["prn"])
    transport = BleakDfuTransport(
        scan_timeout=scan_timeout,
        profile=profile,
        progress_callback=progress_callback,
    )

    def on_progress(progress: int = 0, done: bool = False, log_message: str = "") -> None:
        del done
        message = log_message or "刷写固件"
        if "Uploading firmware" in message:
            mapped = 42 + int(round((float(progress) / 100.0) * 50))
            state = "running"
        else:
            mapped = 40
            state = "running"
        if progress_callback is not None:
            progress_callback(mapped, message, state)

    transport.register_events_callback(DfuEvent.PROGRESS_EVENT, on_progress)

    try:
        if progress_callback is not None:
            progress_callback(
                25,
                f"准备连接 DFU bootloader（{active_profile['label']}模式：每 {active_profile['prn']} 包确认）",
                "running",
            )
        dfu = Dfu(str(firmware_zip), dfu_transport=transport)
        dfu.dfu_send_images()
        if progress_callback is not None:
            progress_callback(98, "固件已发送，等待设备重启", "running")
    finally:
        transport.shutdown()


async def _reset_dfu_device_async(
    *,
    scan_timeout: float,
    progress_callback: ProgressCallback | None = None,
) -> None:
    def progress(percent: int, message: str, state: str = "running") -> None:
        if progress_callback is not None:
            progress_callback(percent, message, state)

    progress(20, "扫描 DFU bootloader")
    device = await find_dfu_device(scan_timeout)
    if device is None:
        raise RuntimeError("Could not find BLE DFU device.")

    progress(45, "连接 DFU bootloader")
    client = BleakClient(device)
    try:
        await client.connect()
        if not client.is_connected:
            raise RuntimeError("Failed to connect to BLE DFU device.")

        await asyncio.sleep(0.4)
        progress(65, "发送系统重启命令")
        try:
            await client.write_gatt_char(
                DFU_CONTROL_UUID,
                bytes([DfuOpcodesBle.SYSTEM_RESET]),
                response=True,
            )
        except Exception:
            if not client.is_connected:
                progress(90, "bootloader 已断开，等待应用启动")
                return
            raise

        await asyncio.sleep(0.5)
        if client.is_connected:
            progress(82, "断开 DFU 连接")
            await client.disconnect()
        progress(90, "已发送重启命令，等待应用启动")
    finally:
        if client.is_connected:
            try:
                await client.disconnect()
            except Exception:
                pass


def run_dfu_system_reset(
    *,
    scan_timeout: float,
    progress_callback: ProgressCallback | None = None,
) -> None:
    asyncio.run(
        _reset_dfu_device_async(
            scan_timeout=scan_timeout,
            progress_callback=progress_callback,
        )
    )
