# 固件 OTA 升级

CatSense V0 支持 BLE OTA/DFU 升级。推荐使用网页里的“刷写固件”：电脑后端会通过 BLE 连接 DFU bootloader，并把 `firmware.zip` 直接刷入设备。手机 App 刷写仍保留为备用方案。

## 前提

- 设备当前运行的是支持 `DFU` 命令的固件。
- 已编译生成 `firmware.zip`。
- 电脑蓝牙可用，并且 `gateway/requirements.txt` 已安装。
- 手机安装 `nRF Connect` 或 `Adafruit Bluefruit Connect`，作为备用方案。

固件包位置：

```text
firmware/xiao_nrf52840_sense/.pio/build/seeed_xiao_nrf52840_sense/firmware.zip
```

## GitHub Actions 产物

仓库的 `CI` 会自动编译固件，并上传 `catsense-v0-firmware` 产物。下载后可以看到：

- `catsense-v0-firmware.zip`：BLE OTA/DFU 固件包。
- `catsense-v0-firmware.hex`：USB 烧录或调试用固件镜像。

如果要让本地网页“刷写固件”直接使用 Actions 下载的包，把 `catsense-v0-firmware.zip` 放到下面位置并改名为 `firmware.zip`：

```text
firmware/xiao_nrf52840_sense/.pio/build/seeed_xiao_nrf52840_sense/firmware.zip
```

## 网页直接刷写

1. 打开 CatSense 网页。
2. 停止实时采集，确认电脑离设备较近。
3. 确认“设备管理”里能看到当前 `firmware.zip` 的大小和时间。
4. 点“刷写固件”。
5. 网页会显示扫描、进入 DFU、连接 bootloader、刷写百分比和重启状态。
6. 升级完成后网页会等待设备重新广播 `CatSense-V0`，确认后显示完成。

如果设备已经因为“进入 OTA”而红灯闪烁，直接点“刷写固件”即可，后端会先扫描 DFU bootloader。

如果刷写中出现 `Operation Failed`、`notification from device`、中途断开等错误，保持设备在红灯闪烁的 DFU 状态，再点“慢速重试”。慢速模式会让 DFU bootloader 更频繁确认数据包，并降低 macOS/CoreBluetooth 堆积写包导致失败的概率。

如果网页提示“固件数据已发送，但设备仍停留在 DFU bootloader”，说明写入和校验基本完成，但 bootloader 没有退出。先点“重启 DFU”；如果仍不恢复，再按一下 reset。设备恢复 `CatSense-V0` 广播后再读取状态确认。

## 手机 App 备用流程

1. 在网页“设备管理”里点“下载固件包”，把 `catsense-v0-firmware.zip` 保存到手机或电脑。
2. 点“进入 OTA”。
3. 设备会断开当前连接并重启到 DFU/bootloader 模式。
4. 打开 `nRF Connect` 或 `Adafruit Bluefruit Connect`，连接 DFU 设备。
5. 选择刚下载的 `firmware.zip` 并开始 DFU。
6. 升级完成后设备会重启回 CatSense 固件。

## 命令流程

主机也可以直接通过 BLE UART 发送：

```text
DFU
```

设备返回：

```text
OK DFU
```

随后设备重启进入 OTA bootloader。

## 注意事项

- 进入 OTA 前建议先停止实时采集。
- 日常模式下如果有缓存数据，先点“拉取缓存”，确认保存后再升级。
- OTA 过程中不要断电。
- 如果网页提示找不到 `firmware.zip`，先在固件目录运行 `pio run`。
- 如果刷写结束后红灯仍闪烁，先点“重启 DFU”或按 reset；不要重复刷写同一个包，除非设备仍无法恢复广播。
- 如果 BLE OTA 失败，可以双击 reset 进入 USB bootloader，再用 USB 方式刷入固件。

## 当前限制

网页按钮通过 Python 后端执行 BLE DFU，不依赖浏览器 Web Bluetooth。电脑必须能扫描并连接到 DFU 设备；如果电脑 BLE 环境失败，可以改用手机 App 备用流程。当前 OTA 仍建议在近距离、USB 供电或满电状态下操作。
