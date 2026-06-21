# CatSense V0 BLE Protocol

CatSense V0 uses a simple Nordic UART Service style BLE protocol.

## Device

| Field | Value |
| --- | --- |
| BLE device name | `CatSense-V0` |
| Service UUID | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| TX Notify UUID | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |
| RX Write UUID | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |

TX is used by the firmware to notify the host. RX is used by the host to write ASCII commands.

## Control Commands

Commands are ASCII strings. A trailing newline is accepted but not required.

| Command | Meaning |
| --- | --- |
| `START` | Start IMU sampling and BLE notifications |
| `STOP` | Stop IMU sampling |
| `RATE 25` | Set sampling rate to 25 Hz |
| `RATE 50` | Set sampling rate to 50 Hz |
| `PING` | Return `PONG` |
| `STATUS` | Return current sampling state, rate, sequence number, battery voltage, and BLE TX power |
| `MODE` / `MODE?` | Return current mode and cache status |
| `MODE COLLECT` | Switch to realtime collection mode and persist it |
| `MODE DAILY` | Switch to daily low-power cached mode and persist it |
| `CACHE` / `CACHE?` | Return local cache bytes, rows, and dropped-row count |
| `UPLOAD` | Stream cached `CS0,...` rows over Notify |
| `CLEAR` / `CACHE CLEAR` | Clear local cache |
| `FORMAT` / `CACHE FORMAT` | Format the internal LittleFS cache area |
| `DFU` / `OTA` | Reboot into the BLE OTA/DFU bootloader for `firmware.zip` updates |

The firmware may send short status lines such as `OK START`, `OK STOP`, `OK RATE 25`, `PONG`, `STATUS,mode=collect,...`, `CACHE,...`, `UPLOAD BEGIN ...`, or `UPLOAD END`.

Host software should treat lines beginning with `CS0,` as sample data and ignore or log all other lines as device status.

## Modes

Collection mode is for realtime web logging and manual labels. The host connects, sends `RATE 25` and `START`, then receives live `CS0,...` rows until `STOP`.

Daily mode is a low-power cache proof of concept. The firmware samples a 2-second, 25 Hz burst every 60 seconds, writes rows to `/daily.csv` on internal LittleFS, and opens a 30-second BLE upload window every 5 minutes. A host can connect, send `UPLOAD`, save the streamed `CS0,...` rows, then send `CLEAR`.

The current internal flash cache is capped at about `20 KB`; it is enough to validate the workflow but not enough for all-day raw IMU storage. Real all-day caching will need external SPI/QSPI flash or feature-level edge caching.

## OTA / DFU

The firmware registers the Adafruit Bluefruit `BLEDfu` service and accepts a UART command to enter the OTA bootloader:

```text
DFU
```

After returning `OK DFU`, the device reboots and disconnects. Use `nRF Connect` or `Adafruit Bluefruit Connect` to connect to the DFU device and flash:

```text
firmware/xiao_nrf52840_sense/.pio/build/seeed_xiao_nrf52840_sense/firmware.zip
```

The web dashboard can flash firmware directly through the Python backend. Use the normal flash action first; if desktop BLE packet delivery is unstable, keep the device in DFU mode and use the slow retry action. The dashboard can also request DFU mode and serve the latest firmware zip for native mobile DFU apps as a fallback.

## Sample Format

Each BLE Notify contains one ASCII CSV line:

```csv
CS0,seq,device_ms,ax_mg,ay_mg,az_mg,battery_mv
```

Example:

```csv
CS0,1234,567890,12,-45,1010,3970
```

| Field | Meaning |
| --- | --- |
| `CS0` | Fixed CatSense V0 protocol header |
| `seq` | Monotonic unsigned sample sequence |
| `device_ms` | Device uptime from `millis()` |
| `ax_mg` | X-axis acceleration in mg |
| `ay_mg` | Y-axis acceleration in mg |
| `az_mg` | Z-axis acceleration in mg |
| `battery_mv` | Battery voltage in mV, or `-1` when unavailable |

On XIAO nRF52840 Sense, firmware reads `PIN_VBAT` through the board's 1/2 battery divider. The value is cached and refreshed every 5 seconds during sampling.

## CSV Logger Output

The command-line Python gateway saves samples with host metadata:

```csv
host_time_iso,device_ms,seq,ax_mg,ay_mg,az_mg,battery_mv,label,cat_id,device_id
```

Example:

```csv
2026-06-20T15:30:00.123,567890,1234,12,-45,1010,3970,eat,cat001,CatSense-V0
```

The web logger adds manual label transition metadata:

```csv
host_time_iso,device_ms,seq,ax_mg,ay_mg,az_mg,battery_mv,label,cat_id,device_id,marker,marker_time_iso,marker_note
```

The `label` column is the active manual behavior label at that sample. Blank labels mean no behavior label was active.
