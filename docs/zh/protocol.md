# BLE 协议

CatSense V0 使用简单的 Nordic UART Service 风格 BLE 文本协议。

## 设备信息

| 字段 | 值 |
| --- | --- |
| BLE 设备名 | `CatSense-V0` |
| Service UUID | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| TX Notify UUID | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |
| RX Write UUID | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |

TX 是固件发给主机的 Notify。RX 是主机写命令给固件。

## 控制命令

命令是 ASCII 字符串，末尾可以带换行。

| 命令 | 含义 |
| --- | --- |
| `START` | 开始 IMU 采样和 BLE 通知 |
| `STOP` | 停止 IMU 采样 |
| `RATE 25` | 设置采样率为 25 Hz |
| `RATE 50` | 设置采样率为 50 Hz |
| `PING` | 返回 `PONG` |
| `STATUS` | 返回当前采样状态、采样率、序号、电池和发射功率 |
| `MODE` / `MODE?` | 返回当前模式和缓存状态 |
| `MODE COLLECT` | 切到采集模式并保存；持续 BLE 广播，等待网页/网关实时采集 |
| `MODE DAILY` | 切到日常工作模式并保存；低频 burst 本地缓存，定时打开 BLE 上传窗口 |
| `CACHE` / `CACHE?` | 返回本地缓存字节数、行数和丢弃数 |
| `UPLOAD` | 通过 Notify 上传本地缓存，缓存内容仍是 `CS0,...` 样本行 |
| `CLEAR` / `CACHE CLEAR` | 清空本地缓存 |
| `FORMAT` / `CACHE FORMAT` | 格式化内部 LittleFS 缓存区 |
| `DFU` / `OTA` | 进入 BLE OTA/DFU bootloader，准备刷入 `firmware.zip` |

状态行示例：

```text
OK START
OK STOP
OK RATE 25
PONG
STATUS,mode=collect,sampling=1,rate=25,daily_rate=25,seq=123,battery_mv=3970,tx_power_dbm=8,cache_bytes=0,cache_rows=0,cache_dropped=0,fs=1
CACHE,bytes=2048,rows=50,buffered=0,dropped=0,max_bytes=20480
UPLOAD BEGIN bytes=2048 rows=50
UPLOAD END
OK DFU
```

主机应该把 `CS0,` 开头的行当作样本数据，其他行当作状态日志。

## 工作模式

### 采集模式

采集模式用于网页实时采集和打标签。BLE 持续广播，主机连接后发送：

```text
RATE 25
START
```

固件按 `25 Hz` 或 `50 Hz` 实时发送 `CS0,...` 样本。`STOP` 停止实时采样。

### 日常工作模式

日常工作模式用于低功耗验证。固件会：

- 每 60 秒采一个 2 秒 burst。
- burst 内部按 25 Hz 采样，共 50 行。
- 样本先进入 RAM 缓冲，再写入内部 LittleFS 文件 `/daily.csv`。
- 每 5 分钟打开 30 秒 BLE 上传窗口。
- 主机连接后发送 `UPLOAD` 拉取缓存，确认保存后发送 `CLEAR` 清空缓存。

当前缓存区使用 nRF52840 内部 flash 的 LittleFS，限制为约 `20 KB` 数据，适合验证机制，不适合长时间完整原始数据记录。后续如果要真正全天缓存，需要外部 SPI/QSPI Flash 或更高层的边缘特征缓存。

## OTA / DFU

固件注册了 Adafruit Bluefruit `BLEDfu` 服务，并支持通过 UART 命令进入 OTA bootloader：

```text
DFU
```

设备返回 `OK DFU` 后会重启并断开当前连接。随后使用 `nRF Connect` 或 `Adafruit Bluefruit Connect` 连接 DFU 设备，刷入 PlatformIO 生成的：

```text
firmware/xiao_nrf52840_sense/.pio/build/seeed_xiao_nrf52840_sense/firmware.zip
```

网页的“设备管理”面板提供“刷写固件”“慢速重试”“进入 OTA”和“下载固件包”入口。推荐先使用“刷写固件”：Python 后端会扫描 DFU bootloader，并通过 BLE 发送升级包。如果电脑 BLE 写包不稳定，保持设备在 DFU 状态并使用“慢速重试”。手机 App 刷写保留为备用方案。

## 样本格式

每条 BLE Notify 是一行 CSV 文本：

```csv
CS0,seq,device_ms,ax_mg,ay_mg,az_mg,battery_mv
```

示例：

```csv
CS0,1234,567890,12,-45,1010,3970
```

字段：

| 字段 | 含义 |
| --- | --- |
| `CS0` | CatSense V0 协议头 |
| `seq` | 单调递增样本序号 |
| `device_ms` | 设备 `millis()` 时间 |
| `ax_mg` | X 轴加速度，单位 mg |
| `ay_mg` | Y 轴加速度，单位 mg |
| `az_mg` | Z 轴加速度，单位 mg |
| `battery_mv` | 电池电压，单位 mV；不可用时为 `-1` |

## 电池读取

XIAO nRF52840 Sense 通过板载电池分压读取 `PIN_VBAT`。固件会缓存电池电压，并在采样时约每 5 秒刷新一次。

当前固件用实测值做过校准：原始 ADC 对应实际约 `3.98V`，所以 `battery_mv` 更接近真实锂电池电压。

## 命令行采集 CSV

命令行采集器输出：

```csv
host_time_iso,device_ms,seq,ax_mg,ay_mg,az_mg,battery_mv,label,cat_id,device_id
```

示例：

```csv
2026-06-20T15:30:00.123,567890,1234,12,-45,1010,3970,eat,cat001,CatSense-V0
```

## 网页采集 CSV

网页采集器会额外保存手动标记事件：

```csv
host_time_iso,device_ms,seq,ax_mg,ay_mg,az_mg,battery_mv,label,cat_id,device_id,marker,marker_time_iso,marker_note
```

其中：

- `label` 是当前生效的手动行为标签
- 空标签表示未标记
- `marker` 记录 `start:<label>` 或 `end`
- `marker_time_iso` 是标记发生的主机时间
- `marker_note` 预留给备注

训练数据优先使用网页采集器生成的 `manual_*.csv`。
